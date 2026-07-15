from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_framework import Agent, Message
from agent_framework import ChatResponse as FrameworkChatResponse
from agent_framework.openai import OpenAIChatClient
from azure.cosmos.aio import CosmosClient
from openai import AsyncAzureOpenAI
from redis import Redis

from app.config import Settings
from app.credentials import (
    create_async_credential,
    create_openai_token_provider,
    create_redis_credential_provider,
)
from app.embeddings import (
    AzureOpenAIEmbeddingService,
    DeterministicEmbeddingService,
    EmbeddingService,
)
from app.models import (
    ChatResponse,
    MemoryCategory,
    MemoryItem,
    MemoryUpsertResult,
    RecalledMemory,
)
from app.providers import CosmosContextProvider, RedisHistoryProvider
from app.stores import (
    CosmosMemoryStore,
    HistoryStore,
    InMemoryHistoryStore,
    InMemoryMemoryStore,
    MemoryStore,
    RedisHistoryStore,
)

AGENT_INSTRUCTIONS = """
You are a concise assistant demonstrating persistent memory.
Use conversation history for the current session and durable memories only when relevant.
When a memory is relevant, naturally acknowledge it without exposing internal IDs or embeddings.
Never infer that a memory belongs to anyone except the current user.
""".strip()


@dataclass
class _ConversationLock:
    lock: asyncio.Lock
    users: int = 0


class DeterministicChatClient:
    def get_response(
        self,
        messages: str | Message | list[str] | list[Message],
        *,
        stream: bool = False,
        options: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Awaitable[FrameworkChatResponse]:
        if stream:
            raise ValueError("Deterministic fake mode does not use streaming")

        async def _respond() -> FrameworkChatResponse:
            normalized = messages if isinstance(messages, list) else [messages]
            framework_messages = [item for item in normalized if isinstance(item, Message)]
            user_messages = [
                message.text or "" for message in framework_messages if message.role == "user"
            ]
            current = user_messages[-1] if user_messages else str(normalized[-1])
            prior = user_messages[-2] if len(user_messages) > 1 else ""
            memories = _extract_injected_memories(framework_messages)
            instructions = (options or {}).get("instructions")
            if isinstance(instructions, str):
                memories.extend(_memory_lines(instructions))
            elif isinstance(instructions, Sequence):
                for instruction in instructions:
                    if isinstance(instruction, str):
                        memories.extend(_memory_lines(instruction))
            lowered = current.casefold()
            if "what did i just say" in lowered and prior:
                answer = f'You just said: "{prior}"'
            elif memories and any(
                word in lowered for word in ("remember", "recall", "favorite", "prefer")
            ):
                answer = "I remember: " + "; ".join(memories)
            elif lowered.startswith("remember"):
                answer = "I will keep that as durable memory for this demo user."
            else:
                answer = f'You said: "{current}".'
            return FrameworkChatResponse(
                messages=Message(role="assistant", contents=[answer]),
            )

        return _respond()


def _extract_injected_memories(messages: Sequence[Message]) -> list[str]:
    memories: list[str] = []
    for message in messages:
        if message.role not in {"system", "developer"} or not message.text:
            continue
        memories.extend(_memory_lines(message.text))
    return memories


def _memory_lines(text: str) -> list[str]:
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ")]


class MemoryAgentService:
    def __init__(
        self,
        agent: Agent,
        history_provider: RedisHistoryProvider,
        context_provider: CosmosContextProvider,
        memory_store: MemoryStore,
        embeddings: EmbeddingService,
    ) -> None:
        self._agent = agent
        self._history_provider = history_provider
        self._context_provider = context_provider
        self._memory_store = memory_store
        self._embeddings = embeddings
        self._locks: dict[str, _ConversationLock] = {}
        self._locks_guard = asyncio.Lock()

    async def chat(self, user_id: str, session_id: str, message: str) -> ChatResponse:
        key = f"{user_id}:{session_id}"
        entry = await self._conversation_lock(key)
        try:
            async with entry.lock:
                session = self._agent.create_session(session_id=session_id)
                turn_id = str(uuid4())
                session.state[self._history_provider.source_id] = {"user_id": user_id}
                session.state[self._context_provider.source_id] = {
                    "user_id": user_id,
                    "source_turn": turn_id,
                }
                response = await self._agent.run(message, session=session)
                state = session.state[self._context_provider.source_id]
                recalled = [
                    RecalledMemory.model_validate(item)
                    for item in state.get("recalled_memories", [])
                ]
                remembered = [
                    MemoryItem.model_validate(item) for item in state.get("remembered_memories", [])
                ]
                return ChatResponse(
                    response=response.text,
                    user_id=user_id,
                    session_id=session_id,
                    recalled_memories=recalled,
                    remembered_memories=remembered,
                )
        finally:
            await self._release_conversation_lock(key, entry)

    async def remember(
        self,
        user_id: str,
        text: str,
        category: MemoryCategory,
        source_turn: str,
    ) -> MemoryUpsertResult:
        embedding = await self._embeddings.embed(text)
        return await self._memory_store.remember(
            user_id,
            text,
            category,
            source_turn,
            embedding,
        )

    async def recall(self, user_id: str, query: str, limit: int) -> list[RecalledMemory]:
        embedding = await self._embeddings.embed(query)
        return await self._memory_store.recall(user_id, embedding, limit)

    @property
    def active_lock_count(self) -> int:
        return len(self._locks)

    async def _conversation_lock(self, key: str) -> _ConversationLock:
        async with self._locks_guard:
            entry = self._locks.setdefault(key, _ConversationLock(asyncio.Lock()))
            entry.users += 1
            return entry

    async def _release_conversation_lock(self, key: str, entry: _ConversationLock) -> None:
        async with self._locks_guard:
            entry.users -= 1
            if entry.users == 0 and self._locks.get(key) is entry:
                del self._locks[key]


class ServiceContainer:
    def __init__(
        self,
        agent: MemoryAgentService,
        memory_store: MemoryStore,
        history_store: HistoryStore,
        closers: Sequence[Any] = (),
    ) -> None:
        self.agent = agent
        self.memory_store = memory_store
        self._history_store = history_store
        self._closers = list(closers)

    async def close(self) -> None:
        await self._history_store.close()
        for closer in self._closers:
            result = closer.close()
            if asyncio.iscoroutine(result):
                await result


async def build_services(settings: Settings) -> ServiceContainer:
    history_store: HistoryStore
    memory_store: MemoryStore
    embeddings: EmbeddingService
    if settings.app_mode == "fake":
        history_store = InMemoryHistoryStore(time.monotonic)
        memory_store = InMemoryMemoryStore()
        embeddings = DeterministicEmbeddingService(settings.memory_dimensions)
        chat_client: Any = DeterministicChatClient()
        closers: list[Any] = []
    else:
        azure_openai_endpoint = settings.azure_openai_endpoint
        cosmos_endpoint = settings.cosmos_endpoint
        redis_host = settings.redis_host
        if not azure_openai_endpoint or not cosmos_endpoint or not redis_host:
            raise ValueError("Azure service endpoints are required in Azure mode")
        credential = create_async_credential(settings)
        token_provider = create_openai_token_provider(credential)
        openai_client = AsyncAzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=settings.azure_openai_embedding_api_version,
        )
        cosmos_client = CosmosClient(cosmos_endpoint, credential=credential)
        container = cosmos_client.get_database_client(
            settings.cosmos_database
        ).get_container_client(settings.cosmos_container)
        redis_client = Redis(
            host=redis_host,
            port=settings.redis_port,
            ssl=True,
            ssl_cert_reqs="required",
            decode_responses=True,
            credential_provider=create_redis_credential_provider(settings),
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        history_store = RedisHistoryStore(redis_client)
        memory_store = CosmosMemoryStore(container)
        embeddings = AzureOpenAIEmbeddingService(
            openai_client,
            settings.azure_openai_embedding_deployment,
            settings.memory_dimensions,
        )
        chat_client = OpenAIChatClient(
            model=settings.azure_openai_chat_deployment,
            azure_endpoint=azure_openai_endpoint,
            credential=credential,
            api_version=settings.azure_openai_api_version,
        )
        closers = [openai_client, cosmos_client, credential]

    history_provider = RedisHistoryProvider(
        history_store,
        settings.history_ttl_seconds,
        settings.history_max_messages,
    )
    context_provider = CosmosContextProvider(memory_store, embeddings, settings.recall_limit)
    framework_agent = Agent(
        client=chat_client,
        name="PersistentMemoryAgent",
        instructions=AGENT_INSTRUCTIONS,
        context_providers=[history_provider, context_provider],
        default_options={"store": False},
    )
    memory_agent = MemoryAgentService(
        framework_agent,
        history_provider,
        context_provider,
        memory_store,
        embeddings,
    )
    return ServiceContainer(memory_agent, memory_store, history_store, closers)

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from agent_framework import (
    AgentSession,
    ContextProvider,
    HistoryProvider,
    Message,
    SessionContext,
)

from app.embeddings import EmbeddingService
from app.models import MemoryCategory, MemoryItem, RecalledMemory
from app.stores import HistoryStore, MemoryStore


def _required_state_value(state: dict[str, Any] | None, name: str) -> str:
    value = state.get(name) if state else None
    if not isinstance(value, str) or not value:
        raise ValueError(f"Provider state requires {name}")
    return value


class RedisHistoryProvider(HistoryProvider):
    def __init__(self, store: HistoryStore, ttl_seconds: int, max_messages: int = 40) -> None:
        super().__init__("redis-history")
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._max_messages = max_messages

    async def get_messages(
        self,
        session_id: str | None,
        *,
        state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Message]:
        if not session_id:
            raise ValueError("History persistence requires a session ID")
        user_id = _required_state_value(state, "user_id")
        serialized = await self._store.load(user_id, session_id)
        return [Message.from_dict(json.loads(value)) for value in serialized[-self._max_messages :]]

    async def save_messages(
        self,
        session_id: str | None,
        messages: Sequence[Message],
        *,
        state: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if not session_id:
            raise ValueError("History persistence requires a session ID")
        user_id = _required_state_value(state, "user_id")
        serialized = [json.dumps(message.to_dict(), separators=(",", ":")) for message in messages]
        await self._store.append(
            user_id,
            session_id,
            serialized,
            self._ttl_seconds,
            self._max_messages,
        )


class CosmosContextProvider(ContextProvider):
    def __init__(
        self,
        store: MemoryStore,
        embeddings: EmbeddingService,
        recall_limit: int,
    ) -> None:
        super().__init__("cosmos-memory")
        self._store = store
        self._embeddings = embeddings
        self._recall_limit = recall_limit

    async def before_run(
        self,
        *,
        agent: Any,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        user_id = _required_state_value(state, "user_id")
        prompt = _latest_input_text(context)
        recalled: list[RecalledMemory] = []
        if prompt:
            embedding = await self._embeddings.embed(prompt)
            recalled = await self._store.recall(user_id, embedding, self._recall_limit)
        state["recalled_memories"] = [memory.model_dump(mode="json") for memory in recalled]
        if recalled:
            facts = "\n".join(f"- {memory.text}" for memory in recalled)
            context.extend_instructions(
                self.source_id,
                "Durable memories for this authenticated demo user follow. "
                "Use them only when relevant and never claim they belong to another user.\n"
                f"{facts}",
            )

    async def after_run(
        self,
        *,
        agent: Any,
        session: AgentSession,
        context: SessionContext,
        state: dict[str, Any],
    ) -> None:
        user_id = _required_state_value(state, "user_id")
        source_turn = _required_state_value(state, "source_turn")
        text = _latest_input_text(context)
        remembered: list[MemoryItem] = []
        for fact, category in extract_durable_facts(text):
            embedding = await self._embeddings.embed(fact)
            result = await self._store.remember(
                user_id,
                fact,
                category,
                source_turn,
                embedding,
            )
            remembered.append(MemoryItem.from_record(result.memory))
        state["remembered_memories"] = [memory.model_dump(mode="json") for memory in remembered]


def _latest_input_text(context: SessionContext) -> str:
    for message in reversed(context.input_messages):
        if message.role == "user" and isinstance(message.text, str):
            return message.text.strip()
    return ""


def extract_durable_facts(text: str) -> list[tuple[str, MemoryCategory]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    explicit = re.match(r"(?i)^remember(?:\s+that)?\s+(.+)$", normalized)
    if explicit:
        return [(explicit.group(1).rstrip("."), "explicit")]
    if re.match(r"(?i)^my\s+.{1,120}\s+is\s+.{1,500}[.!]?$", normalized):
        category: MemoryCategory = (
            "preference"
            if re.search(r"(?i)\b(favorite|preferred|preference)\b", normalized)
            else "fact"
        )
        return [(normalized.rstrip("."), category)]
    if re.match(r"(?i)^i\s+(?:live|work|study|prefer)\s+.{1,500}[.!]?$", normalized):
        category = "preference" if re.match(r"(?i)^i\s+prefer\b", normalized) else "fact"
        return [(normalized.rstrip("."), category)]
    return []

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import ContainerProxy
from redis import Redis

from app.models import (
    MemoryCategory,
    MemoryRecord,
    MemoryUpsertResult,
    RecalledMemory,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def normalize_memory_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def memory_content_hash(text: str) -> str:
    normalized = normalize_memory_text(text).casefold().rstrip(" .!?")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class HistoryStore(Protocol):
    async def load(self, user_id: str, session_id: str) -> list[str]: ...

    async def append(
        self,
        user_id: str,
        session_id: str,
        messages: Sequence[str],
        ttl_seconds: int,
        max_messages: int,
    ) -> None: ...

    async def close(self) -> None: ...


class InMemoryHistoryStore:
    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._items: dict[str, tuple[float, list[str]]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def key(user_id: str, session_id: str) -> str:
        return f"session:{user_id}:{session_id}"

    async def load(self, user_id: str, session_id: str) -> list[str]:
        key = self.key(user_id, session_id)
        async with self._lock:
            stored = self._items.get(key)
            if not stored:
                return []
            expires_at, messages = stored
            if expires_at <= self._now():
                del self._items[key]
                return []
            return list(messages)

    async def append(
        self,
        user_id: str,
        session_id: str,
        messages: Sequence[str],
        ttl_seconds: int,
        max_messages: int,
    ) -> None:
        key = self.key(user_id, session_id)
        async with self._lock:
            existing = self._items.get(key)
            history = list(existing[1]) if existing and existing[0] > self._now() else []
            history.extend(messages)
            self._items[key] = (self._now() + ttl_seconds, history[-max_messages:])

    async def close(self) -> None:
        return None


class RedisHistoryStore:
    def __init__(self, client: Redis, key_prefix: str = "session") -> None:
        self._client = client
        self._key_prefix = key_prefix

    def key(self, user_id: str, session_id: str) -> str:
        return f"{self._key_prefix}:{user_id}:{session_id}"

    async def load(self, user_id: str, session_id: str) -> list[str]:
        values = await asyncio.to_thread(self._client.lrange, self.key(user_id, session_id), 0, -1)
        return [value.decode("utf-8") if isinstance(value, bytes) else value for value in values]

    async def append(
        self,
        user_id: str,
        session_id: str,
        messages: Sequence[str],
        ttl_seconds: int,
        max_messages: int,
    ) -> None:
        if not messages:
            return
        key = self.key(user_id, session_id)

        def _append() -> None:
            with self._client.pipeline(transaction=True) as pipeline:
                pipeline.rpush(key, *messages)
                pipeline.ltrim(key, -max_messages, -1)
                pipeline.expire(key, ttl_seconds)
                pipeline.execute()

        await asyncio.to_thread(_append)

    async def close(self) -> None:
        await asyncio.to_thread(self._client.close)


class MemoryStore(Protocol):
    async def remember(
        self,
        user_id: str,
        text: str,
        category: MemoryCategory,
        source_turn: str,
        embedding: Sequence[float],
    ) -> MemoryUpsertResult: ...

    async def recall(
        self, user_id: str, embedding: Sequence[float], limit: int
    ) -> list[RecalledMemory]: ...

    async def list_memories(self, user_id: str, limit: int) -> list[MemoryRecord]: ...

    async def forget(self, user_id: str, memory_id: str) -> bool: ...


class InMemoryMemoryStore:
    def __init__(self, now: Callable[[], datetime] = _utcnow) -> None:
        self._now = now
        self._items: dict[tuple[str, str], MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def remember(
        self,
        user_id: str,
        text: str,
        category: MemoryCategory,
        source_turn: str,
        embedding: Sequence[float],
    ) -> MemoryUpsertResult:
        normalized = normalize_memory_text(text)
        content_hash = memory_content_hash(normalized)
        memory_id = hashlib.sha256(f"{user_id}\0{content_hash}".encode()).hexdigest()[:32]
        now = self._now()
        key = (user_id, memory_id)
        async with self._lock:
            existing = self._items.get(key)
            record = MemoryRecord(
                id=memory_id,
                user_id=user_id,
                text=normalized,
                category=category,
                source_turn=source_turn,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                embedding=list(embedding),
                content_hash=content_hash,
            )
            self._items[key] = record
        return MemoryUpsertResult(memory=record, created=existing is None)

    async def recall(
        self, user_id: str, embedding: Sequence[float], limit: int
    ) -> list[RecalledMemory]:
        async with self._lock:
            records = [record for (owner, _), record in self._items.items() if owner == user_id]
        ranked = sorted(
            (
                RecalledMemory(
                    **record.model_dump(exclude={"embedding", "content_hash", "user_id"}),
                    distance=_cosine_distance(record.embedding, embedding),
                )
                for record in records
            ),
            key=lambda memory: memory.distance,
        )
        return ranked[:limit]

    async def list_memories(self, user_id: str, limit: int) -> list[MemoryRecord]:
        async with self._lock:
            records = [record for (owner, _), record in self._items.items() if owner == user_id]
        return sorted(records, key=lambda record: record.updated_at, reverse=True)[:limit]

    async def forget(self, user_id: str, memory_id: str) -> bool:
        async with self._lock:
            return self._items.pop((user_id, memory_id), None) is not None


class CosmosMemoryStore:
    def __init__(self, container: ContainerProxy) -> None:
        self._container = container

    async def remember(
        self,
        user_id: str,
        text: str,
        category: MemoryCategory,
        source_turn: str,
        embedding: Sequence[float],
    ) -> MemoryUpsertResult:
        normalized = normalize_memory_text(text)
        content_hash = memory_content_hash(normalized)
        memory_id = hashlib.sha256(f"{user_id}\0{content_hash}".encode()).hexdigest()[:32]
        now = _utcnow()
        try:
            existing = await self._container.read_item(item=memory_id, partition_key=user_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            existing = None
        record = MemoryRecord(
            id=memory_id,
            user_id=user_id,
            text=normalized,
            category=category,
            source_turn=source_turn,
            created_at=datetime.fromisoformat(existing["created_at"]) if existing else now,
            updated_at=now,
            embedding=list(embedding),
            content_hash=content_hash,
        )
        await self._container.upsert_item(record.model_dump(mode="json"))
        return MemoryUpsertResult(memory=record, created=existing is None)

    async def recall(
        self, user_id: str, embedding: Sequence[float], limit: int
    ) -> list[RecalledMemory]:
        query = """
            SELECT TOP @limit
                c.id, c.text, c.category, c.source_turn, c.created_at, c.updated_at,
                VectorDistance(c.embedding, @embedding) AS distance
            FROM c
            WHERE c.user_id = @user_id
            ORDER BY VectorDistance(c.embedding, @embedding)
        """
        items = self._container.query_items(
            query=query,
            parameters=[
                {"name": "@limit", "value": limit},
                {"name": "@user_id", "value": user_id},
                {"name": "@embedding", "value": list(embedding)},
            ],
            partition_key=user_id,
        )
        return [RecalledMemory.model_validate(item) async for item in items]

    async def list_memories(self, user_id: str, limit: int) -> list[MemoryRecord]:
        query = """
            SELECT TOP @limit *
            FROM c
            WHERE c.user_id = @user_id
            ORDER BY c.updated_at DESC
        """
        items = self._container.query_items(
            query=query,
            parameters=[
                {"name": "@limit", "value": limit},
                {"name": "@user_id", "value": user_id},
            ],
            partition_key=user_id,
        )
        return [MemoryRecord.model_validate(item) async for item in items]

    async def forget(self, user_id: str, memory_id: str) -> bool:
        try:
            await self._container.delete_item(item=memory_id, partition_key=user_id)
        except cosmos_exceptions.CosmosResourceNotFoundError:
            return False
        return True


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 1.0
    return 1.0 - (dot / (left_norm * right_norm))

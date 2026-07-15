from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

BoundedId = Annotated[
    str,
    Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$"),
]
MessageText = Annotated[str, Field(min_length=1, max_length=8000)]
MemoryText = Annotated[str, Field(min_length=1, max_length=2000)]
MemoryCategory = Literal["fact", "preference", "instruction", "explicit"]


class ChatRequest(BaseModel):
    user_id: BoundedId
    session_id: BoundedId
    message: MessageText


class RememberRequest(BaseModel):
    user_id: BoundedId
    text: MemoryText
    category: MemoryCategory = "explicit"
    source_turn: Annotated[str, Field(min_length=1, max_length=128)] = "explicit-api"


class RecallRequest(BaseModel):
    user_id: BoundedId
    query: MessageText
    limit: int = Field(default=5, ge=1, le=10)


class MemoryRecord(BaseModel):
    id: str
    user_id: str
    text: str
    category: MemoryCategory
    source_turn: str
    created_at: datetime
    updated_at: datetime
    embedding: list[float]
    content_hash: str


class MemoryItem(BaseModel):
    id: str
    text: str
    category: MemoryCategory
    source_turn: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_record(cls, record: MemoryRecord) -> MemoryItem:
        data = record.model_dump(exclude={"embedding", "content_hash", "user_id"})
        return cls.model_validate(data)


class RecalledMemory(MemoryItem):
    distance: float


class MemoryUpsertResult(BaseModel):
    memory: MemoryRecord
    created: bool


class RememberResponse(BaseModel):
    memory: MemoryItem
    created: bool


class RecallResponse(BaseModel):
    memories: list[RecalledMemory]


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]


class ForgetResponse(BaseModel):
    forgotten: bool


class ChatResponse(BaseModel):
    response: str
    user_id: str
    session_id: str
    recalled_memories: list[RecalledMemory]
    remembered_memories: list[MemoryItem]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    mode: Literal["fake", "azure"]

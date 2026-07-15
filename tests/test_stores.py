from __future__ import annotations

import json

import pytest
from agent_framework import Message

from app.providers import RedisHistoryProvider
from app.stores import InMemoryHistoryStore


class MutableClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


@pytest.mark.asyncio
async def test_history_provider_round_trips_framework_messages_and_applies_ttl() -> None:
    clock = MutableClock()
    store = InMemoryHistoryStore(clock)
    provider = RedisHistoryProvider(store, ttl_seconds=60)
    state = {"user_id": "user-one"}
    message = Message(
        role="user",
        contents=["hello"],
        additional_properties={"trace": "preserved"},
    )

    await provider.save_messages("session-one", [message], state=state)

    restored = await provider.get_messages("session-one", state=state)
    assert restored[0].text == "hello"
    assert restored[0].additional_properties["trace"] == "preserved"
    raw = await store.load("user-one", "session-one")
    assert json.loads(raw[0])["role"] == "user"

    clock.value += 61
    assert await provider.get_messages("session-one", state=state) == []


@pytest.mark.asyncio
async def test_history_is_scoped_by_user_and_session() -> None:
    store = InMemoryHistoryStore(lambda: 100.0)
    provider = RedisHistoryProvider(store, ttl_seconds=60)
    await provider.save_messages(
        "same-session",
        [Message(role="user", contents=["private"])],
        state={"user_id": "user-one"},
    )

    assert (
        await provider.get_messages(
            "same-session",
            state={"user_id": "user-two"},
        )
        == []
    )


@pytest.mark.asyncio
async def test_history_is_bounded_to_recent_messages() -> None:
    store = InMemoryHistoryStore(lambda: 100.0)
    provider = RedisHistoryProvider(store, ttl_seconds=60, max_messages=4)
    state = {"user_id": "user-one"}

    for index in range(6):
        await provider.save_messages(
            "session-one",
            [Message(role="user", contents=[f"message-{index}"])],
            state=state,
        )

    restored = await provider.get_messages("session-one", state=state)
    assert [message.text for message in restored] == [
        "message-2",
        "message-3",
        "message-4",
        "message-5",
    ]

from __future__ import annotations

from typing import Any

import pytest
from agent_framework import AgentSession, Message, SessionContext

from app.embeddings import DeterministicEmbeddingService
from app.providers import CosmosContextProvider, extract_durable_facts
from app.stores import InMemoryMemoryStore


@pytest.mark.asyncio
async def test_context_provider_recalls_and_extracts_durable_memory() -> None:
    store = InMemoryMemoryStore()
    embeddings = DeterministicEmbeddingService(dimensions=32)
    provider = CosmosContextProvider(store, embeddings, recall_limit=3)
    seed_embedding = await embeddings.embed("favorite color teal")
    await store.remember(
        "user-one",
        "My favorite color is teal",
        "preference",
        "seed",
        seed_embedding,
    )
    context = SessionContext(
        session_id="session-one",
        input_messages=[Message(role="user", contents=["What is my favorite color?"])],
    )
    state: dict[str, Any] = {"user_id": "user-one", "source_turn": "turn-one"}

    await provider.before_run(
        agent=object(),
        session=AgentSession(session_id="session-one"),
        context=context,
        state=state,
    )

    assert state["recalled_memories"][0]["text"] == "My favorite color is teal"
    assert any("My favorite color is teal" in instruction for instruction in context.instructions)

    remember_context = SessionContext(
        session_id="session-one",
        input_messages=[Message(role="user", contents=["Remember that my project is Northstar."])],
    )
    await provider.after_run(
        agent=object(),
        session=AgentSession(session_id="session-one"),
        context=remember_context,
        state=state,
    )
    listed = await store.list_memories("user-one", 10)
    assert any(memory.text == "my project is Northstar" for memory in listed)


def test_durable_fact_extraction_is_conservative() -> None:
    assert extract_durable_facts("How is the weather?") == []
    assert extract_durable_facts("My favorite editor is VS Code.") == [
        ("My favorite editor is VS Code", "preference")
    ]
    assert extract_durable_facts("Remember that I use dark mode.") == [
        ("I use dark mode", "explicit")
    ]

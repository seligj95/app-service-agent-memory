from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.agent import ServiceContainer
from app.config import Settings
from app.main import create_app


def test_complete_fake_mode_memory_lifecycle() -> None:
    with TestClient(create_app(Settings(app_mode="fake"))) as client:
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok", "mode": "fake"}

        first = client.post(
            "/api/chat",
            json={
                "user_id": "user-alpha",
                "session_id": "session-one",
                "message": "The launch codename is Aurora.",
            },
        )
        assert first.status_code == 200

        history = client.post(
            "/api/chat",
            json={
                "user_id": "user-alpha",
                "session_id": "session-one",
                "message": "What did I just say?",
            },
        )
        assert history.status_code == 200
        assert "Aurora" in history.json()["response"]

        remembered = client.post(
            "/api/memories/remember",
            json={
                "user_id": "user-alpha",
                "text": "My favorite launch color is teal.",
                "category": "explicit",
            },
        )
        assert remembered.status_code == 200
        memory_id = remembered.json()["memory"]["id"]

        duplicate = client.post(
            "/api/memories/remember",
            json={
                "user_id": "user-alpha",
                "text": "  my favorite launch color is teal  ",
                "category": "explicit",
            },
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["created"] is False
        assert duplicate.json()["memory"]["id"] == memory_id

        recalled_chat = client.post(
            "/api/chat",
            json={
                "user_id": "user-alpha",
                "session_id": "session-two",
                "message": "What is my favorite launch color?",
            },
        )
        assert recalled_chat.status_code == 200
        assert any(
            "teal" in memory["text"].lower() for memory in recalled_chat.json()["recalled_memories"]
        )

        listed = client.get("/api/users/user-alpha/memories?limit=10")
        assert listed.status_code == 200
        assert any(memory["id"] == memory_id for memory in listed.json()["memories"])

        forgotten = client.delete(f"/api/users/user-alpha/memories/{memory_id}")
        assert forgotten.status_code == 200
        assert forgotten.json()["forgotten"] is True

        recalled = client.post(
            "/api/memories/recall",
            json={
                "user_id": "user-alpha",
                "query": "favorite launch color",
                "limit": 5,
            },
        )
        assert recalled.status_code == 200
        assert all(memory["id"] != memory_id for memory in recalled.json()["memories"])
        application = cast(FastAPI, client.app)
        services = cast(ServiceContainer, application.state.services)
        assert services.agent.active_lock_count == 0


def test_user_isolation_and_bounded_recall() -> None:
    with TestClient(create_app(Settings(app_mode="fake"))) as client:
        for index in range(12):
            response = client.post(
                "/api/memories/remember",
                json={
                    "user_id": "user-alpha",
                    "text": f"Project preference number {index}",
                    "category": "preference",
                },
            )
            assert response.status_code == 200

        other_user = client.get("/api/users/user-bravo/memories")
        assert other_user.status_code == 200
        assert other_user.json()["memories"] == []

        recall = client.post(
            "/api/memories/recall",
            json={"user_id": "user-alpha", "query": "project preference", "limit": 3},
        )
        assert recall.status_code == 200
        assert len(recall.json()["memories"]) == 3

        memory_id = recall.json()["memories"][0]["id"]
        cross_user_forget = client.delete(f"/api/users/user-bravo/memories/{memory_id}")
        assert cross_user_forget.status_code == 200
        assert cross_user_forget.json()["forgotten"] is False


def test_api_validation_bounds_ids_messages_and_limits() -> None:
    with TestClient(create_app(Settings(app_mode="fake"))) as client:
        invalid_id = client.post(
            "/api/chat",
            json={"user_id": "../bad", "session_id": "valid-session", "message": "hello"},
        )
        assert invalid_id.status_code == 422

        oversized = client.post(
            "/api/chat",
            json={
                "user_id": "valid-user",
                "session_id": "valid-session",
                "message": "x" * 8001,
            },
        )
        assert oversized.status_code == 422

        invalid_limit = client.post(
            "/api/memories/recall",
            json={"user_id": "valid-user", "query": "hello", "limit": 11},
        )
        assert invalid_limit.status_code == 422


def test_dependency_failures_are_not_returned_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(create_app(Settings(app_mode="fake"))) as client:
        application = cast(FastAPI, client.app)
        services = cast(ServiceContainer, application.state.services)
        monkeypatch.setattr(services.agent, "chat", AsyncMock(side_effect=RedisError("offline")))
        response = client.post(
            "/api/chat",
            json={
                "user_id": "valid-user",
                "session_id": "valid-session",
                "message": "hello",
            },
        )

        assert response.status_code == 503
        assert response.json()["detail"] == "Session memory is temporarily unavailable."


def test_public_demo_has_a_global_api_request_limit() -> None:
    settings = Settings(app_mode="fake", api_requests_per_minute=2)
    with TestClient(create_app(settings)) as client:
        payload = {"user_id": "valid-user", "query": "hello", "limit": 1}
        assert client.post("/api/memories/recall", json=payload).status_code == 200
        assert client.post("/api/memories/recall", json=payload).status_code == 200
        limited = client.post("/api/memories/recall", json=payload)

        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1
        assert client.get("/health").status_code == 200

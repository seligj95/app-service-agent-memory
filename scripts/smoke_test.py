#!/usr/bin/env python3
from __future__ import annotations

import argparse
from uuid import uuid4

import httpx


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the deployed memory lifecycle")
    parser.add_argument("base_url", help="Deployed application URL")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    suffix = uuid4().hex[:10]
    user_id = f"smoke-user-{suffix}"
    session_one = f"smoke-session-a-{suffix}"
    session_two = f"smoke-session-b-{suffix}"

    with httpx.Client(base_url=base_url, timeout=90, follow_redirects=True) as client:
        health = client.get("/health")
        health.raise_for_status()
        require(health.json()["status"] == "ok", "Health endpoint did not report ok")
        require(health.json()["mode"] == "azure", "Smoke test requires deployed Azure mode")

        first = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "session_id": session_one,
                "message": "The launch codename is Aurora.",
            },
        )
        first.raise_for_status()

        second = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "session_id": session_one,
                "message": "What did I just say?",
            },
        )
        second.raise_for_status()
        require("aurora" in second.json()["response"].lower(), "Same-session history was not used")

        remembered = client.post(
            "/api/memories/remember",
            json={
                "user_id": user_id,
                "text": "My favorite launch color is teal.",
                "category": "explicit",
                "source_turn": "deployment-smoke",
            },
        )
        remembered.raise_for_status()
        memory_id = remembered.json()["memory"]["id"]

        recalled_chat = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "session_id": session_two,
                "message": "What is my favorite launch color?",
            },
        )
        recalled_chat.raise_for_status()
        recalled = recalled_chat.json()["recalled_memories"]
        require(
            any(memory["id"] == memory_id for memory in recalled),
            "New-session chat did not recall the durable memory",
        )

        explicit_recall = client.post(
            "/api/memories/recall",
            json={"user_id": user_id, "query": "favorite launch color", "limit": 5},
        )
        explicit_recall.raise_for_status()
        require(
            any(memory["id"] == memory_id for memory in explicit_recall.json()["memories"]),
            "Explicit recall did not return the durable memory",
        )

        listed = client.get(f"/api/users/{user_id}/memories?limit=50")
        listed.raise_for_status()
        require(
            any(memory["id"] == memory_id for memory in listed.json()["memories"]),
            "List did not return the durable memory",
        )

        forgotten = client.delete(f"/api/users/{user_id}/memories/{memory_id}")
        forgotten.raise_for_status()
        require(forgotten.json()["forgotten"] is True, "Forget did not delete the memory")

        absent = client.post(
            "/api/memories/recall",
            json={"user_id": user_id, "query": "favorite launch color", "limit": 5},
        )
        absent.raise_for_status()
        require(
            all(memory["id"] != memory_id for memory in absent.json()["memories"]),
            "Forgotten memory still appears in recall",
        )

    print(f"SMOKE_OK base_url={base_url} user_id={user_id}")


if __name__ == "__main__":
    main()

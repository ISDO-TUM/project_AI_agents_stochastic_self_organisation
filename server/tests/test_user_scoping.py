"""Anonymous per-user data scoping via the ``X-User-Id`` header.

List endpoints only return the caller's rows plus shared (ownerless) rows;
requests without the header see everything (legacy behaviour); bulk deletes
only touch what the caller can see.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from server.db import create_trial, get_engine

ALICE = {"X-User-Id": "user-alice"}
BOB = {"X-User-Id": "user-bob"}


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Iterator[None]:
    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        yield


def _agent_payload(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": "d",
        "system_prompt": "You are helpful.",
        "provider": "openai",
        "model": "gpt-4o",
        "tools": [],
        "connections": [],
    }


async def test_agents_are_scoped_to_their_creator(client: AsyncClient) -> None:
    await client.post("/api/agents", json=_agent_payload("Alices"), headers=ALICE)
    await client.post("/api/agents", json=_agent_payload("Bobs"), headers=BOB)
    await client.post("/api/agents", json=_agent_payload("Shared"))  # no header → shared

    alice_names = {a["name"] for a in (await client.get("/api/agents", headers=ALICE)).json()}
    bob_names = {a["name"] for a in (await client.get("/api/agents", headers=BOB)).json()}
    all_names = {a["name"] for a in (await client.get("/api/agents")).json()}

    assert alice_names == {"Alices", "Shared"}
    assert bob_names == {"Bobs", "Shared"}
    assert all_names == {"Alices", "Bobs", "Shared"}


async def test_files_are_scoped_to_their_creator(client: AsyncClient) -> None:
    await client.post("/api/files", json={"name": "a.txt", "content": "A"}, headers=ALICE)
    await client.post("/api/files", json={"name": "b.txt", "content": "B"}, headers=BOB)

    alice_files = {f["name"] for f in (await client.get("/api/files", headers=ALICE)).json()}
    bob_files = {f["name"] for f in (await client.get("/api/files", headers=BOB)).json()}

    assert alice_files == {"a.txt"}
    assert bob_files == {"b.txt"}


async def test_clear_canvas_only_deletes_callers_agents(client: AsyncClient) -> None:
    await client.post("/api/agents", json=_agent_payload("Alices"), headers=ALICE)
    await client.post("/api/agents", json=_agent_payload("Bobs"), headers=BOB)

    resp = await client.delete("/api/agents", headers=ALICE)
    assert resp.status_code == 204

    remaining = {a["name"] for a in (await client.get("/api/agents")).json()}
    assert remaining == {"Bobs"}


async def test_history_trials_are_scoped(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await create_trial(conn, "P", "alice run", "swarm", user_id="user-alice")
        await create_trial(conn, "P", "bob run", "swarm", user_id="user-bob")
        await create_trial(conn, "P", "legacy run", "swarm")  # shared

    alice_resp = await client.get("/api/history/trials", headers=ALICE)
    alice = {t["description"] for t in alice_resp.json()}
    everyone = {t["description"] for t in (await client.get("/api/history/trials")).json()}

    assert alice == {"alice run", "legacy run"}
    assert everyone == {"alice run", "bob run", "legacy run"}


async def test_clear_history_only_deletes_callers_trials(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await create_trial(conn, "P", "alice run", "swarm", user_id="user-alice")
        await create_trial(conn, "P", "bob run", "swarm", user_id="user-bob")

    resp = await client.delete("/api/history/trials", headers=ALICE)
    assert resp.status_code == 204

    remaining = {t["description"] for t in (await client.get("/api/history/trials")).json()}
    assert remaining == {"bob run"}

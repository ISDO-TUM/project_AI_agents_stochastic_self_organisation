"""Tests for per-owner data isolation via the ``X-Owner-Id`` header.

Two browsers (two distinct owner ids) must never see each other's agents,
knowledge files, or simulation history, even though authentication is out of
scope. See ``server/owner.py``.
"""

from httpx import AsyncClient

_AGENT_PAYLOAD = {
    "name": "SalesBot",
    "description": "Handles inbound sales queries.",
    "system_prompt": "You are a helpful sales agent.",
    "provider": "openai",
    "model": "gpt-4o",
    "tools": [],
    "connections": [],
}

_ALICE = {"X-Owner-Id": "11111111-1111-1111-1111-111111111111"}
_BOB = {"X-Owner-Id": "22222222-2222-2222-2222-222222222222"}


async def test_agents_are_scoped_to_owner(client: AsyncClient) -> None:
    await client.post("/api/agents", json=_AGENT_PAYLOAD, headers=_ALICE)
    await client.post("/api/agents", json={**_AGENT_PAYLOAD, "name": "BobBot"}, headers=_BOB)

    alice_agents = (await client.get("/api/agents", headers=_ALICE)).json()
    bob_agents = (await client.get("/api/agents", headers=_BOB)).json()

    assert [a["name"] for a in alice_agents] == ["SalesBot"]
    assert [a["name"] for a in bob_agents] == ["BobBot"]


async def test_other_owner_cannot_read_or_mutate_agent(client: AsyncClient) -> None:
    created = (await client.post("/api/agents", json=_AGENT_PAYLOAD, headers=_ALICE)).json()
    agent_id = created["id"]

    # Bob sees Alice's agent as non-existent for every verb.
    assert (await client.get(f"/api/agents/{agent_id}", headers=_BOB)).status_code == 404
    assert (
        await client.patch(f"/api/agents/{agent_id}", json={"name": "Hijacked"}, headers=_BOB)
    ).status_code == 404
    assert (await client.delete(f"/api/agents/{agent_id}", headers=_BOB)).status_code == 404

    # Alice's agent is untouched.
    alice_view = (await client.get(f"/api/agents/{agent_id}", headers=_ALICE)).json()
    assert alice_view["name"] == "SalesBot"


async def test_knowledge_files_are_scoped_to_owner(client: AsyncClient) -> None:
    await client.post("/api/files", json={"name": "secret.txt", "content": "hi"}, headers=_ALICE)

    assert len((await client.get("/api/files", headers=_ALICE)).json()) == 1
    assert (await client.get("/api/files", headers=_BOB)).json() == []


async def test_clear_all_only_wipes_caller_data(client: AsyncClient) -> None:
    await client.post("/api/agents", json=_AGENT_PAYLOAD, headers=_ALICE)
    await client.post("/api/agents", json={**_AGENT_PAYLOAD, "name": "BobBot"}, headers=_BOB)

    # Alice clears all of *her* data.
    assert (await client.delete("/api/agents", headers=_ALICE)).status_code == 204

    assert (await client.get("/api/agents", headers=_ALICE)).json() == []
    assert len((await client.get("/api/agents", headers=_BOB)).json()) == 1


async def test_missing_header_uses_shared_bucket(client: AsyncClient) -> None:
    # No header → shared NULL bucket; an owned agent stays invisible to it.
    await client.post("/api/agents", json=_AGENT_PAYLOAD, headers=_ALICE)
    assert (await client.get("/api/agents")).json() == []

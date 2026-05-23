"""Tests for the simulation REST endpoints."""

from __future__ import annotations

import os

from httpx import AsyncClient

os.environ.setdefault("DB_PATH", ":memory:")
os.environ.setdefault("DEBUG", "true")


async def _create_agent(client: AsyncClient, name: str = "Alpha") -> str:
    resp = await client.post(
        "/api/agents/",
        json={
            "name": name,
            "description": "Test agent",
            "system_prompt": "You are a test agent.",
            "provider": "openai",
            "model": "gpt-4o",
            "tools": [],
            "connections": [],
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def test_get_blackboard_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/simulation/nonexistent-run-id/blackboard")
    assert resp.status_code == 404


async def test_seed_creates_run_and_returns_ids(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test prompt", "agent_ids": [agent_id]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "run_id" in data
    assert "thread_id" in data


async def test_get_blackboard_after_seed_returns_entries(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Analyze this contract", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]
    thread_id = seed_resp.json()["thread_id"]

    resp = await client.get(f"/api/simulation/{run_id}/blackboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "confirmed" in data
    assert "draft" in data
    assert "threads" in data
    assert len(data["confirmed"]) >= 1  # anchor entry
    assert len(data["threads"]) == 1
    assert data["threads"][0]["id"] == thread_id


async def test_get_blackboard_thread_filter(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]
    thread_id = seed_resp.json()["thread_id"]

    resp = await client.get(
        f"/api/simulation/{run_id}/blackboard",
        params={"thread_id": thread_id, "layer": "confirmed"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(e["thread_id"] == thread_id for e in data["confirmed"])
    assert data["draft"] == []


async def test_seed_disabled_without_debug_flag(client: AsyncClient, monkeypatch) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test", "agent_ids": []},
    )
    assert resp.status_code == 403


from api.simulation import _extract_reason, _extract_vote, _tally


def test_tally_ignores_unknown_votes() -> None:
    plurality, counts = _tally(
        {
            "agent_1": "unknown",
            "agent_2": "acme computers",
            "agent_3": "unknown",
        }
    )

    assert plurality == "acme computers"
    assert counts == {"acme computers": 1}


def test_tally_returns_no_plurality_when_only_unknown_votes() -> None:
    plurality, counts = _tally({"agent_1": "unknown", "agent_2": None})

    assert plurality is None
    assert counts == {}


def test_unknown_vote_is_normalized_before_tallying() -> None:
    vote = _extract_vote("I cannot find it.\nVOTE: Unknown!")

    assert vote == "unknown"
    assert _tally({"agent_1": vote}) == (None, {})


def test_extract_reason_returns_last_reason_line() -> None:
    reason = _extract_reason(
        "REASON: preliminary note\n"
        "Some explanation.\n"
        "REASON: Acme Computers was chosen due to the quote 'approved supplier' "
        "from 2026_supplier_contract.txt\n"
        "VOTE: Acme Computers"
    )

    assert (
        reason == "Acme Computers was chosen due to the quote 'approved supplier' "
        "from 2026_supplier_contract.txt"
    )

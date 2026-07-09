"""Tests for the simulation REST endpoints."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import insert

import server.topology as sim
from server.db import create_connection, create_round, create_trial, get_engine, resolve_experiment
from server.db.tables import agents
from server.market_hive.schemas import SimulationStep
from server.topology import (
    Reputation,
    TopologyController,
    _aggregate_trust,
    _apply_selection,
    _centroid_response,
    _centroid_text,
    _entity_aware_similarity,
    _extract_answer,
    _extract_entities,
    _extract_reason,
    _extract_reasoning,
    _extract_source,
    _extract_structured_response,
    _extract_vote,
    _jaccard,
    _normalise_trust,
    _parse_connect,
    _tally,
)

os.environ.setdefault("DEBUG", "true")


async def _create_agent(client: AsyncClient, name: str = "Alpha") -> str:
    resp = await client.post(
        "/api/agents",
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
    return str(resp.json()["id"])


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


async def test_get_audit_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/simulation/nonexistent-run-id/audit")
    assert resp.status_code == 404


async def test_get_audit_returns_full_trail(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Audit me", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]

    resp = await client.get(f"/api/simulation/{run_id}/audit")
    assert resp.status_code == 200
    data = resp.json()
    # Every audit section is present, even when empty.
    for key in (
        "run",
        "contract",
        "threads",
        "bids",
        "draft_entries",
        "citations",
        "votes",
        "confirmed_entries",
        "amendments",
        "reputation",
    ):
        assert key in data
    assert data["run"]["id"] == run_id
    assert data["contract"]["original_prompt"] == "Audit me"
    assert len(data["threads"]) == 1
    assert len(data["confirmed_entries"]) >= 1  # anchor
    assert len(data["draft_entries"]) == 1  # seeded proposal
    assert data["final_output"] is None


async def test_get_audit_includes_soft_deleted_entries(client: AsyncClient) -> None:
    """Soft-deleted draft entries must still surface in the audit trail (P-11)."""
    from sqlalchemy import text

    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Keep deleted", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]

    async with get_engine().connect() as conn:
        await conn.execute(
            text(
                "UPDATE draft_entries SET is_visible = false, "
                "deleted_at = CURRENT_TIMESTAMP WHERE run_id = :id"
            ),
            {"id": run_id},
        )
        await conn.commit()

    # The visible blackboard view hides it...
    bb = (await client.get(f"/api/simulation/{run_id}/blackboard")).json()
    assert bb["draft"] == []
    # ...but the audit trail preserves it.
    audit = (await client.get(f"/api/simulation/{run_id}/audit")).json()
    assert len(audit["draft_entries"]) == 1
    assert audit["draft_entries"][0]["is_visible"] is False


async def test_get_status_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/simulation/nonexistent-run-id/status")
    assert resp.status_code == 404


async def test_get_status_reports_round_and_state(client: AsyncClient) -> None:
    agent_id = await _create_agent(client)
    seed_resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Status check", "agent_ids": [agent_id]},
    )
    run_id = seed_resp.json()["run_id"]

    resp = await client.get(f"/api/simulation/{run_id}/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run_id
    assert data["status"] == "running"
    assert data["current_round"] == 1  # seeded proposal is round 1
    assert data["termination_reason"] is None
    assert data["token_usage"] == {}


async def test_seed_disabled_without_debug_flag(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEBUG", raising=False)
    resp = await client.post(
        "/api/simulation/seed",
        json={"prompt": "Test", "agent_ids": []},
    )
    assert resp.status_code == 403


async def test_get_audit_returns_soft_deleted_entries(client: AsyncClient) -> None:
    resp = await client.post("/api/simulation/seed-rich")
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    audit = await client.get(f"/api/simulation/{run_id}/audit")
    assert audit.status_code == 200
    data = audit.json()

    all_drafts = data["draft_entries"]
    deleted = [e for e in all_drafts if not e["is_visible"]]
    visible = [e for e in all_drafts if e["is_visible"]]

    assert len(deleted) >= 2, "rich seed should have at least 2 stale entries soft-deleted"
    assert len(visible) >= 4, "rich seed should have at least 4 visible entries"
    assert len(data["citations"]) >= 3
    assert len(data["confirmed_entries"]) >= 3  # 2 anchors + 1 thread anchor + findings


async def test_seed_rich_creates_expected_structure(client: AsyncClient) -> None:
    resp = await client.post("/api/simulation/seed-rich")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["thread_ids"]) == 2
    assert len(data["agent_ids"]) == 3

    run_id = data["run_id"]
    bb = await client.get(f"/api/simulation/{run_id}/blackboard")
    assert bb.status_code == 200
    bb_data = bb.json()

    assert len(bb_data["threads"]) == 2
    # At least 2 findings promoted (one per thread) + 3 anchors
    assert len(bb_data["confirmed"]) >= 4
    # Visible draft entries (soft-deleted are excluded by default)
    assert len(bb_data["draft"]) >= 3


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


def test_extract_vote_accepts_markdown_list_formatting() -> None:
    vote = _extract_vote("I found the access code.\n- **VOTE:** `Z`")

    assert vote == "z"


def test_extract_vote_accepts_hyphen_separator() -> None:
    vote = _extract_vote("REASON - The file states the answer.\nVOTE - Dylan")

    assert vote == "dylan"


def test_tally_counts_markdown_formatted_votes() -> None:
    votes = {
        "agent_1": _extract_vote("VOTE: Z"),
        "agent_2": _extract_vote("- **VOTE:** Z"),
        "agent_3": _extract_vote("1. **Vote** - `Z`"),
    }

    assert _tally(votes) == ("z", {"z": 3})


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


def test_extract_reason_accepts_markdown_list_formatting() -> None:
    reason = _extract_reason("- **REASON:** The file says code Z belongs to Dylan.")

    assert reason == "The file says code Z belongs to Dylan."


async def test_create_connection_reuses_system_connection(client: AsyncClient) -> None:
    async with get_engine().connect() as conn:
        await conn.execute(
            insert(agents).values(
                id="agent_a",
                name="Agent A",
                description="A test agent.",
                system_prompt="Answer briefly.",
                provider="openai",
                model="gpt-4o",
                tools="[]",
                connections="[]",
            )
        )
        await conn.commit()

        trial_id = await create_trial(conn, "Prompt", "Test trial", "broadcast_no_consensus")
        round_id = await create_round(conn, trial_id, 1, "broadcast")

        first_id = await create_connection(conn, round_id, None, "agent_a")
        second_id = await create_connection(conn, round_id, None, "agent_a")

    assert second_id == first_id


async def test_resolve_experiment_can_create_fresh_runs_for_same_setup(
    client: AsyncClient,
) -> None:
    await _create_agent(client, "Agent A")

    async with get_engine().connect() as conn:
        first = await resolve_experiment(
            conn,
            "Prompt",
            3,
            "bidding",
            None,
            "static",
            3,
            None,
            reuse_existing=False,
        )
        second = await resolve_experiment(
            conn,
            "Prompt",
            3,
            "bidding",
            None,
            "static",
            3,
            None,
            reuse_existing=False,
        )

    assert first != second


async def test_clear_board_preserves_history_and_stats(client: AsyncClient) -> None:
    """Clearing the canvas deletes agents but keeps the run history + statistics.

    Regression test: previously ``DELETE /api/agents`` wiped every trial and the
    FK cascade erased the per-message history, so past-run statistics vanished.
    """

    async def _make_agent(name: str) -> str:
        resp = await client.post(
            "/api/agents",
            json={
                "name": name,
                "description": "A test agent.",
                "system_prompt": "Answer briefly.",
                "provider": "openai",
                "model": "gpt-4o",
                "tools": [],
                "connections": [],
            },
        )
        assert resp.status_code == 201
        return str(resp.json()["id"])

    agent_a = await _make_agent("Agent A")
    agent_b = await _make_agent("Agent B")

    # Persist a trial with one real agent-to-agent message exchange.
    async with get_engine().connect() as conn:
        trial_id = await create_trial(conn, "Prompt", "Test trial", "broadcast_no_consensus")
        round_id = await create_round(conn, trial_id, 1, "discussion")
        await sim.record_message(conn, round_id, agent_a, agent_b, "agent_output", "hi B")
        await sim.record_message(conn, round_id, agent_b, agent_a, "agent_output", "hi A")

    # Clear the board.
    cleared = await client.delete("/api/agents")
    assert cleared.status_code == 204
    assert (await client.get("/api/agents")).json() == []

    # The trial and its messages survive.
    trials = (await client.get("/api/history/trials")).json()
    assert any(t["id"] == trial_id for t in trials)

    msgs = (await client.get("/api/history/messages", params={"trial_id": trial_id})).json()
    assert len(msgs) == 2
    # Identity and names are still attributable after the agents are gone.
    assert {m["from_agent_id"] for m in msgs} == {agent_a, agent_b}
    assert {m["from_agent_name"] for m in msgs} == {"Agent A", "Agent B"}

    # Per-agent statistics still resolve names from the snapshots.
    agent_stats = (await client.get(f"/api/statistics/trials/{trial_id}/agents")).json()
    assert {s["agent_name"] for s in agent_stats} == {"Agent A", "Agent B"}

    # Edge statistics survive with readable endpoints.
    edges = (await client.get(f"/api/statistics/trials/{trial_id}/edges")).json()
    edge_names = {(e["from_agent_name"], e["to_agent_name"]) for e in edges}
    assert ("Agent A", "Agent B") in edge_names
    assert ("Agent B", "Agent A") in edge_names


async def test_bidding_statistics_edges_include_board_after_agent_clear(
    client: AsyncClient,
) -> None:
    async def _make_agent(name: str) -> str:
        resp = await client.post(
            "/api/agents",
            json={
                "name": name,
                "description": "A test agent.",
                "system_prompt": "Answer briefly.",
                "provider": "openai",
                "model": "gpt-4o",
                "tools": [],
                "connections": [],
            },
        )
        assert resp.status_code == 201
        return str(resp.json()["id"])

    agent_a = await _make_agent("Agent A")
    agent_b = await _make_agent("Agent B")

    async with get_engine().connect() as conn:
        trial_id = await create_trial(conn, "Prompt", "Bidding trial", "bidding")
        round_id = await create_round(conn, trial_id, 2, "bidding_bids")
        await sim.record_message(conn, round_id, agent_a, agent_a, "bidding_bid", "{}")
        await sim.record_message(conn, round_id, agent_b, agent_b, "bidding_match", "{}")
        await sim.record_message(conn, round_id, agent_b, agent_b, "tool", "ignored")

    cleared = await client.delete("/api/agents")
    assert cleared.status_code == 204

    edges_resp = await client.get(f"/api/statistics/trials/{trial_id}/edges")
    assert edges_resp.status_code == 200
    edges_by_name = {edge["from_agent_name"]: edge for edge in edges_resp.json()}
    assert edges_by_name == {
        "Agent A": {
            "from_agent_id": agent_a,
            "from_agent_name": "Agent A",
            "to_agent_id": "__bidding_board__",
            "to_agent_name": "Board",
            "message_count": 1,
        },
        "Agent B": {
            "from_agent_id": agent_b,
            "from_agent_name": "Agent B",
            "to_agent_id": "__bidding_board__",
            "to_agent_name": "Board",
            "message_count": 1,
        },
    }

    summary_resp = await client.get(f"/api/statistics/trials/{trial_id}/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["total_edges"] == 2


async def test_bidding_experiment_statistics_edges_include_board(
    client: AsyncClient,
) -> None:
    async def _make_agent(name: str) -> str:
        resp = await client.post(
            "/api/agents",
            json={
                "name": name,
                "description": "A test agent.",
                "system_prompt": "Answer briefly.",
                "provider": "openai",
                "model": "gpt-4o",
                "tools": [],
                "connections": [],
            },
        )
        assert resp.status_code == 201
        return str(resp.json()["id"])

    agent_a = await _make_agent("Agent A")
    agent_b = await _make_agent("Agent B")

    async with get_engine().connect() as conn:
        exp_id = await resolve_experiment(
            conn,
            "Prompt",
            3,
            "bidding",
            None,
            "static",
            3,
            None,
        )
        trial_id = await create_trial(conn, "Prompt", "Bidding trial", "bidding", exp_id)
        round_id = await create_round(conn, trial_id, 2, "bidding_bids")
        await sim.record_message(conn, round_id, agent_a, agent_a, "bidding_bid", "{}")
        await sim.record_message(conn, round_id, agent_b, agent_b, "bidding_match", "{}")
        await sim.record_message(conn, round_id, agent_b, agent_b, "tool", "ignored")

    cleared = await client.delete("/api/agents")
    assert cleared.status_code == 204

    edges_resp = await client.get(f"/api/statistics/experiments/{exp_id}/edges")
    assert edges_resp.status_code == 200
    edges_by_name = {edge["from_agent_name"]: edge for edge in edges_resp.json()}
    assert edges_by_name == {
        "Agent A": {
            "from_agent_id": agent_a,
            "from_agent_name": "Agent A",
            "to_agent_id": "__bidding_board__",
            "to_agent_name": "Board",
            "avg_message_count": 1.0,
        },
        "Agent B": {
            "from_agent_id": agent_b,
            "from_agent_name": "Agent B",
            "to_agent_id": "__bidding_board__",
            "to_agent_name": "Board",
            "avg_message_count": 1.0,
        },
    }

    summary_resp = await client.get(f"/api/statistics/experiments/{exp_id}/summary")
    assert summary_resp.status_code == 200
    assert summary_resp.json()["avg_total_edges"] == 2.0


# ── _jaccard ─────────────────────────────────────────────────────────────────


def test_jaccard_identical_text() -> None:
    assert _jaccard("hello world", "hello world") == 1.0


def test_jaccard_disjoint_text() -> None:
    assert _jaccard("hello world", "foo bar") == 0.0


def test_jaccard_empty_text() -> None:
    assert _jaccard("", "hello") == 0.0
    assert _jaccard("hello", "") == 0.0
    assert _jaccard("", "") == 0.0


# ── _extract_entities ────────────────────────────────────────────────────────


def test_extract_entities_proper_nouns() -> None:
    ents = _extract_entities("I recommend Acme Computers for this contract.")
    assert "acme" in ents
    assert "computers" in ents


def test_extract_entities_camelcase() -> None:
    ents = _extract_entities("BetaSystems is a local vendor.")
    assert "betasystems" in ents


def test_extract_entities_alphanumeric_codes() -> None:
    ents = _extract_entities("Order PO-1234 from vendor AC-2026.")
    assert "po-1234" in ents
    assert "ac-2026" in ents


def test_extract_entities_all_caps() -> None:
    ents = _extract_entities("The IT department uses EMEA standards.")
    assert "it" in ents
    assert "emea" in ents


def test_extract_entities_filters_common_sentence_starters() -> None:
    ents = _extract_entities("Based on the analysis, this is correct.")
    assert "based" not in ents


def test_extract_entities_keeps_proper_nouns_at_sentence_start() -> None:
    ents = _extract_entities("Dylan is the manager.")
    assert "dylan" in ents


def test_extract_entities_empty_text() -> None:
    assert _extract_entities("") == set()


# ── _entity_aware_similarity ─────────────────────────────────────────────────


def test_entity_similarity_both_agree() -> None:
    a = "The approved supplier is Acme Computers with code AC-2026."
    b = "Acme Computers (AC-2026) is the sole approved vendor for hardware."
    score = _entity_aware_similarity(a, b)
    assert score > 0.5


def test_entity_similarity_both_disagree() -> None:
    a = "The approved supplier is Acme Computers with code AC-2026."
    b = "Contact BetaSystems GmbH for urgent laptop orders."
    score = _entity_aware_similarity(a, b)
    assert score < 0.2


def test_entity_similarity_no_entities_falls_back() -> None:
    a = "the quick brown fox jumps over the lazy dog"
    b = "the quick brown fox jumps over the lazy dog"
    assert _entity_aware_similarity(a, b) == _jaccard(a, b)


def test_entity_similarity_one_sided_falls_back() -> None:
    a = "the quick brown fox"
    b = "Acme Computers is approved."
    assert _entity_aware_similarity(a, b) == _jaccard(a, b)


def test_entity_similarity_empty_text() -> None:
    assert _entity_aware_similarity("", "Acme") == 0.0


# ── _normalise_trust ─────────────────────────────────────────────────────────


def test_normalise_trust_sums_to_one() -> None:
    result = _normalise_trust({"a": 0.3, "b": 0.7, "c": 0.5})
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_normalise_trust_all_zero() -> None:
    result = _normalise_trust({"a": 0.0, "b": 0.0})
    assert result == {"a": 0.5, "b": 0.5}


def test_normalise_trust_empty() -> None:
    assert _normalise_trust({}) == {}


# ── _aggregate_trust ─────────────────────────────────────────────────────────


def test_aggregate_trust_sums_incoming() -> None:
    trust = {
        "a": {"b": 0.6, "c": 0.4},
        "b": {"a": 0.3, "c": 0.7},
    }
    agg = _aggregate_trust(trust)
    assert abs(agg["a"] - 0.3) < 1e-9
    assert abs(agg["b"] - 0.6) < 1e-9
    assert abs(agg["c"] - 1.1) < 1e-9


def test_aggregate_trust_empty() -> None:
    assert _aggregate_trust({}) == {}


# ── _centroid_response ───────────────────────────────────────────────────────


def test_centroid_single_response() -> None:
    text, aid = _centroid_response({"a1": "hello world"})
    assert text == "hello world"
    assert aid == "a1"


def test_centroid_empty() -> None:
    assert _centroid_response({}) == (None, None)


def test_centroid_picks_most_similar() -> None:
    responses = {
        "a1": "the approved supplier is Acme",
        "a2": "Acme is the approved vendor",
        "a3": "contact BetaSystems for orders",
    }
    _, aid = _centroid_response(responses)
    assert aid in ("a1", "a2")


# ── _extract_answer ──────────────────────────────────────────────────────────


def test_extract_answer_simple() -> None:
    assert _extract_answer("ANSWER: Acme Computers") == "Acme Computers"


def test_extract_answer_with_markdown() -> None:
    assert _extract_answer("- **ANSWER:** Acme Computers") == "Acme Computers"


def test_extract_answer_missing() -> None:
    assert _extract_answer("I think the supplier is Acme.") is None


def test_extract_answer_takes_last() -> None:
    text = "ANSWER: BetaSystems\nOn reflection:\nANSWER: Acme Computers"
    assert _extract_answer(text) == "Acme Computers"


# ── _extract_source ──────────────────────────────────────────────────────────


def test_extract_source_with_quote() -> None:
    text = "SOURCE: 2026_master_agreement.txt — 'Vendor: Acme Computers'"
    assert _extract_source(text) == "2026_master_agreement.txt — 'Vendor: Acme Computers'"


def test_extract_source_none_value() -> None:
    assert _extract_source("SOURCE: none") == "none"


def test_extract_source_missing() -> None:
    assert _extract_source("No source provided.") is None


# ── _extract_reasoning ───────────────────────────────────────────────────────


def test_extract_reasoning_simple() -> None:
    text = "REASONING: The master agreement supersedes all prior arrangements."
    assert _extract_reasoning(text) == "The master agreement supersedes all prior arrangements."


def test_extract_reasoning_missing() -> None:
    assert _extract_reasoning("Just a plain response.") is None


# ── _extract_structured_response ─────────────────────────────────────────────


def test_extract_structured_response_full() -> None:
    text = (
        "ANSWER: Acme Computers\n"
        "SOURCE: 2026_master_agreement.txt — 'sole approved vendor'\n"
        "REASONING: The master agreement names Acme as the EMEA supplier."
    )
    result = _extract_structured_response(text)
    assert result["answer"] == "Acme Computers"
    assert result["source"] is not None
    assert result["reasoning"] is not None


def test_extract_structured_response_partial() -> None:
    text = "ANSWER: Acme Computers\nSome other text."
    result = _extract_structured_response(text)
    assert result["answer"] == "Acme Computers"
    assert result["source"] is None
    assert result["reasoning"] is None


# ── dynamic topology: CONNECT parser ────────────────────────────────────────


def test_parse_connect_reads_ids_from_last_line() -> None:
    text = "Answer.\nCONNECT: a1, a2\nMore.\nCONNECT: a3 a4\n"
    assert _parse_connect(text) == ["a3", "a4"]


def test_parse_connect_handles_brackets_and_missing_line() -> None:
    assert _parse_connect("CONNECT: [a1, a2]") == ["a1", "a2"]
    assert _parse_connect("no connect line here") == []


# ── dynamic topology: neighbour selection ───────────────────────────────────


def test_apply_selection_drops_invalid_and_self() -> None:
    out = _apply_selection(
        declared=["a2", "ghost", "a1"],
        prior=["a3"],
        valid_ids={"a1", "a2", "a3"},
        reputation={},
        k=5,
        self_id="a1",
    )
    assert out == ["a2"]


def test_apply_selection_falls_back_to_prior_when_empty() -> None:
    out = _apply_selection(
        declared=["ghost"],
        prior=["a2", "a3"],
        valid_ids={"a1", "a2", "a3"},
        reputation={},
        k=5,
        self_id="a1",
    )
    assert set(out) == {"a2", "a3"}


def test_apply_selection_ranks_by_reputation_then_caps() -> None:
    out = _apply_selection(
        declared=["a2", "a3", "a4"],
        prior=[],
        valid_ids={"a2", "a3", "a4"},
        reputation={"a2": 0.1, "a3": 0.9, "a4": 0.5},
        k=2,
        self_id="a1",
    )
    assert out == ["a3", "a4"]


def test_apply_selection_unlimited_fanout_keeps_all() -> None:
    # k <= 0 means unlimited: every validly-declared peer is kept (no cap).
    out = _apply_selection(
        declared=["a2", "a3", "a4"],
        prior=[],
        valid_ids={"a2", "a3", "a4"},
        reputation={},
        k=0,
        self_id="a1",
    )
    assert set(out) == {"a2", "a3", "a4"}


# ── dynamic topology: reputation tally + consensus proxy ────────────────────


def test_centroid_text_joins_responses() -> None:
    text = _centroid_text({"a1": "alpha beta", "a2": "gamma"})
    assert "alpha" in text and "gamma" in text


def test_reputation_rewards_grounding_and_agreement() -> None:
    rep = Reputation()
    consensus = "the supplier is acme computers"
    responses = {
        "grounded": "REASON: acme per contract.txt\nVOTE: acme computers",
        "ungrounded": "totally unrelated rambling about weather",
    }
    rep.update(responses, consensus)

    assert rep.score["grounded"] > rep.score["ungrounded"]
    assert 0.0 <= rep.score["ungrounded"] <= 1.0


# ── dynamic topology: TopologyController ────────────────────────────────────


def _topo_agents() -> list[dict[str, Any]]:
    return [
        {"id": "a1", "name": "A1", "description": "one"},
        {"id": "a2", "name": "A2", "description": "two"},
        {"id": "a3", "name": "A3", "description": "three"},
    ]


def test_controller_static_is_noop() -> None:
    seed = {"a1": ["a2"], "a2": ["a1"], "a3": []}
    ctrl = TopologyController.create("static", 3, _topo_agents(), seed)
    returned = ctrl.rewire({"a1": "CONNECT: a3", "a2": "", "a3": ""})

    assert returned == seed
    assert ctrl.incoming == seed
    assert ctrl.converged is False
    assert ctrl.prompt_suffix(_topo_agents()[0]) == ""


def test_controller_dynamic_suffix_is_pull_model() -> None:
    seed = {"a1": ["a2"], "a2": ["a1"], "a3": []}
    ctrl = TopologyController.create("dynamic", 3, _topo_agents(), seed)
    suffix = ctrl.prompt_suffix(_topo_agents()[0])
    assert "registry" in suffix.lower()
    assert "CONNECT:" in suffix
    assert "a2" not in suffix and "a3" not in suffix  # no peer ids pushed


def test_controller_dynamic_rewires_from_connect_lines() -> None:
    seed = {"a1": ["a2"], "a2": ["a1"], "a3": []}
    ctrl = TopologyController.create("dynamic", 3, _topo_agents(), seed)
    new = ctrl.rewire({"a1": "CONNECT: a3", "a2": "CONNECT: a3", "a3": "CONNECT: a1"})

    assert new["a1"] == ["a3"]
    assert new["a2"] == ["a3"]
    assert new["a3"] == ["a1"]
    assert ctrl.incoming == new


def test_controller_dynamic_converges_when_graph_stable() -> None:
    seed = {"a1": ["a2"], "a2": ["a1"], "a3": ["a1"]}
    ctrl = TopologyController.create("dynamic", 3, _topo_agents(), seed)
    ctrl.rewire({"a1": "CONNECT: a2", "a2": "CONNECT: a1", "a3": "CONNECT: a1"})
    assert ctrl.converged is True


# ── dynamic topology: _call_agent offers the registry tool ──────────────────


def _bare_agent() -> dict[str, Any]:
    return {
        "id": "a1",
        "name": "A1",
        "description": "one",
        "provider": "openai",
        "model": "m",
        "system_prompt": "",
        "tools": [],
    }


@pytest.mark.asyncio
async def test_call_agent_offers_registry_tool_when_index_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    from server.tools.builtin.registry import RegistryIndex

    captured: dict[str, Any] = {}

    async def fake_call_agent(
        prompt: str,
        *,
        provider: str,
        model: str,
        system_prompt: str | None,
        tool_names: list[str] | None,
        tool_context: dict[str, Any] | None,
    ) -> tuple[str, list[Any]]:
        captured["tool_names"] = tool_names
        captured["tool_context"] = tool_context
        return "ok", []

    monkeypatch.setattr(sim, "call_agent", fake_call_agent)

    sentinel = RegistryIndex(agents=[], texts={}, file_names={}, vectors={})
    await sim._call_agent(_bare_agent(), "hi", files={}, ruleset=None, registry=sentinel)

    assert captured["tool_names"] is not None and "registry" in captured["tool_names"]
    assert captured["tool_context"]["registry"] is sentinel
    assert captured["tool_context"]["agent_id"] == "a1"


@pytest.mark.asyncio
async def test_call_agent_omits_registry_when_index_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    captured: dict[str, Any] = {}

    async def fake_call_agent(
        prompt: str,
        *,
        provider: str,
        model: str,
        system_prompt: str | None,
        tool_names: list[str] | None,
        tool_context: dict[str, Any] | None,
    ) -> tuple[str, list[Any]]:
        captured["tool_names"] = tool_names
        return "ok", []

    monkeypatch.setattr(sim, "call_agent", fake_call_agent)

    await sim._call_agent(_bare_agent(), "hi", files={}, ruleset=None, registry=None)

    assert captured["tool_names"] is None  # static: no tools added


def test_run_topology_exposes_topology_and_fanout_params() -> None:
    import inspect

    from server.topology import run_topology

    params = inspect.signature(run_topology).parameters
    assert params["topology"].default == "static"
    assert params["fanout"].default == 3


# ── dynamic topology: engine rewires the persisted graph ────────────────────


@pytest.mark.asyncio
async def test_dynamic_broadcast_rewires_persisted_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import agents as agents_table
    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        # Everyone asks to hear from a3 -> a3 becomes a sender in round 2.
        return "my answer\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        for i, conns in (("a1", '["a2"]'), ("a2", '["a1"]'), ("a3", "[]")):
            await conn.execute(
                agents_table.insert().values(
                    id=i,
                    name=i.upper(),
                    description="x",
                    system_prompt="",
                    provider="openai",
                    model="m",
                    tools="[]",
                    connections=conns,
                )
            )
        await conn.commit()

        await sim.run_topology(
            "q", conn, rounds=2, mode="broadcast_no_consensus", topology="dynamic", fanout=3
        )

        rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "agent_to_agent")
                )
            )
            .mappings()
            .all()
        )

    # a3 is never a sender under the static seed; if it sent anything, the graph rewired.
    assert any(r["from_agent_id"] == "a3" for r in rows)


@pytest.mark.asyncio
async def test_single_agent_skips_consensus(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lone agent has no one to reconcile with, so a requested voting run is
    silently downgraded to broadcast — no empty 'No valid votes' tally appears."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import agents as agents_table
    from server.db.tables import messages, metadata, trials

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        return "REASON: because\nVOTE: yes", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))

    async with engine.connect() as conn:
        await conn.execute(
            agents_table.insert().values(
                id="solo",
                name="SOLO",
                description="x",
                system_prompt="",
                provider="openai",
                model="m",
                tools="[]",
                connections="[]",
            )
        )
        await conn.commit()

        await sim.run_topology("q", conn, rounds=2, mode="plurality_voting", topology="static")

        trial_rows = (await conn.execute(_sa_select(trials))).mappings().all()
        msg_rows = (await conn.execute(_sa_select(messages))).mappings().all()

    assert trial_rows and all(r["mode"] == "broadcast_no_consensus" for r in trial_rows)
    assert not any("No valid votes" in (r["message"] or "") for r in msg_rows)
    assert not any(r["message_type"] in ("vote_tally", "voting_tally") for r in msg_rows)


@pytest.mark.asyncio
async def test_dynamic_broadcast_bootstraps_from_empty_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fully-wireless start: no seed edges at all, yet the graph self-organises."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import agents as agents_table
    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        return "my answer\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        # Every agent starts ISOLATED — no connections drawn at all.
        for i in ("a1", "a2", "a3"):
            await conn.execute(
                agents_table.insert().values(
                    id=i,
                    name=i.upper(),
                    description="x",
                    system_prompt="",
                    provider="openai",
                    model="m",
                    tools="[]",
                    connections="[]",
                )
            )
        await conn.commit()

        await sim.run_topology(
            "q", conn, rounds=2, mode="broadcast_no_consensus", topology="dynamic", fanout=3
        )
        rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "agent_to_agent")
                )
            )
            .mappings()
            .all()
        )

    # With a static empty seed there would be zero agent-to-agent edges ever.
    # Under dynamic mode the agents discover a3 and edges appear from nothing.
    assert any(r["from_agent_id"] == "a3" for r in rows)


async def _seed_three_agents(conn: Any) -> None:
    from server.db.tables import agents as agents_table

    for i, conns in (("a1", '["a2"]'), ("a2", '["a1"]'), ("a3", "[]")):
        await conn.execute(
            agents_table.insert().values(
                id=i,
                name=i.upper(),
                description="x",
                system_prompt="",
                provider="openai",
                model="m",
                tools="[]",
                connections=conns,
            )
        )
    await conn.commit()


@pytest.mark.asyncio
async def test_dynamic_voting_rewires_persisted_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        # No stable plurality (no VOTE line) so voting never short-circuits before
        # the graph has a chance to rewire toward a3.
        return "REASON: because\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        await _seed_three_agents(conn)
        await sim.run_topology(
            "q", conn, rounds=2, mode="plurality_voting", topology="dynamic", fanout=3
        )
        rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "voting_agent_to_agent")
                )
            )
            .mappings()
            .all()
        )

    assert any(r["from_agent_id"] == "a3" for r in rows)


@pytest.mark.asyncio
async def test_dynamic_weighted_runs_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    from sqlalchemy import func as _sa_func
    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        return f"ANSWER: {agent['id']}\nSOURCE: none\nREASONING: x\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        await _seed_three_agents(conn)
        # Dynamic weighted mode must run to completion without raising — this
        # exercises the dynamic discussion prompt, the registry wiring, and the
        # trust-reconciliation path against the rewired graph.
        await sim.run_topology(
            "q", conn, rounds=3, mode="weighted_opinion_pooling", topology="dynamic", fanout=3
        )
        total = (
            await conn.execute(_sa_select(_sa_func.count()).select_from(messages))
        ).scalar_one()

    assert total > 0  # the run persisted its broadcast + discussion messages


@pytest.mark.asyncio
async def test_dynamic_voting_rewires_even_when_consensus_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug regression: the phone-book graph must rewire from CONNECT lines even
    when the plurality is already stable.

    Previously the consensus-stability ``break`` fired *before* ``rewire()``, so a
    stable answer (the common case) meant the dynamic topology never evolved and
    an isolated agent could never join. Here every agent emits a stable VOTE *and*
    a ``CONNECT: a3``; a3 starts isolated in the seed graph, so if it ever becomes
    a *sender* the graph must have rewired toward it.
    """
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        # Stable plurality across all rounds (everyone votes "x") yet everyone
        # also asks to hear from a3 next round.
        return "REASON: because\nVOTE: x\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        await _seed_three_agents(conn)
        await sim.run_topology(
            "q", conn, rounds=2, mode="plurality_voting", topology="dynamic", fanout=3
        )
        rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "voting_agent_to_agent")
                )
            )
            .mappings()
            .all()
        )

    # a3 is never a sender under the static seed; if it sent anything, the graph
    # rewired *despite* the stable plurality.
    assert any(r["from_agent_id"] == "a3" for r in rows)


@pytest.mark.asyncio
async def test_dynamic_voting_isolated_agent_uses_registry_not_global_tally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In dynamic mode a truly isolated agent must be pushed to the registry, not
    spoon-fed the global vote tally (the static fallback)."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    seen_prompts: list[tuple[str, str]] = []

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        seen_prompts.append((agent["id"], prompt))
        return "REASON: because\nVOTE: x", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))

    async with engine.connect() as conn:
        await _seed_three_agents(conn)
        await sim.run_topology(
            "q", conn, rounds=2, mode="plurality_voting", topology="dynamic", fanout=3
        )
        tally_rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "voting_tally")
                )
            )
            .mappings()
            .all()
        )

    a3_prompts = [p for aid, p in seen_prompts if aid == "a3"]
    # The isolated agent is nudged toward the registry...
    assert any("registry" in p.lower() for p in a3_prompts)
    # ...and is NOT handed the global tally fallback.
    assert all("current vote tally" not in p.lower() for p in a3_prompts)
    assert tally_rows == []


@pytest.mark.asyncio
async def test_dynamic_weighted_rewires_even_when_trust_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug regression (weighted pool): the graph must rewire from CONNECT lines
    even when trust has already stabilised (``_WEIGHT_STABILITY_K == 1`` makes
    this fire after a single round)."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from server.db.tables import messages, metadata

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async def fake_call_agent(
        agent: dict[str, Any],
        prompt: str,
        files: dict[str, str],
        ruleset: str | None = None,
        registry: Any = None,
        tables: Any = None,
    ) -> tuple[str, list[Any]]:
        # Identical answer everywhere → trust stabilises immediately, yet all
        # agents request a3 as their next-round source.
        return "ANSWER: same\nSOURCE: none\nREASONING: x\nCONNECT: a3", []

    monkeypatch.setattr(sim, "_call_agent", fake_call_agent)
    monkeypatch.setattr(sim, "load_files_by_agent", AsyncMock(return_value={}))
    monkeypatch.setattr(sim.RegistryIndex, "build", AsyncMock(return_value=object()))
    # Force the entity-aware (non-embedding) similarity path so the test is
    # deterministic regardless of embedding-backend availability.
    monkeypatch.setattr(sim, "embed_texts", AsyncMock(return_value=None))

    async with engine.connect() as conn:
        await _seed_three_agents(conn)
        await sim.run_topology(
            "q", conn, rounds=3, mode="weighted_opinion_pooling", topology="dynamic", fanout=3
        )
        rows = (
            (
                await conn.execute(
                    _sa_select(messages).where(messages.c.message_type == "weighted_agent_to_agent")
                )
            )
            .mappings()
            .all()
        )

    assert any(r["from_agent_id"] == "a3" for r in rows)


# ── API: topology/fanout request schema + route ─────────────────────────────


def test_simulation_request_defaults_topology_static() -> None:
    from server.schemas import SimulationRunRequest

    req = SimulationRunRequest(prompt="hi")
    assert req.topology == "static"
    assert req.fanout == 3

    dyn = SimulationRunRequest(prompt="hi", topology="dynamic", fanout=5)
    assert dyn.topology == "dynamic" and dyn.fanout == 5

    unlimited = SimulationRunRequest(prompt="hi", topology="dynamic", fanout=0)
    assert unlimited.fanout == 0  # 0 == unlimited fan-out


@pytest.mark.asyncio
async def test_run_route_accepts_topology_and_rejects_no_agents(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/simulation/run",
        json={"prompt": "hi", "topology": "dynamic", "fanout": 4, "mode": "plurality_voting"},
    )
    assert resp.status_code == 422
    assert "No agents" in resp.json()["detail"]


# ── M5: swarm engine streams SSE ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_swarm_run_with_no_agents_returns_422(client: AsyncClient) -> None:
    resp = await client.post("/api/simulation/run", json={"engine": "swarm", "prompt": "hi"})
    assert resp.status_code == 422
    assert "No agents" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_delete_agent_preserves_swarm_data(client: AsyncClient) -> None:
    """Deleting an agent that joined a swarm run leaves the run's history intact.

    The swarm tables carry no foreign keys to agents (their id columns are
    denormalised snapshots), so the audit trail survives the canvas being
    cleared — mirroring how topology trial history is preserved.
    """
    from sqlalchemy import text

    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        agent_id = await _create_agent(client)

    async with get_engine().connect() as conn:
        await conn.execute(text("INSERT INTO swarm_runs (id) VALUES ('run-x')"))
        await conn.execute(
            text("INSERT INTO bids (id, run_id, agent_id) VALUES ('bid-x', 'run-x', :a)"),
            {"a": agent_id},
        )
        await conn.commit()

    resp = await client.delete(f"/api/agents/{agent_id}")
    assert resp.status_code == 204

    async with get_engine().connect() as conn:
        bids = (await conn.execute(text("SELECT COUNT(*) FROM bids"))).scalar_one()
        runs = (await conn.execute(text("SELECT COUNT(*) FROM swarm_runs"))).scalar_one()
    assert bids == 1
    assert runs == 1


@pytest.mark.asyncio
async def test_swarm_run_streams_simulation_steps_as_sse(client: AsyncClient) -> None:
    # Avoid the embedding network call during agent creation.
    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    async def fake_run_swarm(config: Any, db: Any, **kwargs: Any) -> AsyncIterator[SimulationStep]:
        yield SimulationStep(type="system", msg="Contract created: analysis, single")
        yield SimulationStep(
            type="convergence", msg="Run complete.", data={"termination_reason": "max_rounds"}
        )

    with patch("server.routes.simulation.run_swarm", new=fake_run_swarm):
        resp = await client.post(
            "/api/simulation/run", json={"engine": "swarm", "prompt": "Analyze this contract"}
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    body = resp.text
    assert "data: " in body
    assert "Contract created" in body
    assert "convergence" in body


@pytest.mark.asyncio
async def test_with_keepalive_pads_slow_gaps_without_cancelling_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tick during a slow step must interleave a keepalive comment, not
    abort the step. Regression: wrapping ``it.__anext__()`` directly in
    ``asyncio.wait_for`` cancels the wrapped coroutine on every timeout tick —
    that would silently kill a genuinely slow (not hung) swarm turn instead of
    just padding the gap around it, exactly the bug this wrapper exists to
    avoid on the *proxy* side."""
    import server.routes.simulation as sim_routes

    monkeypatch.setattr(sim_routes, "_SSE_KEEPALIVE_S", 0.05)

    async def slow_steps() -> AsyncIterator[str]:
        await asyncio.sleep(0.2)
        yield "data: real\n\n"

    frames = [frame async for frame in sim_routes._with_keepalive(slow_steps())]

    assert frames.count(": keepalive\n\n") >= 2
    assert frames[-1] == "data: real\n\n"


@pytest.mark.asyncio
async def test_with_keepalive_propagates_underlying_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real failure from the wrapped stream must still surface, not vanish
    into a keepalive loop."""
    import server.routes.simulation as sim_routes

    monkeypatch.setattr(sim_routes, "_SSE_KEEPALIVE_S", 0.05)

    async def failing_steps() -> AsyncIterator[str]:
        yield "data: one\n\n"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        async for _ in sim_routes._with_keepalive(failing_steps()):
            pass


@pytest.mark.asyncio
async def test_swarm_run_unknown_parent_run_id_returns_404(client: AsyncClient) -> None:
    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    resp = await client.post(
        "/api/simulation/run",
        json={"engine": "swarm", "prompt": "p", "parent_run_id": "does-not-exist"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_swarm_run_still_running_parent_returns_409(client: AsyncClient) -> None:
    from sqlalchemy import text

    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    async with get_engine().connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO swarm_runs (id, status, mode) "
                "VALUES ('still-running', 'running', 'swarm')"
            )
        )
        await conn.commit()

    resp = await client.post(
        "/api/simulation/run",
        json={"engine": "swarm", "prompt": "p", "parent_run_id": "still-running"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_swarm_run_valid_parent_carries_session(client: AsyncClient) -> None:
    from sqlalchemy import text

    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    async with get_engine().connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO swarm_runs (id, status, mode) "
                "VALUES ('parent-done', 'completed', 'swarm')"
            )
        )
        await conn.commit()

    captured_kwargs: dict[str, Any] = {}

    async def fake_run_swarm(config: Any, db: Any, **kwargs: Any) -> AsyncIterator[SimulationStep]:
        captured_kwargs.update(kwargs)
        yield SimulationStep(type="convergence", msg="Run complete.")

    with patch("server.routes.simulation.run_swarm", new=fake_run_swarm):
        resp = await client.post(
            "/api/simulation/run",
            json={"engine": "swarm", "prompt": "p", "parent_run_id": "parent-done"},
        )

    assert resp.status_code == 200
    assert captured_kwargs.get("parent_run_id") == "parent-done"


@pytest.mark.asyncio
async def test_run_metrics_endpoint_404s_before_termination(client: AsyncClient) -> None:
    from sqlalchemy import text

    async with get_engine().connect() as conn:
        await conn.execute(
            text("INSERT INTO swarm_runs (id, status, mode) VALUES ('mid-run', 'running', 'swarm')")
        )
        await conn.commit()

    resp = await client.get("/api/simulation/mid-run/metrics")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_run_metrics_endpoint_returns_snapshot_after_termination(client: AsyncClient) -> None:
    import json

    from sqlalchemy import text

    async with get_engine().connect() as conn:
        await conn.execute(
            text(
                "INSERT INTO swarm_runs (id, status, mode) "
                "VALUES ('done-run', 'completed', 'swarm')"
            )
        )
        await conn.execute(
            text("INSERT INTO run_metrics (run_id, metrics) VALUES ('done-run', :m)"),
            {"m": json.dumps({"duplication": None, "citations": {"total": 0}})},
        )
        await conn.commit()

    resp = await client.get("/api/simulation/done-run/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["citations"]["total"] == 0
    assert body["duplication"] is None


@pytest.mark.asyncio
async def test_run_metrics_endpoint_404s_for_unknown_run(client: AsyncClient) -> None:
    resp = await client.get("/api/simulation/does-not-exist/metrics")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_swarm_run_creates_linked_experiment_and_trial(client: AsyncClient) -> None:
    """A swarm run joins the shared history: one experiment + one trial per click,
    with the ids handed to the orchestrator config for linkage."""
    from sqlalchemy import text

    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    seen_configs: list[Any] = []

    def fake_run_swarm(config: Any, db: Any, **kwargs: Any) -> AsyncIterator[SimulationStep]:
        seen_configs.append(config)

        async def stream() -> AsyncIterator[SimulationStep]:
            yield SimulationStep(type="system", msg="Run started")

        return stream()

    with patch("server.routes.simulation.run_swarm", new=fake_run_swarm):
        resp = await client.post(
            "/api/simulation/run",
            json={"engine": "swarm", "prompt": "Analyze this contract"},
            headers={"X-User-Id": "user-alice"},
        )
    assert resp.status_code == 200

    async with get_engine().connect() as conn:
        trial = (
            (
                await conn.execute(
                    text("SELECT id, mode, experiment_id, user_prompt, user_id FROM trials")
                )
            )
            .mappings()
            .fetchone()
        )
        experiment = (
            (await conn.execute(text("SELECT id, user_id FROM experiments"))).mappings().fetchone()
        )

    assert trial is not None and experiment is not None
    assert trial["mode"] == "swarm"
    assert trial["user_prompt"] == "Analyze this contract"
    assert trial["experiment_id"] == experiment["id"]
    assert trial["user_id"] == "user-alice"
    assert experiment["user_id"] == "user-alice"

    # The orchestrator config carries the linkage + owner for the run row.
    assert len(seen_configs) == 1
    config = seen_configs[0]
    assert config.trial_id == trial["id"]
    assert config.experiment_id == experiment["id"]
    assert config.user_id == "user-alice"


@pytest.mark.asyncio
async def test_run_simulation_swarm_threads_config_fields(client: AsyncClient) -> None:
    """POSTing min_rounds/max_rounds (etc.) on the swarm engine branch must
    reach the persisted SwarmRunConfig — not silently default."""
    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    seen_configs: list[Any] = []

    def fake_run_swarm(config: Any, db: Any, **kwargs: Any) -> AsyncIterator[SimulationStep]:
        seen_configs.append(config)

        async def stream() -> AsyncIterator[SimulationStep]:
            yield SimulationStep(type="system", msg="Run started")

        return stream()

    with patch("server.routes.simulation.run_swarm", new=fake_run_swarm):
        resp = await client.post(
            "/api/simulation/run",
            json={"engine": "swarm", "prompt": "test prompt", "min_rounds": 1, "max_rounds": 2},
        )

    assert resp.status_code == 200
    assert len(seen_configs) == 1
    config = seen_configs[0]
    # Defaults are min_rounds=3, max_rounds=5 — assert the sent values, not those.
    assert config.min_rounds == 1
    assert config.max_rounds == 2


@pytest.mark.asyncio
async def test_run_simulation_swarm_omitted_fields_keep_defaults(client: AsyncClient) -> None:
    """Omitting the new optional fields must leave SwarmRunConfig at its own
    defaults — zero behaviour change for existing callers."""
    with patch(
        "server.routes.agents.compute_capability_embedding",
        new=AsyncMock(return_value=None),
    ):
        await _create_agent(client)

    seen_configs: list[Any] = []

    def fake_run_swarm(config: Any, db: Any, **kwargs: Any) -> AsyncIterator[SimulationStep]:
        seen_configs.append(config)

        async def stream() -> AsyncIterator[SimulationStep]:
            yield SimulationStep(type="system", msg="Run started")

        return stream()

    with patch("server.routes.simulation.run_swarm", new=fake_run_swarm):
        resp = await client.post(
            "/api/simulation/run",
            json={"engine": "swarm", "prompt": "test prompt"},
        )

    assert resp.status_code == 200
    assert len(seen_configs) == 1
    config = seen_configs[0]
    assert config.min_rounds == 3
    assert config.max_rounds == 5
    assert config.min_takers == 2
    assert config.max_takers == 5
    assert config.token_budget == 50_000
    assert config.max_amendments == 2
    assert config.decay_rounds == 3
    assert config.invite_floor == 0.3

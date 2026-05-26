from typing import Any

import pytest

from api.schemas import ToolCall
from api.simulation import (
    _aggregate_trust,
    _build_incoming,
    _centroid_response,
    _extract_reason,
    _extract_vote,
    _normalise_trust,
    _run_weighted_pool,
    _tally,
    _weighted_consensus,
)


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


# ── Weighted pooling ─────────────────────────────────────────────────────────


def test_aggregate_trust_sums_incoming_weights() -> None:
    """Trust is summed across all sources pointing at each target."""
    trust = {
        "a": {"b": 0.7, "c": 0.3},
        "b": {"a": 0.5, "c": 0.5},
        "c": {"a": 0.4, "b": 0.6},
    }

    agg = _aggregate_trust(trust)

    assert agg["a"] == pytest.approx(0.9)  # b → 0.5  +  c → 0.4
    assert agg["b"] == pytest.approx(1.3)  # a → 0.7  +  c → 0.6
    assert agg["c"] == pytest.approx(0.8)  # a → 0.3  +  b → 0.5


def test_aggregate_trust_handles_empty() -> None:
    assert _aggregate_trust({}) == {}
    assert _aggregate_trust({"a": {}}) == {}


def test_weighted_consensus_picks_most_trusted_agent() -> None:
    """The reply from the agent with highest aggregate trust wins."""
    responses = {"a": "answer A", "b": "answer B", "c": "answer C"}
    aggregate = {"a": 0.4, "b": 1.2, "c": 0.6}

    text, aid = _weighted_consensus(responses, aggregate)

    assert aid == "b"
    assert text == "answer B"


def test_weighted_consensus_falls_back_to_centroid_when_no_trust() -> None:
    """Disconnected graph → all aggregate trust zero → centroid fallback."""
    # Two agents agree (overlap=cat), one diverges. Centroid picks an
    # agreeing reply, never the outlier.
    responses = {
        "a": "the cat sat on the mat",
        "b": "the cat is here",
        "c": "totally unrelated zzz",
    }
    aggregate: dict[str, float] = {}  # no edges, no trust

    text, aid = _weighted_consensus(responses, aggregate)

    assert aid in {"a", "b"}
    assert text == responses[aid]


def test_weighted_consensus_returns_none_for_empty_responses() -> None:
    assert _weighted_consensus({}, {}) == (None, None)


def test_weighted_consensus_breaks_ties_deterministically() -> None:
    """Equal trust → longer reply wins so test runs are reproducible."""
    responses = {"a": "short", "b": "a longer reply"}
    aggregate = {"a": 0.5, "b": 0.5}

    _text, aid = _weighted_consensus(responses, aggregate)

    assert aid == "b"


def test_normalise_trust_sums_to_one() -> None:
    out = _normalise_trust({"a": 2.0, "b": 1.0, "c": 1.0})

    assert sum(out.values()) == 1.0
    assert out == {"a": 0.5, "b": 0.25, "c": 0.25}


def test_normalise_trust_handles_zero_total_with_uniform_fallback() -> None:
    out = _normalise_trust({"a": 0.0, "b": 0.0})

    assert out == {"a": 0.5, "b": 0.5}


def test_normalise_trust_handles_empty() -> None:
    assert _normalise_trust({}) == {}


# ── Weighted pool end-to-end (mock agents) ───────────────────────────────────


def _make_agent(agent_id: str, connections: list[str]) -> dict[str, Any]:
    """Build the minimal agent dict the simulation engine expects."""
    return {
        "id": agent_id,
        "name": f"Agent {agent_id}",
        "description": "",
        "system_prompt": "",
        "provider": "openai",
        "model": "gpt-4o-mini",
        "tools": [],
        "connections": connections,
    }


async def test_weighted_pool_converges_with_stable_responses() -> None:
    """When responses stop changing, trust stabilises and the run converges
    within the K-round stability window.
    """
    agents = [
        _make_agent("a", ["b", "c"]),
        _make_agent("b", ["a", "c"]),
        _make_agent("c", ["a", "b"]),
    ]
    incoming = _build_incoming(agents)
    fixed_replies = {"a": "Dylan", "b": "Dylan", "c": "Dylan"}

    async def fake_call(agent: dict[str, Any], _prompt: str) -> tuple[str, list[ToolCall]]:
        return fixed_replies[agent["id"]], []

    outcome = await _run_weighted_pool(
        prompt="Who is the manager?",
        agents=agents,
        incoming=incoming,
        call=fake_call,
        rounds=5,
        agent_context=None,
    )

    assert outcome.converged is True
    assert outcome.rounds_used >= 2  # K=2 stability required
    assert outcome.consensus == "Dylan"
    assert outcome.consensus_agent_id in {"a", "b", "c"}


async def test_weighted_pool_handles_disconnected_graph() -> None:
    """No edges → broadcast-only, fall back to the textual centroid and
    report unconverged."""
    agents = [
        _make_agent("a", []),
        _make_agent("b", []),
    ]
    incoming = _build_incoming(agents)
    replies = {"a": "alpha alpha alpha", "b": "alpha alpha beta"}

    async def fake_call(agent: dict[str, Any], _prompt: str) -> tuple[str, list[ToolCall]]:
        return replies[agent["id"]], []

    outcome = await _run_weighted_pool(
        prompt="ignored",
        agents=agents,
        incoming=incoming,
        call=fake_call,
        rounds=3,
        agent_context=None,
    )

    assert outcome.converged is False
    assert outcome.rounds_used == 0
    assert outcome.consensus in set(replies.values())
    # _centroid_response should still attribute the answer to one of the agents.
    assert outcome.consensus_agent_id in {"a", "b"}


async def test_weighted_pool_propagates_agent_errors_without_crashing() -> None:
    """One agent raising during the broadcast must not break the run; its
    error is captured as its response and the rest of the pool proceeds."""
    agents = [
        _make_agent("a", ["b"]),
        _make_agent("b", ["a"]),
    ]
    incoming = _build_incoming(agents)

    async def fake_call(agent: dict[str, Any], _prompt: str) -> tuple[str, list[ToolCall]]:
        if agent["id"] == "a":
            raise RuntimeError("boom")
        return "stable answer", []

    outcome = await _run_weighted_pool(
        prompt="anything",
        agents=agents,
        incoming=incoming,
        call=fake_call,
        rounds=2,
        agent_context=None,
    )

    # Run completes, produces a consensus, and never raises.
    assert outcome.consensus is not None


def test_centroid_response_single_reply_round_trips() -> None:
    assert _centroid_response({"a": "hello"}) == ("hello", "a")


def test_centroid_response_empty_returns_none() -> None:
    assert _centroid_response({}) == (None, None)

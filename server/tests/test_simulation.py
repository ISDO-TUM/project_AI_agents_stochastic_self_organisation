from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import insert

from server.db import create_connection, create_round, create_trial, get_engine
from server.db.tables import agents
from server.simulation import (
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
    import server.simulation as sim
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
    import server.simulation as sim

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

    from server.simulation import run_topology

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

    import server.simulation as sim
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
async def test_dynamic_broadcast_bootstraps_from_empty_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fully-wireless start: no seed edges at all, yet the graph self-organises."""
    from unittest.mock import AsyncMock

    from sqlalchemy import select as _sa_select
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    import server.simulation as sim
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

    import server.simulation as sim
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

    import server.simulation as sim
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

    import server.simulation as sim
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

    import server.simulation as sim
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

    import server.simulation as sim
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

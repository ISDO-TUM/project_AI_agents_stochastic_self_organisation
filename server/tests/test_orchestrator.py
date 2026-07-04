"""Orchestrator tests — run_swarm wiring (PRD §11.2).

These drain the ``run_swarm`` async generator against an in-memory SQLite DB,
asserting on the persisted state and the emitted ``SimulationStep`` stream. No
network / LLM is required: the fallback contract source degrades to a null
embedding when no embedding API key is present.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.auction import AuctionEngine
from server.market_hive.blackboard import Blackboard
from server.market_hive.orchestrator import AgentRunner, _default_agent_runner, run_swarm
from server.market_hive.schemas import SimulationStep, SwarmRunConfig
from server.market_hive.tools import (
    ApproveSynthesisInput,
    ApproveSynthesisTool,
    CiteInput,
    CiteTool,
    DisputeInput,
    DisputeTool,
    PostToBlackboardInput,
    PostToBlackboardTool,
    ReviseSynthesisInput,
    ReviseSynthesisTool,
)
from server.schemas import ToolCall


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Iterator[None]:
    """Keep the swarm offline + deterministic: never call the embedding API.

    The contract source and every blackboard post embed their content; with an
    API key present that would hit the network. Returning ``None`` makes the
    engines fall back to their zero-vector path, exactly as they do offline.
    """
    with (
        patch("server.market_hive.blackboard.embed_texts", new=AsyncMock(return_value=None)),
        patch("server.market_hive.contract_source.embed_texts", new=AsyncMock(return_value=None)),
    ):
        yield


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        yield conn


async def _drain(
    config: SwarmRunConfig, db: AsyncConnection, **kwargs: Any
) -> list[SimulationStep]:
    return [step async for step in run_swarm(config, db, **kwargs)]


async def _insert_agent(db: AsyncConnection, agent_id: str, name: str) -> None:
    await db.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :name, 'desc', 'You are helpful.', 'openai', 'gpt-4o')"
        ),
        {"id": agent_id, "name": name},
    )
    await db.commit()


def _scripted_runner(*, abstainers: frozenset[str] = frozenset()) -> AgentRunner:
    """A full-pipeline ``AgentRunner`` that performs real tool side-effects.

    Branches on the offered tool set to act for each phase exactly as the real
    tools would — records bids/abstentions, posts a round-1 proposal, votes on
    co-workers' proposals, and in discussion rounds posts a reply citing a
    co-worker — so the whole run is driven deterministically with no LLM.
    ``abstainers`` (by agent name) opt out of the auction.
    """

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        db = tool_context["db"]
        run_id = tool_context["run_id"]
        agent_id = tool_context["agent_id"]

        if "submit_bid" in tool_names:
            engine = AuctionEngine(db)
            if agent["name"] in abstainers:
                await engine.record_abstention(
                    run_id=run_id,
                    agent_id=agent_id,
                    contract_id=tool_context["contract_id"],
                    reason="outside my domain",
                )
                return "", [ToolCall(name="abstain", input={"reason": "n/a"}, output="{}")]
            await engine.record_bid(
                run_id=run_id,
                agent_id=agent_id,
                contract_id=tool_context["contract_id"],
                justification="I can contribute",
                preliminary_score=tool_context["preliminary_score"],
            )
            return "", [ToolCall(name="submit_bid", input={"justification": "yes"}, output="{}")]

        # Discussion round (rounds 2+): post a reply and cite a co-worker's proposal.
        # Checked before the round-1 branch because discussion offers post AND cite.
        if "cite" in tool_names:
            thread_id = tool_context["thread_id"]
            round_ = tool_context["round"]
            bb = Blackboard(db)
            entry_id = await bb.post(
                run_id=run_id,
                thread_id=thread_id,
                author_id=agent_id,
                content=f"{agent['name']} reply r{round_}",
                entry_type="reply",
                round=round_,
            )
            calls = [
                ToolCall(
                    name="post_to_blackboard",
                    input={"entry_type": "reply", "thread_id": thread_id},
                    output=json.dumps({"entry_id": entry_id}),
                )
            ]
            others = (
                await db.execute(
                    text(
                        "SELECT id FROM draft_entries WHERE run_id = :r AND thread_id = :t "
                        "AND round = 1 AND entry_type = 'proposal' AND author_id <> :a"
                    ),
                    {"r": run_id, "t": thread_id, "a": agent_id},
                )
            ).fetchall()
            cited = [eid for (eid,) in others]
            if cited:
                await bb.cite(
                    run_id=run_id,
                    citing_agent_id=agent_id,
                    entry_ids=cited,
                    round=round_,
                    citing_entry_id=entry_id,
                )
                calls.append(ToolCall(name="cite", input={"entry_ids": cited}, output="{}"))
            return "", calls

        if "post_to_blackboard" in tool_names:
            thread_id = tool_context["thread_id"]
            entry_id = await Blackboard(db).post(
                run_id=run_id,
                thread_id=thread_id,
                author_id=agent_id,
                content=f"{agent['name']} proposal",
                entry_type="proposal",
                round=tool_context["round"],
            )
            return "", [
                ToolCall(
                    name="post_to_blackboard",
                    input={"entry_type": "proposal", "thread_id": thread_id},
                    output=json.dumps({"entry_id": entry_id}),
                )
            ]

        if "vote" in tool_names:
            thread_id = tool_context["thread_id"]
            rows = (
                await db.execute(
                    text(
                        "SELECT id FROM draft_entries WHERE run_id = :r AND thread_id = :t "
                        "AND round = 1 AND entry_type = 'proposal' AND author_id <> :a"
                    ),
                    {"r": run_id, "t": thread_id, "a": agent_id},
                )
            ).fetchall()
            bb = Blackboard(db)
            calls = []
            for (eid,) in rows:
                await bb.vote(run_id=run_id, voter_id=agent_id, entry_id=eid, thread_id=thread_id)
                calls.append(ToolCall(name="vote", input={"entry_id": eid}, output="{}"))
            return "", calls

        return "", []

    return runner


# ── M0: skeleton ──────────────────────────────────────────────────────────────


async def test_run_swarm_creates_run_contract_and_thread(db: AsyncConnection) -> None:
    await _drain(SwarmRunConfig(prompt="Analyze this energy contract"), db)

    # With no agents the auction aborts after creation — creation is what M0 owns;
    # the completed/aborted lifecycle is covered by the M1 auction tests below.
    run = (await db.execute(text("SELECT id, status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None

    contract = (
        (await db.execute(text("SELECT original_prompt, task_nature FROM contracts")))
        .mappings()
        .fetchone()
    )
    assert contract is not None
    assert contract["original_prompt"] == "Analyze this energy contract"
    assert contract["task_nature"] == "single"

    threads = (await db.execute(text("SELECT id FROM threads"))).fetchall()
    assert len(threads) == 1


async def test_draft_entries_documents_used_defaults_to_empty_list(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await db.execute(
        text(
            "INSERT INTO draft_entries "
            "(id, run_id, thread_id, round, author_id, entry_type, content) "
            "VALUES ('e1', 'r1', 't1', 1, 'a1', 'proposal', 'hello')"
        )
    )
    await db.commit()
    row = (
        await db.execute(text("SELECT documents_used FROM draft_entries WHERE id = 'e1'"))
    ).mappings().fetchone()
    assert row["documents_used"] == "[]"


async def test_run_swarm_confirmed_layer_starts_empty(db: AsyncConnection) -> None:
    await _drain(SwarmRunConfig(prompt="Analyze this energy contract"), db)

    # No anchors are seeded — the Confirmed layer is empty until a draft entry is
    # promoted via citations.
    confirmed = (await db.execute(text("SELECT COUNT(*) FROM confirmed_entries"))).scalar_one()
    assert confirmed == 0


async def test_run_swarm_emits_system_steps(db: AsyncConnection) -> None:
    steps = await _drain(SwarmRunConfig(prompt="Analyze this energy contract"), db)

    # An immediate liveness frame is emitted before the (slow) contract step.
    assert steps[0].type == "system"
    assert "Run started" in steps[0].msg
    assert any("Contract created" in s.msg for s in steps)
    assert any("Threads created" in s.msg for s in steps)


# ── M1: auction ───────────────────────────────────────────────────────────────


async def test_auction_selects_bidders_as_takers(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    await _insert_agent(db, "a3", "Gamma")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract"),
        db,
        agent_runner=_scripted_runner(),  # all bid
    )

    types = [s.type for s in steps]
    assert types.count("bid") == 3
    assert any("Auction open. 3 agent(s) invited." in s.msg for s in steps)
    assert any("Takers selected" in s.msg for s in steps)

    takers = await AuctionEngine(db).get_takers(run_id=_run_id(steps))
    assert set(takers) == {"a1", "a2", "a3"}

    run = (await db.execute(text("SELECT status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None
    assert run["status"] == "completed"


async def test_auction_abstainers_are_not_takers(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract"),
        db,
        agent_runner=_scripted_runner(abstainers=frozenset({"Beta"})),
    )

    assert [s.type for s in steps].count("bid") == 1
    assert [s.type for s in steps].count("abstain") == 1
    takers = await AuctionEngine(db).get_takers(run_id=_run_id(steps))
    assert takers == ["a1"]


async def test_auction_zero_bidders_aborts_run(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract"),
        db,
        agent_runner=_scripted_runner(abstainers=frozenset({"Alpha", "Beta"})),
    )

    assert any("aborted" in s.msg.lower() for s in steps)
    run = (await db.execute(text("SELECT status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None
    assert run["status"] == "aborted"


# ── M2: round 1 + vote sub-round ──────────────────────────────────────────────


async def test_round_one_posts_one_proposal_per_taker(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )

    # Count only the posts emitted before the vote sub-round (i.e. round 1).
    vote_idx = next(i for i, s in enumerate(steps) if s.msg.startswith("Vote sub-round"))
    round1_posts = [s for s in steps[:vote_idx] if s.type == "bb-post"]
    assert len(round1_posts) == 2

    proposals = (
        await db.execute(
            text("SELECT COUNT(*) FROM draft_entries WHERE round = 1 AND entry_type = 'proposal'")
        )
    ).scalar_one()
    assert proposals == 2


def _prompt_capturing_runner(
    captured: list[tuple[str, str]], *, wave2_posts: bool = True
) -> AgentRunner:
    """Wraps _scripted_runner behaviour but records (agent_name, user_prompt)
    for round-1 turns and lets wave-2 agents stay silent when wave2_posts=False."""
    inner = _scripted_runner()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "post_to_blackboard" in tool_names and "cite" not in tool_names:
            captured.append((agent["name"], user_prompt))
            if not wave2_posts and "second wave" in user_prompt:
                return "", []  # wave-2 agent agrees in full: posts nothing
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    return runner


async def test_round_one_second_wave_sees_first_wave_proposals(db: AsyncConnection) -> None:
    for i, name in enumerate(["Alpha", "Beta", "Gamma", "Delta"]):
        await _insert_agent(db, f"a{i + 1}", name)
    captured: list[tuple[str, str]] = []
    await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_prompt_capturing_runner(captured),
    )
    wave1 = [p for _, p in captured if "second wave" not in p]
    wave2 = [p for _, p in captured if "second wave" in p]
    assert len(wave1) == 2 and len(wave2) == 2  # ceil(4/2) split
    for p in wave1:
        assert "PROPOSALS ALREADY POSTED" not in p
    for p in wave2:
        assert "PROPOSALS ALREADY POSTED" in p
        assert "proposal" in p  # wave-1 content excerpts made it in
        assert "do NOT post" in p


async def test_silent_wave2_agent_still_votes_and_run_completes(db: AsyncConnection) -> None:
    for i, name in enumerate(["Alpha", "Beta"]):
        await _insert_agent(db, f"a{i + 1}", name)
    captured: list[tuple[str, str]] = []
    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_prompt_capturing_runner(captured, wave2_posts=False),
    )
    # ceil(2/2)=1 → Beta is wave 2 and posted nothing:
    proposals = (
        await db.execute(
            text("SELECT COUNT(*) FROM draft_entries WHERE round = 1 AND entry_type = 'proposal'")
        )
    ).scalar_one()
    assert proposals == 1
    # …but still voted in the vote sub-round:
    votes = (await db.execute(text("SELECT COUNT(*) FROM votes"))).scalar_one()
    assert votes >= 1
    assert any(s.type == "convergence" for s in steps)  # run completed
    assert any("second wave" in s.msg for s in steps if s.type == "system")


async def test_reply_without_reply_to_is_rejected(db: AsyncConnection) -> None:
    """A 'reply' post with no reply_to has nothing to thread under — the Draft
    board's nesting and the graph view's reply edges both key off reply_to, so
    a missing one would silently orphan the post. The tool should reject it
    (as a tool-result error string, not a raised exception) instead of persisting."""
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()

    result = await tool.execute(
        PostToBlackboardInput(content="a reply with no target", entry_type="reply", thread_id="t1"),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2},
    )

    assert "error" in result
    count = (await db.execute(text("SELECT COUNT(*) FROM draft_entries"))).scalar_one()
    assert count == 0


async def test_reply_with_reply_to_still_posts(db: AsyncConnection) -> None:
    """The new reply_to check must not reject legitimate replies."""
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()

    result = await tool.execute(
        PostToBlackboardInput(
            content="a reply", entry_type="reply", thread_id="t1", reply_to="some-entry-id"
        ),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2},
    )

    assert "error" not in result
    assert "entry_id" in result
    count = (await db.execute(text("SELECT COUNT(*) FROM draft_entries"))).scalar_one()
    assert count == 1


async def test_documents_used_captured_from_files_tool_calls(db: AsyncConnection) -> None:
    """When an agent's turn includes a files(action='read', ...) call before
    post_to_blackboard, the resulting entry's documents_used carries the file
    name — both on the emitted bb-post step and in the persisted row."""
    await _insert_agent(db, "a1", "Alpha")

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "submit_bid" in tool_names:
            engine = AuctionEngine(tool_context["db"])
            await engine.record_bid(
                run_id=tool_context["run_id"],
                agent_id=tool_context["agent_id"],
                contract_id=tool_context["contract_id"],
                justification="I can contribute",
                preliminary_score=tool_context["preliminary_score"],
            )
            return "", [ToolCall(name="submit_bid", input={"justification": "yes"}, output="{}")]
        # Discussion rounds (round 2+) offer post_to_blackboard alongside cite; this
        # test only cares about the round-1 opening proposal, so no-op there.
        if "cite" in tool_names:
            return "", []
        if "post_to_blackboard" in tool_names:
            entry_id = await Blackboard(tool_context["db"]).post(
                run_id=tool_context["run_id"],
                thread_id=tool_context["thread_id"],
                author_id=tool_context["agent_id"],
                content="Alpha proposal",
                entry_type="proposal",
                round=tool_context["round"],
            )
            return "", [
                ToolCall(
                    name="files",
                    input={"action": "list"},
                    output="Available files:\n- contract.txt",
                ),
                ToolCall(
                    name="files",
                    input={"action": "read", "file_name": "contract.txt"},
                    output="clause text...",
                ),
                ToolCall(
                    name="post_to_blackboard",
                    input={"entry_type": "proposal", "thread_id": tool_context["thread_id"]},
                    output=json.dumps({"entry_id": entry_id}),
                ),
            ]
        return "", []

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=runner,
    )

    post_steps = [s for s in steps if s.type == "bb-post"]
    assert len(post_steps) == 1
    assert post_steps[0].data["documents_used"] == ["contract.txt"]

    row = (
        await db.execute(
            text("SELECT documents_used FROM draft_entries WHERE entry_type = 'proposal'")
        )
    ).mappings().fetchone()
    assert json.loads(row["documents_used"]) == ["contract.txt"]


async def test_vote_subround_records_votes_and_confidence(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )

    # Each taker votes on the other's proposal → two votes (vote sub-round only).
    assert [s.type for s in steps].count("bb-vote") == 2
    votes = (await db.execute(text("SELECT COUNT(*) FROM votes"))).scalar_one()
    assert votes == 2

    # Cold-start confidence is computed and surfaced as a system step.
    assert any(s.msg.startswith("Cold-start confidence:") for s in steps)
    assert any(s.msg.startswith("Round 2 temperatures:") for s in steps)

    run = (await db.execute(text("SELECT status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None
    assert run["status"] == "completed"


# ── M3: discussion rounds + end-of-round ──────────────────────────────────────


async def test_discussion_runs_to_max_rounds(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=3),
        db,
        agent_runner=_scripted_runner(),
    )

    begins = [s.msg for s in steps if s.msg.startswith("Round ") and s.msg.endswith("begins.")]
    assert begins == ["Round 2 begins.", "Round 3 begins."]

    run = (
        (
            await db.execute(
                text("SELECT status, termination_reason, termination_round FROM swarm_runs")
            )
        )
        .mappings()
        .fetchone()
    )
    assert run is not None
    assert run["status"] == "completed"
    assert run["termination_reason"] == "max_rounds"
    assert run["termination_round"] == 3


async def test_citations_promote_entries_to_confirmed(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )

    # Each round-1 proposal is cited by the other taker → threshold M=1 → promoted.
    assert [s.type for s in steps].count("bb-promote") == 2
    findings = (
        await db.execute(
            text("SELECT COUNT(*) FROM confirmed_entries WHERE entry_type = 'finding'")
        )
    ).scalar_one()
    assert findings == 2


async def test_amendment_processor_seam_is_invoked_each_round(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    class _FakeProcessor:
        def __init__(self) -> None:
            self.rounds: list[int] = []

        async def process(
            self,
            *,
            run_id: str,
            current_round: int,
            takers: list[str],
            db: AsyncConnection,
        ) -> AsyncIterator[SimulationStep]:
            self.rounds.append(current_round)
            yield SimulationStep(type="amendment", msg=f"checked round {current_round}")

    processor = _FakeProcessor()
    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=3),
        db,
        agent_runner=_scripted_runner(),
        amendment_processor=processor,
    )

    assert processor.rounds == [2, 3]
    assert [s.type for s in steps].count("amendment") == 2


# ── Rounds RAG context injection ──────────────────────────────────────────────


async def test_discussion_prompts_carry_injected_relevant_posts(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    captured: list[str] = []
    inner = _scripted_runner()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "cite" in tool_names:  # discussion rounds only
            captured.append(user_prompt)
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=runner,
    )
    assert captured, "no discussion turns ran"
    for p in captured:
        assert "RELEVANT EXISTING POSTS" in p
        assert "cite(entry_ids=[...]) it instead of restating" in p
        assert "proposal" in p  # round-1 content surfaced through retrieval
        assert "] Alpha · Round 1 · proposal" in p or "] Beta · Round 1 · proposal" in p


# ── Adaptive turn skipping (resilient runs) ───────────────────────────────────


async def test_dropout_after_consecutive_failures_shrinks_promotion_denominator(
    db: AsyncConnection,
) -> None:
    for i, name in enumerate(["Alpha", "Beta", "Gamma", "Delta", "Echo", "Foxtrot"]):
        await _insert_agent(db, f"a{i + 1}", name)
    inner = _scripted_runner()

    async def flaky(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if agent["name"] == "Foxtrot" and "submit_bid" not in tool_names:
            raise RuntimeError("provider down")
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=3, max_takers=6),
        db,
        agent_runner=flaky,
    )
    assert any("dropped out" in s.msg for s in steps if s.type == "system")
    failed = (
        await db.execute(
            text("SELECT COUNT(*) FROM turn_log WHERE agent_id = 'a6' AND status = 'failed'")
        )
    ).scalar_one()
    assert failed >= 2

    run = (await db.execute(text("SELECT status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None
    assert run["status"] == "completed"


async def test_retry_succeeds_without_dropout(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    inner = _scripted_runner()
    calls = {"n": 0}

    async def flaky_once(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if agent["name"] == "Beta" and "cite" in tool_names and calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("transient error")
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=flaky_once,
    )
    assert not any("dropped out" in s.msg for s in steps if s.type == "system")
    statuses = (
        await db.execute(
            text(
                "SELECT status FROM turn_log WHERE agent_id = 'a2' AND phase = 'round_2' "
                "ORDER BY created_at"
            )
        )
    ).scalars().all()
    assert statuses[-1] == "done"


async def test_resume_continues_without_duplicating_completed_turns(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    class _CrashOnceProcessor:
        """Simulates an orchestrator-level crash right after round 2 finishes
        (end-of-round processing already committed) but before round 3 starts."""

        def __init__(self) -> None:
            self.crashed = False

        async def process(
            self, *, run_id: str, current_round: int, takers: list[str], db: AsyncConnection
        ) -> AsyncIterator[SimulationStep]:
            if current_round == 2 and not self.crashed:
                self.crashed = True
                raise RuntimeError("simulated crash")
            return
            yield  # pragma: no cover - makes this an async generator

    with pytest.raises(RuntimeError):
        await _drain(
            SwarmRunConfig(prompt="Analyze this contract", max_rounds=3),
            db,
            agent_runner=_scripted_runner(),
            amendment_processor=_CrashOnceProcessor(),
        )
    run_id = (await db.execute(text("SELECT id FROM swarm_runs"))).scalar_one()
    await db.execute(
        text("UPDATE swarm_runs SET status = 'interrupted' WHERE id = :i"), {"i": run_id}
    )
    await db.commit()
    round1_before = (
        await db.execute(text("SELECT COUNT(*) FROM draft_entries WHERE round = 1"))
    ).scalar_one()

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=3),
        db,
        agent_runner=_scripted_runner(),
        resume_run_id=run_id,
    )
    assert any(s.type == "convergence" for s in steps)
    round1_after = (
        await db.execute(text("SELECT COUNT(*) FROM draft_entries WHERE round = 1"))
    ).scalar_one()
    assert round1_after == round1_before  # round 1 was not re-run


# ── Multi-turn contract sessions ──────────────────────────────────────────────


async def test_follow_up_run_sees_carried_anchors(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    # Run 1 to completion with citations so a finding confirms:
    await _drain(
        SwarmRunConfig(prompt="Analyze the contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )
    parent_id = (
        await db.execute(text("SELECT id FROM swarm_runs ORDER BY created_at LIMIT 1"))
    ).scalar_one()

    captured: list[str] = []
    inner = _scripted_runner()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "get_confirmed" in tool_names:
            bb = Blackboard(tool_context["db"])
            entries = await bb.get_confirmed(run_id=tool_context["run_id"], thread_id=None)
            captured.extend(e.content for e in entries)
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    await _drain(
        SwarmRunConfig(prompt="Now check the pricing follow-up", max_rounds=2),
        db,
        agent_runner=runner,
        parent_run_id=parent_id,
    )

    assert any(c.startswith("[carried] ") for c in captured)
    session = (
        await db.execute(
            text("SELECT session_id, parent_run_id FROM swarm_runs WHERE parent_run_id IS NOT NULL")
        )
    ).fetchone()
    assert session[0] == parent_id  # first run minted session_id = its own id
    assert session[1] == parent_id


async def test_follow_up_run_with_no_parent_findings_runs_normally(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES ('empty-parent', 'completed', 'swarm')")
    )
    await db.commit()

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
        parent_run_id="empty-parent",
    )

    assert any(s.type == "convergence" for s in steps)
    assert not any("Carried" in s.msg for s in steps if s.type == "system")


async def test_unknown_parent_run_id_raises(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    with pytest.raises(ValueError):
        await _drain(
            SwarmRunConfig(prompt="P", max_rounds=2),
            db,
            agent_runner=_scripted_runner(),
            parent_run_id="does-not-exist",
        )


async def test_running_parent_run_id_raises(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES ('still-running', 'running', 'swarm')")
    )
    await db.commit()
    with pytest.raises(ValueError):
        await _drain(
            SwarmRunConfig(prompt="P", max_rounds=2),
            db,
            agent_runner=_scripted_runner(),
            parent_run_id="still-running",
        )


# ── M4: finalize + final output ───────────────────────────────────────────────


async def test_final_output_convergence_step(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )

    final = steps[-1]
    assert final.type == "convergence"
    assert final.data is not None
    assert final.data["termination_reason"] == "max_rounds"
    assert final.data["termination_round"] == 2

    # Both round-1 proposals were promoted; the answer for the thread is one of them.
    threads_data = next(s.data for s in steps if s.msg.startswith("Threads created"))
    assert threads_data is not None
    thread_id = threads_data["thread_ids"][0]
    assert thread_id in final.data["answers"]
    assert len(final.data["confirmed_layer"]) >= 1

    # The confirmed findings are synthesised into a brief final answer (the no-LLM
    # default joins them deterministically) and persisted on the run.
    final_answer = final.data["final_answer"]
    assert isinstance(final_answer, str) and final_answer.strip()

    run = (
        (await db.execute(text("SELECT status, final_answer FROM swarm_runs")))
        .mappings()
        .fetchone()
    )
    assert run is not None
    assert run["status"] == "completed"
    assert run["final_answer"] == final_answer


async def test_aborted_run_has_no_convergence_step(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract"),
        db,
        agent_runner=_scripted_runner(abstainers=frozenset({"Alpha"})),
    )

    assert all(s.type != "convergence" for s in steps)


def _run_id(steps: list[SimulationStep]) -> str:
    """Pull the run_id out of the first system step's data payload."""
    data = steps[0].data
    assert data is not None
    run_id = data["run_id"]
    assert isinstance(run_id, str)
    return run_id


# ── knowledge-file wiring into agent turns ─────────────────────────────────────


async def test_default_runner_wires_agent_files(db: AsyncConnection) -> None:
    """_default_agent_runner loads the agent's files, offers the `files` tool, and
    hints the system prompt — so takers can read attached documents in any phase."""
    agent_id = str(uuid.uuid4())
    file_id = str(uuid.uuid4())
    await _insert_agent(db, agent_id, "Counsel")
    await db.execute(
        text("INSERT INTO knowledge_files (id, name, content) VALUES (:id, :name, :content)"),
        {"id": file_id, "name": "contract.txt", "content": "Clause 7: price may change monthly."},
    )
    await db.execute(
        text("INSERT INTO agent_files (agent_id, file_id) VALUES (:aid, :fid)"),
        {"aid": agent_id, "fid": file_id},
    )
    await db.commit()

    agent = {
        "id": agent_id,
        "name": "Counsel",
        "system_prompt": "You are a lawyer.",
        "provider": "openai",
        "model": "gpt-4o",
    }
    captured: dict[str, Any] = {}

    async def _fake_call_agent(prompt: str, **kwargs: Any) -> tuple[str, list[ToolCall]]:
        captured.update(kwargs)
        return "ok", []

    with patch("server.market_hive.orchestrator.call_agent", new=_fake_call_agent):
        text_out, _ = await _default_agent_runner(
            agent,
            user_prompt="Analyse the contract.",
            system_suffix="ROUND 1",
            tool_names=["post_to_blackboard"],
            tool_context={"db": db, "agent_id": agent_id, "run_id": str(uuid.uuid4())},
        )

    assert text_out == "ok"
    assert "files" in captured["tool_names"]  # the files tool was offered
    assert captured["tool_context"]["files"] == {
        "contract.txt": "Clause 7: price may change monthly."
    }
    assert "contract.txt" in (captured["system_prompt"] or "")  # prompt hints the file


async def test_default_runner_no_files_omits_files_tool(db: AsyncConnection) -> None:
    """An agent with no attached files is not given the files tool."""
    agent_id = str(uuid.uuid4())
    await _insert_agent(db, agent_id, "Plain")
    await db.commit()

    agent = {
        "id": agent_id,
        "name": "Plain",
        "system_prompt": "You are helpful.",
        "provider": "openai",
        "model": "gpt-4o",
    }
    captured: dict[str, Any] = {}

    async def _fake_call_agent(prompt: str, **kwargs: Any) -> tuple[str, list[ToolCall]]:
        captured.update(kwargs)
        return "ok", []

    with patch("server.market_hive.orchestrator.call_agent", new=_fake_call_agent):
        await _default_agent_runner(
            agent,
            user_prompt="Hi",
            system_suffix="ROUND 1",
            tool_names=["post_to_blackboard"],
            tool_context={"db": db, "agent_id": agent_id, "run_id": str(uuid.uuid4())},
        )

    assert "files" not in captured["tool_names"]
    assert captured["tool_context"]["files"] == {}


# ── Trust registry: cross-run loop (PRD §6.7) ─────────────────────────────────


async def _trust_for(db: AsyncConnection, agent_id: str) -> tuple[float, int] | None:
    """(trust_score, runs_participated) for an agent's single domain, or None."""
    row = (
        await db.execute(
            text("SELECT trust_score, runs_participated FROM agent_trust WHERE agent_id = :a"),
            {"a": agent_id},
        )
    ).fetchone()
    return (float(row[0]), int(row[1])) if row is not None else None


async def test_trust_populated_after_first_swarm_run(db: AsyncConnection) -> None:
    """End-to-end: a real run_swarm() writes agent_trust at run end (was a no-op)."""
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    # Before the run there is no trust anywhere.
    assert (await db.execute(text("SELECT COUNT(*) FROM agent_trust"))).scalar_one() == 0

    await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=_scripted_runner(),
    )

    # Both takers authored confirmed findings (each cited once), so both gained
    # trust above the 0.5 cold-start, and each participated in exactly one run.
    for agent_id in ("a1", "a2"):
        trust = await _trust_for(db, agent_id)
        assert trust is not None, f"{agent_id} has no trust row after the run"
        score, runs = trust
        assert score > 0.5, f"{agent_id} trust did not rise above cold-start"
        assert runs == 1


async def test_trust_accumulates_across_runs(db: AsyncConnection) -> None:
    """The learning loop compounds: a second run lifts trust further (PRD §6.7)."""
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")

    config = SwarmRunConfig(prompt="Analyze this contract", max_rounds=2)

    await _drain(config, db, agent_runner=_scripted_runner())
    after_run_1 = await _trust_for(db, "a1")
    assert after_run_1 is not None
    score_1, runs_1 = after_run_1
    assert runs_1 == 1

    await _drain(config, db, agent_runner=_scripted_runner())
    after_run_2 = await _trust_for(db, "a1")
    assert after_run_2 is not None
    score_2, runs_2 = after_run_2

    # Trust strictly increases and participation is counted once per run — the
    # cross-run loop is closed, not frozen at the cold-start value.
    assert score_2 > score_1
    assert runs_2 == 2


async def test_observer_gets_no_trust_events_or_penalty(db: AsyncConnection) -> None:
    """An agent that bids and loses (observer) gets zero trust events — no
    penalty of any kind (2026-07-04 trust-registry-hardening removed the
    flat observer penalty: losing a bid is not evidence of anything)."""
    # Three agents, but cap takers at 2 so the lowest-scored bidder loses.
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    await _insert_agent(db, "a3", "Gamma")

    await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2, max_takers=2),
        db,
        agent_runner=_scripted_runner(),
    )

    observers = (
        await db.execute(text("SELECT agent_id FROM bids WHERE is_observer = true"))
    ).fetchall()
    for (agent_id,) in observers:
        n_events = (
            await db.execute(
                text("SELECT COUNT(*) FROM trust_events WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar_one()
        assert n_events == 0
        assert await _trust_for(db, agent_id) is None


# ── Tool-level unit tests: structured posts, citation cap, disputes,
#    ratification (contestable-consensus / structured-contributions /
#    ratified-synthesis) ────────────────────────────────────────────────────


async def test_post_with_structured_fields_persists_them(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()
    result = await tool.execute(
        PostToBlackboardInput(
            content="Full analysis of the pricing clause.",
            entry_type="proposal",
            thread_id="t1",
            claim="§4.2 is an unenforceable penalty",
            evidence=["contract.txt"],
        ),
        {
            "db": db,
            "run_id": "r1",
            "agent_id": "a1",
            "round": 1,
            "files": {"contract.txt": "…"},
        },
    )
    assert "entry_id" in result and "warning" not in result
    row = (
        await db.execute(
            text("SELECT claim, evidence FROM draft_entries WHERE entry_type='proposal'")
        )
    ).mappings().fetchone()
    assert row is not None
    assert row["claim"] == "§4.2 is an unenforceable penalty"
    assert json.loads(row["evidence"]) == ["contract.txt"]


async def test_refutes_without_target_rejected(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()
    result = await tool.execute(
        PostToBlackboardInput(
            content="x", entry_type="reply", thread_id="t1", reply_to="p1", stance="refutes"
        ),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2, "files": {}},
    )
    assert "error" in result
    n = (await db.execute(text("SELECT COUNT(*) FROM draft_entries"))).scalar_one()
    assert n == 0


async def test_unknown_evidence_dropped_with_warning(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()
    result = await tool.execute(
        PostToBlackboardInput(
            content="x",
            entry_type="proposal",
            thread_id="t1",
            evidence=["contract.txt", "ghost.pdf"],
        ),
        {
            "db": db,
            "run_id": "r1",
            "agent_id": "a1",
            "round": 1,
            "files": {"contract.txt": "…"},
        },
    )
    assert "entry_id" in result and "ghost.pdf" in result and "warning" in result
    row = (await db.execute(text("SELECT evidence FROM draft_entries"))).mappings().fetchone()
    assert row is not None
    assert json.loads(row["evidence"]) == ["contract.txt"]


async def test_refutes_own_entry_rejected(db: AsyncConnection) -> None:
    """Refuting your own entry is meaningless — rejected, only the original persists."""
    await _insert_agent(db, "a1", "Alpha")
    tool = PostToBlackboardTool()
    first = await tool.execute(
        PostToBlackboardInput(content="original claim", entry_type="proposal", thread_id="t1"),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 1, "files": {}},
    )
    entry_id = json.loads(first)["entry_id"]
    result = await tool.execute(
        PostToBlackboardInput(
            content="self-refutation",
            entry_type="reply",
            thread_id="t1",
            reply_to=entry_id,
            stance="refutes",
            stance_target=entry_id,
        ),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2, "files": {}},
    )
    assert "error" in result
    n = (await db.execute(text("SELECT COUNT(*) FROM draft_entries"))).scalar_one()
    assert n == 1


async def test_cite_requires_reasons(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    tool = CiteTool()
    result = await tool.execute(
        CiteInput(entry_ids=["e1"], reasons=[]),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2},
    )
    assert "error" in result
    n = (await db.execute(text("SELECT COUNT(*) FROM citations"))).scalar_one()
    assert n == 0


async def _seed_citable_entries(
    db: AsyncConnection, *, run_id: str, thread_id: str, author: str, count: int
) -> list[str]:
    bb = Blackboard(db)
    return [
        await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=author,
            content=f"entry {i}",
            entry_type="proposal",
            round=1,
        )
        for i in range(count)
    ]


async def test_cite_cap_skips_excess(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    ids = await _seed_citable_entries(db, run_id="r1", thread_id="t1", author="a2", count=5)
    tool = CiteTool()
    result = await tool.execute(
        CiteInput(entry_ids=ids, reasons=[f"builds on {i}" for i in range(5)]),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2},
    )
    assert '"cited": 3' in result and "cap" in result
    n = (await db.execute(text("SELECT COUNT(*) FROM citations"))).scalar_one()
    assert n == 3
    reasons = (await db.execute(text("SELECT reason FROM citations"))).scalars().all()
    assert all(r for r in reasons)


async def test_cite_cap_counts_prior_calls_this_round(db: AsyncConnection) -> None:
    """A second cite() call in the same round cannot bypass the per-round cap —
    the tool counts what already landed before deciding how much of a later
    list still fits."""
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    ids = await _seed_citable_entries(db, run_id="r1", thread_id="t1", author="a2", count=4)
    tool = CiteTool()
    ctx = {"db": db, "run_id": "r1", "agent_id": "a1", "round": 2}
    first = await tool.execute(CiteInput(entry_ids=ids[:2], reasons=["r0", "r1"]), ctx)
    assert '"cited": 2' in first and "cap" not in first
    second = await tool.execute(CiteInput(entry_ids=ids[2:], reasons=["r2", "r3"]), ctx)
    assert '"cited": 1' in second and "cap" in second
    n = (await db.execute(text("SELECT COUNT(*) FROM citations"))).scalar_one()
    assert n == 3


async def test_dispute_tool_rejects_missing_target(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    tool = DisputeTool()
    result = await tool.execute(
        DisputeInput(entry_id="nonexistent", reason="no evidence for this"),
        {"db": db, "run_id": "r1", "agent_id": "a1", "round": 3},
    )
    assert '"ok": false' in result


async def test_dispute_tool_records_valid_dispute(db: AsyncConnection) -> None:
    """post -> cite to M=1 -> promote -> dispute, all through real tool/Blackboard calls."""
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    run_id, thread_id = "r1", "t1"
    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id="a1",
        content="finding",
        entry_type="proposal",
        round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id="a2", entry_ids=[entry_id], round=2)
    promoted = await bb.check_promotions(
        run_id=run_id, current_round=2, participants_by_thread={thread_id: 2}
    )
    assert len(promoted) == 1

    tool = DisputeTool()
    result = await tool.execute(
        DisputeInput(entry_id=promoted[0].id, reason="contradicted by later evidence"),
        {"db": db, "run_id": run_id, "agent_id": "a2", "round": 3},
    )
    assert '"ok": true' in result


async def test_dispute_flip_emits_bb_contest_step(db: AsyncConnection) -> None:
    """Two distinct disputes on a promoted entry (M=2 with 4 takers) flip it to
    contested through the real orchestrator wiring — _ROUNDS_TOOLS, _board_events'
    dispute branch, and _end_of_round's contest_check pass."""
    for i, name in enumerate(["Alpha", "Beta", "Gamma", "Delta"]):
        await _insert_agent(db, f"a{i + 1}", name)
    inner = _scripted_runner()
    disputers_used: set[str] = set()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if (
            "dispute" in tool_names
            and tool_context["round"] == 3
            and len(disputers_used) < 2
        ):
            db_ = tool_context["db"]
            run_id = tool_context["run_id"]
            agent_id = tool_context["agent_id"]
            row = (
                (
                    await db_.execute(
                        text(
                            "SELECT ce.id AS id, de.author_id AS author_id "
                            "FROM confirmed_entries ce "
                            "JOIN draft_entries de ON de.id = ce.source_draft_id "
                            "WHERE ce.run_id = :r AND ce.status = 'confirmed'"
                        ),
                        {"r": run_id},
                    )
                )
                .mappings()
                .fetchone()
            )
            if (
                row is not None
                and row["author_id"] != agent_id
                and agent_id not in disputers_used
            ):
                bb = Blackboard(db_)
                result = await bb.dispute(
                    run_id=run_id,
                    disputing_agent_id=agent_id,
                    confirmed_entry_id=row["id"],
                    reason="stale data",
                    round=3,
                )
                if result["ok"]:
                    disputers_used.add(agent_id)
                    return "", [
                        ToolCall(name="dispute", input={"entry_id": row["id"]}, output="{}")
                    ]
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=4), db, agent_runner=runner
    )
    assert len(disputers_used) == 2
    assert any(s.type == "bb-contest" for s in steps)
    disputes = (await db.execute(text("SELECT COUNT(*) FROM disputes"))).scalar_one()
    assert disputes == 2
    # The scripted runner keeps re-citing the source draft every round, so the
    # contest raised in round 3 gathers fresh citers and re-affirms by round 4 —
    # both contest_check and reaffirm_check fired through the real wiring.
    run = (await db.execute(text("SELECT status FROM swarm_runs"))).mappings().fetchone()
    assert run is not None
    assert run["status"] == "completed"


async def test_ratification_tools_record_votes() -> None:
    votes: dict[str, str | None] = {}
    ok = await ApproveSynthesisTool().execute(
        ApproveSynthesisInput(), {"agent_id": "a1", "ratification_votes": votes}
    )
    rev = await ReviseSynthesisTool().execute(
        ReviseSynthesisInput(reason="misses the §7.1 pricing risk"),
        {"agent_id": "a2", "ratification_votes": votes},
    )
    assert '"ok": true' in ok and '"ok": true' in rev
    assert votes == {"a1": None, "a2": "misses the §7.1 pricing risk"}


async def test_unanimous_approval_ships_ratified(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    inner = _scripted_runner()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "approve_synthesis" in tool_names:
            tool_context["ratification_votes"][agent["id"]] = None
            return "", [ToolCall(name="approve_synthesis", input={}, output='{"ok": true}')]
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2), db, agent_runner=runner
    )
    conv = next(s for s in steps if s.type == "convergence")
    assert conv.data["ratification"]["approved"] is True
    assert conv.data["ratification"]["round"] == 1
    stored = (await db.execute(text("SELECT ratification FROM swarm_runs"))).scalar_one()
    assert json.loads(stored)["approved"] is True


async def test_double_rejection_ships_flagged_with_objections(db: AsyncConnection) -> None:
    await _insert_agent(db, "a1", "Alpha")
    await _insert_agent(db, "a2", "Beta")
    inner = _scripted_runner()

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if "revise_synthesis" in tool_names:
            reason = f"{agent['name']} objects"
            tool_context["ratification_votes"][agent["id"]] = reason
            return "", [ToolCall(name="revise_synthesis", input={"reason": reason}, output="{}")]
        return await inner(
            agent,
            user_prompt=user_prompt,
            system_suffix=system_suffix,
            tool_names=tool_names,
            tool_context=tool_context,
        )

    class _CountingSynthesizer:
        def __init__(self) -> None:
            self.calls: list[list[str] | None] = []

        async def synthesize(
            self, *, prompt: str, findings: list[Any], objections: list[str] | None = None
        ) -> str:
            self.calls.append(objections)
            return f"draft answer v{len(self.calls)}"

    synth = _CountingSynthesizer()
    steps = await _drain(
        SwarmRunConfig(prompt="Analyze this contract", max_rounds=2),
        db,
        agent_runner=runner,
        synthesizer=synth,
    )
    assert len(synth.calls) == 2
    assert synth.calls[1]  # objections from round 1 were passed to the revision call
    conv = next(s for s in steps if s.type == "convergence")
    assert conv.data["ratification"]["approved"] is False
    assert conv.data["ratification"]["round"] == 2
    assert conv.data["ratification"]["objections"]

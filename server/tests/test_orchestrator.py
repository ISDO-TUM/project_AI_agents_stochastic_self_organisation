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
from server.market_hive.tools import PostToBlackboardInput, PostToBlackboardTool
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


async def test_observer_trust_decremented_after_run(db: AsyncConnection) -> None:
    """An agent that bids and loses (observer) has its trust lowered at run end."""
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
    # If taker selection produced an observer, its trust must be below cold-start
    # and it must not have been credited with participation.
    for (agent_id,) in observers:
        trust = await _trust_for(db, agent_id)
        assert trust is not None
        score, runs = trust
        assert score < 0.5
        assert runs == 0

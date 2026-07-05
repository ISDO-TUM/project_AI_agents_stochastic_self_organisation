"""Tests for the baseline benchmark harness (server/benchmarks/).

The existing tests/test_benchmarks.py covers the unrelated needle-in-haystack
REST route and is untouched — this file is entirely new.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.benchmarks.modes import B01SingleAgent, B02Topology, B03MinimalSupervisor, B04Swarm
from server.benchmarks.tasks import REPO_ROOT, BenchmarkTask, load_suite
from server.db.tables import metadata
from server.market_hive.blackboard import Blackboard
from server.schemas import ToolCall


def test_task_001_loads_and_covers_known_defects() -> None:
    tasks = load_suite(REPO_ROOT / "benchmarks" / "tasks")
    t = next(t for t in tasks if t.id == "001-energy-contract")
    assert len(t.agents) == 5 and len(t.sources) == 3
    cited = {f.must_cite for f in t.rubric}
    assert {"§4.2", "§7.1", "§9.1", "§11", "§12"} <= cited
    assert all(f.severity in ("high", "medium", "low") for f in t.rubric)


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Any:
    from unittest.mock import AsyncMock, patch

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


def _mini_task() -> BenchmarkTask:
    """A tiny 2-agent task for adapter tests — schema/rubric fidelity is
    task_001's job; these tests only need a well-formed roster + sources."""
    return BenchmarkTask.model_validate(
        {
            "id": "mini-task",
            "prompt": "Analyze this contract.",
            "agents": [
                {
                    "id": "agent-lawyer",
                    "name": "Contract Counsel",
                    "description": "Lawyer",
                    "systemPrompt": "You are a lawyer.",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "tools": ["files"],
                    "connections": [],
                    "position": {"x": 0, "y": 0},
                },
                {
                    "id": "agent-finance",
                    "name": "Financial Risk Analyst",
                    "description": "Finance",
                    "systemPrompt": "You are a financial risk analyst.",
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "tools": ["files"],
                    "connections": [],
                    "position": {"x": 0, "y": 0},
                },
            ],
            "sources": [
                {
                    "id": "source-1",
                    "name": "contract.txt",
                    "type": "text",
                    "content": "§1 Some clause.",
                    "position": {"x": 0, "y": 0},
                },
            ],
            "rubric": [
                {
                    "id": "f1",
                    "description": "A finding.",
                    "must_cite": "§1",
                    "severity": "high",
                },
            ],
            "tier": "cross-domain",
        }
    )


def _canned_runner(response: str = "canned answer") -> Any:
    """A trivial AgentRunner returning the same text for every call."""

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        return response, []

    return runner


def _planning_runner(fail_agent: str | None = None) -> Any:
    """B-03's runner: the "planner"/"aggregator" pseudo-agents get their
    scripted responses; real agents get a canned finding."""

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        if agent["name"] == "planner":
            plan = [
                {"subtask": "Review the contract", "agent_name": "Contract Counsel"},
                {"subtask": "Assess financial risk", "agent_name": "Financial Risk Analyst"},
            ]
            return json.dumps(plan), []
        if agent["name"] == "aggregator":
            return "aggregated answer", []
        return f"{agent['name']} finding", []

    return runner


async def test_b01_single_agent_returns_well_formed_result(db: AsyncConnection) -> None:
    task = _mini_task()
    result = await B01SingleAgent().run(task, db, agent_runner=_canned_runner("b01 answer"))
    assert result.mode == "b01"
    assert result.task_id == "mini-task"
    assert result.answer == "b01 answer"
    assert isinstance(result.tokens, int)
    assert result.wall_seconds >= 0


async def test_b02_topology_returns_well_formed_result(db: AsyncConnection) -> None:
    task = _mini_task()
    result = await B02Topology().run(task, db, agent_runner=_canned_runner("b02 answer"))
    assert result.mode == "b02"
    assert "b02 answer" in result.answer
    assert "Contract Counsel" in result.answer
    assert "Financial Risk Analyst" in result.answer


async def test_b02_topology_ablation_marks_failed_agent(db: AsyncConnection) -> None:
    task = _mini_task()
    result = await B02Topology().run(
        task, db, agent_runner=_canned_runner("b02 answer"), fail_agent="Financial Risk Analyst"
    )
    assert "[failed to respond]" in result.answer
    assert "b02 answer" in result.answer  # the other agent still answered


async def test_b03_minimal_supervisor_returns_well_formed_result(db: AsyncConnection) -> None:
    task = _mini_task()
    result = await B03MinimalSupervisor().run(task, db, agent_runner=_planning_runner())
    assert result.mode == "b03"
    assert result.answer == "aggregated answer"
    assert result.metadata["lost_subtasks"] == []
    assert len(result.metadata["plan"]) == 2


async def test_b03_minimal_supervisor_records_lost_subtask_on_ablation(
    db: AsyncConnection,
) -> None:
    task = _mini_task()
    result = await B03MinimalSupervisor().run(
        task, db, agent_runner=_planning_runner(), fail_agent="Financial Risk Analyst"
    )
    assert result.metadata["lost_subtasks"] == ["Assess financial risk"]
    assert result.answer == "aggregated answer"  # aggregation still proceeds


def _swarm_scripted_runner() -> Any:
    """Minimal swarm-capable runner: bids, posts a round-1 proposal, votes,
    and posts+cites in discussion rounds — enough for run_swarm to converge."""

    async def runner(
        agent: dict[str, Any],
        *,
        user_prompt: str,
        system_suffix: str,
        tool_names: list[str],
        tool_context: dict[str, Any],
    ) -> tuple[str, list[ToolCall]]:
        from server.market_hive.auction import AuctionEngine

        db_ = tool_context["db"]
        run_id = tool_context.get("run_id")
        agent_id = tool_context.get("agent_id")

        if "submit_bid" in tool_names:
            engine = AuctionEngine(db_)
            await engine.record_bid(
                run_id=run_id,
                agent_id=agent_id,
                contract_id=tool_context["contract_id"],
                justification="I can contribute",
                preliminary_score=tool_context.get("preliminary_score", 0.0),
            )
            return "", [ToolCall(name="submit_bid", input={"justification": "yes"}, output="{}")]

        if "cite" in tool_names:
            thread_id = tool_context["thread_id"]
            round_ = tool_context["round"]
            bb = Blackboard(db_)
            entry_id = await bb.post(
                run_id=run_id,
                thread_id=thread_id,
                author_id=agent_id,
                content=f"{agent['name']} reply r{round_}",
                entry_type="reply",
                round=round_,
            )
            return "", [
                ToolCall(
                    name="post_to_blackboard",
                    input={"entry_type": "reply", "thread_id": thread_id},
                    output=json.dumps({"entry_id": entry_id}),
                )
            ]

        if "post_to_blackboard" in tool_names:
            thread_id = tool_context["thread_id"]
            entry_id = await Blackboard(db_).post(
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
            return "", []

        return "", []

    return runner


async def test_b04_swarm_returns_well_formed_result(db: AsyncConnection) -> None:
    task = _mini_task()
    result = await B04Swarm().run(task, db, agent_runner=_swarm_scripted_runner())
    assert result.mode == "b04"
    assert result.metadata["run_id"] is not None


async def test_b04_swarm_ablation_routes_around_failed_agent(db: AsyncConnection) -> None:
    task = _mini_task()
    await B04Swarm().run(
        task, db, agent_runner=_swarm_scripted_runner(), fail_agent="Financial Risk Analyst"
    )

    run_id = (await db.execute(text("SELECT id FROM swarm_runs"))).scalar_one()
    failed_agent_row = (
        await db.execute(text("SELECT id FROM agents WHERE name = 'Financial Risk Analyst'"))
    ).scalar_one()
    takers = (
        await db.execute(
            text("SELECT agent_id FROM bids WHERE run_id = :r AND is_taker = true"),
            {"r": run_id},
        )
    ).fetchall()
    taker_ids = {row[0] for row in takers}
    dropped = (
        await db.execute(
            text("SELECT DISTINCT agent_id FROM turn_log WHERE run_id = :r AND status = 'failed'"),
            {"r": run_id},
        )
    ).fetchall()
    dropped_ids = {row[0] for row in dropped}
    assert failed_agent_row not in taker_ids or failed_agent_row in dropped_ids


# ── Blind judge ────────────────────────────────────────────────────────────────


def _rubric_task() -> BenchmarkTask:
    """Three findings, one per severity tier, for hand-computable weighting."""
    return BenchmarkTask.model_validate(
        {
            "id": "rubric-task",
            "prompt": "Analyze this contract.",
            "agents": [],
            "sources": [
                {
                    "id": "s1",
                    "name": "contract.txt",
                    "type": "text",
                    "content": "§1 High. §2 Med. §3 Low.",
                    "position": {"x": 0, "y": 0},
                }
            ],
            "rubric": [
                {
                    "id": "f-high",
                    "description": "High severity finding.",
                    "must_cite": "§1",
                    "severity": "high",
                },
                {
                    "id": "f-med",
                    "description": "Medium severity finding.",
                    "must_cite": "§2",
                    "severity": "medium",
                },
                {
                    "id": "f-low",
                    "description": "Low severity finding.",
                    "must_cite": "§3",
                    "severity": "low",
                },
            ],
            "tier": "single-domain",
        }
    )


def _fake_judge(responses: list[str]) -> Any:
    """A Judge callable returning canned responses in sequence; records every
    prompt it was called with on ``captured``."""
    captured: list[str] = []
    calls = {"n": 0}

    async def judge(
        prompt: str, provider: str, model: str, system_prompt: str | None = None
    ) -> tuple[str, list[ToolCall]]:
        captured.append(prompt)
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        return responses[i], []

    judge.captured = captured  # type: ignore[attr-defined]
    return judge


async def test_judge_answer_computes_severity_weighted_coverage() -> None:
    from server.benchmarks.judge import judge_answer

    task = _rubric_task()
    canned = json.dumps(
        {
            "rubric": [
                {
                    "finding_id": "f-high",
                    "coverage": "covered",
                    "grounded": True,
                    "rationale": "r1",
                },
                {"finding_id": "f-med", "coverage": "partial", "grounded": True, "rationale": "r2"},
                {"finding_id": "f-low", "coverage": "missed", "grounded": False, "rationale": "r3"},
            ],
            "contradictions": 1,
        }
    )
    judge = _fake_judge([canned])

    score = await judge_answer("some answer", task, judge=judge, model="fake-model")

    # (3*1.0 + 2*0.5 + 1*0.0) / (3+2+1) = 4/6
    assert score.coverage_score == pytest.approx(4 / 6)
    assert score.contradictions == 1
    assert score.judge_model == "fake-model"
    assert score.metadata == {}


async def test_judge_answer_reasks_once_then_falls_back_on_malformed_output() -> None:
    from server.benchmarks.judge import judge_answer

    task = _rubric_task()
    judge = _fake_judge(["not json at all", "still not json"])

    score = await judge_answer("some answer", task, judge=judge, model="fake-model")

    assert score.metadata.get("judge_parse_failed") is True
    assert score.coverage_score == 0.0
    assert all(f.coverage == "missed" for f in score.rubric)
    assert len(judge.captured) == 2  # one re-ask, never more


async def test_judge_answer_recovers_after_one_malformed_response() -> None:
    from server.benchmarks.judge import judge_answer

    task = _rubric_task()
    good = json.dumps(
        {
            "rubric": [
                {"finding_id": "f-high", "coverage": "covered", "grounded": True, "rationale": "r"},
                {"finding_id": "f-med", "coverage": "covered", "grounded": True, "rationale": "r"},
                {"finding_id": "f-low", "coverage": "covered", "grounded": True, "rationale": "r"},
            ],
            "contradictions": 0,
        }
    )
    judge = _fake_judge(["garbage", good])

    score = await judge_answer("some answer", task, judge=judge, model="fake-model")

    assert score.coverage_score == pytest.approx(1.0)
    assert "judge_parse_failed" not in score.metadata


async def test_judge_answer_prompt_is_blind_to_mode() -> None:
    from server.benchmarks.judge import judge_answer

    task = _rubric_task()
    canned = json.dumps({"rubric": [], "contradictions": 0})
    judge = _fake_judge([canned])

    await judge_answer("some answer", task, judge=judge, model="fake-model")

    prompt = judge.captured[0]
    mode_names = ("b01", "b02", "b03", "b04", "single-agent", "topology", "supervisor", "swarm")
    for mode_name in mode_names:
        assert mode_name not in prompt.lower()


# ── Runner CLI + report ─────────────────────────────────────────────────────────


async def test_offline_smoke_run_writes_raw_results_report_and_manifest(tmp_path: Any) -> None:
    from server.benchmarks.run import run_suite

    suite_dir = tmp_path / "tasks"
    suite_dir.mkdir()
    (suite_dir / "001-mini.json").write_text(json.dumps(_mini_task().model_dump()))

    out_dir = tmp_path / "results"
    result_dir = await run_suite(
        suite_path=suite_dir,
        modes=["b01", "b04"],
        trials=2,
        ablate_agent=None,
        judge_model="fake-model",
        offline_smoke=True,
        out_dir=out_dir,
    )

    assert result_dir == out_dir
    raw_files = sorted((out_dir / "raw").glob("*.json"))
    assert len(raw_files) == 4  # 2 modes * 1 task * 2 trials
    for f in raw_files:
        row = json.loads(f.read_text())
        assert "result" in row and "score" in row

    report = (out_dir / "report.md").read_text()
    assert "## Mode Comparison" in report
    assert "| b01 " in report
    assert "| b04 " in report

    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["git_sha"]
    assert manifest["judge_model"] == "fake-model"
    assert manifest["trials"] == 2


def test_build_report_pure_formatting() -> None:
    from server.benchmarks.report import build_report

    rows = [
        {
            "result": {
                "mode": "b01",
                "task_id": "t1",
                "trial": 0,
                "tokens": 100,
                "wall_seconds": 1.5,
                "metadata": {},
            },
            "score": {
                "rubric": [
                    {"finding_id": "f1", "coverage": "covered", "grounded": True, "rationale": "r"}
                ],
                "contradictions": 0,
                "coverage_score": 1.0,
                "judge_model": "fake",
                "metadata": {},
            },
        },
        {
            "result": {
                "mode": "b04",
                "task_id": "t1",
                "trial": 0,
                "tokens": 200,
                "wall_seconds": 3.0,
                "metadata": {},
            },
            "score": {
                "rubric": [
                    {"finding_id": "f1", "coverage": "missed", "grounded": False, "rationale": "r"}
                ],
                "contradictions": 1,
                "coverage_score": 0.0,
                "judge_model": "fake",
                "metadata": {},
            },
        },
    ]
    report = build_report(rows)
    assert "## Mode Comparison" in report
    assert "## Per-Task Breakdown" in report
    assert "b01" in report and "b04" in report
    assert "### t1" in report

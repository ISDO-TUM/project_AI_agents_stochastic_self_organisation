"""Benchmark runner CLI.

    uv run python -m server.benchmarks.run --suite benchmarks/tasks \\
        --modes b01,b02,b03,b04 --trials 3 [--ablate-agent NAME] \\
        [--judge-model MODEL] [--offline-smoke]

Real suite runs hit real LLM providers (cost, and require provider keys) and
use the configured ``DATABASE_URL``. ``--offline-smoke`` instead wires in a
scripted agent runner and a fake judge against a fresh in-memory SQLite
database per trial — a fast, free, fully offline path used by the test suite
and for a quick sanity check before spending on a real run.

Writes ``benchmarks/results/<ISO-timestamp>/raw/*.json`` (one row per
mode x task x trial), ``report.md`` (the mode-comparison table), and
``manifest.json`` (judge model, git SHA, config) — none of it committed
(see .gitignore).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.benchmarks.judge import Judge, judge_answer
from server.benchmarks.modes import (
    B01SingleAgent,
    B02Topology,
    B03MinimalSupervisor,
    B04Swarm,
    ModeAdapter,
)
from server.benchmarks.report import build_report
from server.benchmarks.tasks import REPO_ROOT, BenchmarkTask, load_suite
from server.db.tables import metadata
from server.llm import call_agent
from server.market_hive.auction import AuctionEngine
from server.market_hive.blackboard import Blackboard
from server.schemas import ToolCall

_ADAPTERS: dict[str, ModeAdapter] = {
    "b01": B01SingleAgent(),
    "b02": B02Topology(),
    "b03": B03MinimalSupervisor(),
    "b04": B04Swarm(),
}


def _git_sha() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    try:
        # git path is resolved above (not attacker-controlled), args are literals.
        return subprocess.check_output(  # noqa: S603
            [git, "rev-parse", "HEAD"], text=True, cwd=REPO_ROOT
        ).strip()
    except Exception:
        return "unknown"


async def _smoke_agent_runner(
    agent: dict[str, Any],
    *,
    user_prompt: str,
    system_suffix: str,
    tool_names: list[str],
    tool_context: dict[str, Any],
) -> tuple[str, list[ToolCall]]:
    """A minimal scripted runner good enough for every mode's board mechanics
    (bid/vote/discussion) — used only by ``--offline-smoke``."""
    db_ = tool_context.get("db")
    run_id = tool_context.get("run_id")
    agent_id = tool_context.get("agent_id")

    if "submit_bid" in tool_names:
        engine = AuctionEngine(db_)
        await engine.record_bid(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=tool_context["contract_id"],
            justification="smoke bid",
            preliminary_score=tool_context.get("preliminary_score", 0.0),
        )
        return "", [ToolCall(name="submit_bid", input={"justification": "smoke"}, output="{}")]
    if "cite" in tool_names:
        thread_id, round_ = tool_context["thread_id"], tool_context["round"]
        entry_id = await Blackboard(db_).post(
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
    if agent.get("name") == "planner":
        return "[]", []
    return f"[smoke] response from {agent.get('name', 'agent')}", []


async def _smoke_judge(
    prompt: str, provider: str, model: str, system_prompt: str | None = None
) -> tuple[str, list[ToolCall]]:
    return json.dumps({"rubric": [], "contradictions": 0}), []


async def _make_engine(*, offline: bool) -> AsyncEngine:
    if offline:
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        return engine

    # Real runs share the configured DATABASE_URL and are scoped by run ids —
    # one engine reused across trials, not recreated per trial.
    from server.db import get_engine, init_db

    await init_db()
    real_engine: AsyncEngine = get_engine()
    return real_engine


async def _run_one(
    mode: str,
    task: BenchmarkTask,
    trial: int,
    *,
    offline: bool,
    fail_agent: str | None,
    judge: Judge,
    judge_model: str,
    agent_runner: Any,
) -> dict[str, Any]:
    engine = await _make_engine(offline=offline)
    try:
        async with engine.connect() as db:
            result = await _ADAPTERS[mode].run(
                task, db, agent_runner=agent_runner, fail_agent=fail_agent
            )
    finally:
        if offline:
            await engine.dispose()
    result.trial = trial
    score = await judge_answer(result.answer, task, judge=judge, model=judge_model)
    return {"result": result.model_dump(), "score": score.model_dump()}


async def run_suite(
    *,
    suite_path: Path,
    modes: list[str],
    trials: int,
    ablate_agent: str | None,
    judge_model: str,
    offline_smoke: bool,
    out_dir: Path,
) -> Path:
    """Run every task x mode x trial, write raw results + report + manifest.
    Returns ``out_dir``."""
    tasks = load_suite(suite_path)
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    agent_runner = _smoke_agent_runner if offline_smoke else None
    judge: Judge = _smoke_judge if offline_smoke else call_agent

    rows: list[dict[str, Any]] = []
    for task in tasks:
        for mode in modes:
            for trial in range(trials):
                row = await _run_one(
                    mode,
                    task,
                    trial,
                    offline=offline_smoke,
                    fail_agent=ablate_agent,
                    judge=judge,
                    judge_model=judge_model,
                    agent_runner=agent_runner,
                )
                rows.append(row)
                raw_path = raw_dir / f"{mode}_{task.id}_{trial}.json"
                raw_path.write_text(json.dumps(row, indent=2))

    (out_dir / "report.md").write_text(build_report(rows))
    manifest = {
        "judge_model": judge_model,
        "git_sha": _git_sha(),
        "modes": modes,
        "trials": trials,
        "ablate_agent": ablate_agent,
        "offline_smoke": offline_smoke,
        "task_ids": [t.id for t in tasks],
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out_dir


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Baseline benchmark harness runner")
    parser.add_argument("--suite", required=True, help="Directory of task *.json files")
    parser.add_argument("--modes", default="b01,b02,b03,b04", help="Comma-separated mode list")
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--ablate-agent", default=None, help="Agent name to force-fail every turn")
    parser.add_argument("--judge-model", default="gpt-4o")
    parser.add_argument("--offline-smoke", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = REPO_ROOT / "benchmarks" / "results" / timestamp
    result_dir = asyncio.run(
        run_suite(
            suite_path=Path(args.suite),
            modes=args.modes.split(","),
            trials=args.trials,
            ablate_agent=args.ablate_agent,
            judge_model=args.judge_model,
            offline_smoke=args.offline_smoke,
            out_dir=out_dir,
        )
    )
    print(f"Wrote results to {result_dir}")


if __name__ == "__main__":
    main()

"""Topology benchmark suite routes.

The suite runner groups ordinary topology trials under a benchmark id. Each
trial still writes the normal rounds/messages trace, so existing history and
statistics continue to work while this route adds benchmark-specific scoring.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, get_engine, resolve_experiment, update_trial_status
from server.db.tables import (
    agents,
    benchmark_suite_runs,
    benchmark_suites,
    messages,
    rounds,
)
from server.llm.credentials import RequestCredentials, current_credentials, use_credentials
from server.schemas import (
    BenchmarkCanvasResponse,
    BenchmarkDatasetSummary,
    BenchmarkMechanismAggregate,
    BenchmarkSuiteCreateRequest,
    BenchmarkSuiteResultsResponse,
    BenchmarkSuiteRunResult,
    BenchmarkSuiteStartResponse,
    BenchmarkSuiteSummary,
)
from server.topology import ConsensusMode, run_topology
from server.topology.routes.statistics import (
    _cost,
    _fetch_langfuse_observations_multi,
    _usage,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/topology", tags=["Topology Benchmarks"])
DBDep = Annotated[AsyncConnection, Depends(get_db)]

_PLURALITY_RE = re.compile(r"\*\*Plurality:\*\*\s*'([^']+)'", re.IGNORECASE)
_SELECTED_CONSENSUS_RE = re.compile(
    r"Selected consensus answer(?:\s*\([^)]*\))?:\s*(.+)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class PreparedDataset:
    dataset_id: str
    name: str
    prompt: str
    answer: str
    agent_context: dict[str, str]
    variant_id: str
    canvas: BenchmarkCanvasResponse


@dataclass(frozen=True)
class BuiltinDataset:
    id: str
    name: str
    description: str
    metrics: tuple[str, ...]
    fixture: str

    def summary(self) -> BenchmarkDatasetSummary:
        canvas = _load_benchmark_canvas(self.id)
        return BenchmarkDatasetSummary(
            id=self.id,
            name=self.name,
            description=self.description,
            default_prompt=canvas.prompt,
            evaluator_type="exact_match",
            metrics=list(self.metrics),
            min_agents=len(canvas.agents),
        )


DATASETS: dict[str, BuiltinDataset] = {
    "needlehaystack-majority": BuiltinDataset(
        id="needlehaystack-majority",
        name="Needle-in-a-haystack majority",
        description=(
            "A strict majority of agents receive the correct person; the rest "
            "receive a plausible wrong person plus distractors."
        ),
        metrics=("accuracy", "rounds_to_convergence", "message_count"),
        fixture="needlehaystack-majority.json",
    ),
    "approved-supplier-conflict": BuiltinDataset(
        id="approved-supplier-conflict",
        name="Approved supplier conflict",
        description=(
            "Two agents receive current supplier evidence and one receives a "
            "legacy conflicting note. The expected answer is Acme Computers."
        ),
        metrics=("accuracy", "rounds_to_convergence", "message_count"),
        fixture="approved-supplier-conflict.json",
    ),
    "president-majority": BuiltinDataset(
        id="president-majority",
        name="President majority",
        description=(
            "A small majority task based on the existing president demo, useful "
            "for showing how voting handles conflicting private context."
        ),
        metrics=("accuracy", "rounds_to_convergence", "message_count"),
        fixture="president-majority.json",
    ),
}

_BENCHMARK_DATASET_DIR = Path(__file__).resolve().parents[1] / "benchmark_datasets"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _normalise_answer(answer: str | None) -> str:
    if not answer:
        return ""
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in answer)
    return " ".join(cleaned.split())


def _answer_matches(generated: str | None, expected: str) -> bool:
    gen = _normalise_answer(generated)
    exp = _normalise_answer(expected)
    return bool(gen and exp and (gen == exp or gen in exp or exp in gen))


def _load_benchmark_canvas(dataset_id: str) -> BenchmarkCanvasResponse:
    dataset = DATASETS.get(dataset_id)
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Benchmark dataset not found.")
    path = _BENCHMARK_DATASET_DIR / dataset.fixture
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Benchmark fixture '{dataset.fixture}' is missing.",
        ) from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Benchmark fixture '{dataset.fixture}' contains invalid JSON.",
        ) from exc

    raw_dataset_id = raw.get("benchmarkDatasetId", dataset_id)
    if raw_dataset_id != dataset_id:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Benchmark fixture '{dataset.fixture}' has dataset id '{raw_dataset_id}'.",
        )
    try:
        return BenchmarkCanvasResponse(
            dataset_id=dataset_id,
            prompt=str(raw["benchmarkPrompt"]),
            answer=str(raw["benchmarkAnswer"]),
            agents=raw["agents"],
            sources=raw["sources"],
            edges=raw["edges"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Benchmark fixture '{dataset.fixture}' does not match the canvas schema.",
        ) from exc


def _agent_context_from_canvas(canvas: BenchmarkCanvasResponse) -> dict[str, str]:
    source_content = {source.id: source.content for source in canvas.sources}
    agent_ids = {agent.id for agent in canvas.agents}
    chunks_by_agent: dict[str, list[str]] = {agent.id: [] for agent in canvas.agents}
    for edge in canvas.edges:
        if edge.from_id in agent_ids and edge.to in source_content:
            chunks_by_agent[edge.from_id].append(source_content[edge.to])
    return {agent_id: "\n\n".join(chunks) for agent_id, chunks in chunks_by_agent.items() if chunks}


def _prepare_dataset(dataset_id: str, agent_ids: list[str], prompt: str | None) -> PreparedDataset:
    if dataset_id not in DATASETS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Benchmark dataset not found.")
    canvas = _load_benchmark_canvas(dataset_id)
    if len(agent_ids) < len(canvas.agents):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Dataset '{DATASETS[dataset_id].name}' needs at least {len(canvas.agents)} agents.",
        )
    contexts = _agent_context_from_canvas(canvas)
    return PreparedDataset(
        dataset_id=dataset_id,
        name=DATASETS[dataset_id].name,
        prompt=prompt.strip() if prompt and prompt.strip() else canvas.prompt,
        answer=canvas.answer,
        agent_context=contexts,
        variant_id=dataset_id,
        canvas=canvas,
    )


async def _agent_ids(db: AsyncConnection) -> list[str]:
    rows = await db.execute(select(agents.c.id).order_by(agents.c.created_at, agents.c.id))
    return [str(row.id) for row in rows.all()]


async def _extract_trial_answer(db: AsyncConnection, trial_id: str) -> str | None:
    rows = (
        await db.execute(
            select(messages.c.message_type, messages.c.message)
            .select_from(messages.join(rounds, rounds.c.id == messages.c.round_id))
            .where(rounds.c.trial_id == trial_id)
            .order_by(messages.c.id.desc())
        )
    ).all()
    for message_type, message in rows:
        if not message:
            continue
        message_text = cast(str, message)
        if message_type == "consensus":
            match = _SELECTED_CONSENSUS_RE.search(message_text)
            return (match.group(1) if match else message_text).strip()
        if message_type == "vote_tally":
            match = _PLURALITY_RE.search(message_text)
            if match:
                return match.group(1).strip()
        if message_type == "bidding_final_output":
            return message_text.strip()
    for message_type, message in rows:
        if message_type == "agent_output" and message:
            return cast(str, message).strip()
    return None


async def _trial_trace_counts(db: AsyncConnection, trial_id: str) -> tuple[int, int]:
    round_count = await db.scalar(
        select(func.count()).select_from(rounds).where(rounds.c.trial_id == trial_id)
    )
    message_count = await db.scalar(
        select(func.count())
        .select_from(messages.join(rounds, rounds.c.id == messages.c.round_id))
        .where(rounds.c.trial_id == trial_id)
    )
    return int(round_count or 0), int(message_count or 0)


async def _score_trial(
    db: AsyncConnection,
    trial_id: str,
    dataset: PreparedDataset,
) -> dict[str, Any]:
    generated = await _extract_trial_answer(db, trial_id)
    round_count, message_count = await _trial_trace_counts(db, trial_id)
    return {
        "answer_correct": _answer_matches(generated, dataset.answer),
        "correct_answer": dataset.answer,
        "generated_answer": generated,
        "round_count": round_count,
        "message_count": message_count,
    }


async def _llm_usage_for_trials(trial_ids: list[str]) -> dict[str, int | float]:
    if not trial_ids:
        return {
            "generation_count": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }
    observations, _message = await _fetch_langfuse_observations_multi(trial_ids)
    input_tokens = 0
    output_tokens = 0
    total_cost = 0.0
    for obs in observations:
        obs_input, obs_output = _usage(obs)
        input_tokens += obs_input
        output_tokens += obs_output
        total_cost += _cost(obs)
    return {
        "generation_count": len(observations),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "total_cost": total_cost,
    }


async def _refresh_suite_status(db: AsyncConnection, suite_id: str) -> None:
    rows = (
        await db.execute(
            select(benchmark_suite_runs.c.status).where(benchmark_suite_runs.c.suite_id == suite_id)
        )
    ).all()
    completed = sum(1 for (run_status,) in rows if run_status in {"completed", "failed"})
    failed = any(run_status == "failed" for (run_status,) in rows)
    all_done = completed == len(rows)
    await db.execute(
        benchmark_suites.update()
        .where(benchmark_suites.c.id == suite_id)
        .values(
            completed_trials=completed,
            status=("failed" if failed else "completed") if all_done else "running",
            completed_at=_now_iso() if all_done else None,
        )
    )
    await db.commit()


async def _run_suite_background(
    suite_id: str,
    dataset: PreparedDataset,
    trial_plan: list[tuple[str, str, str, str, str, int]],
    rounds_count: int,
    fanout: int,
    credentials: RequestCredentials,
) -> None:
    """Run planned benchmark trials sequentially."""
    from server.llm.credentials import _current as _creds_var

    token = _creds_var.set(credentials)
    try:
        for run_id, _experiment_id, trial_id, mode, topology, _run_index in trial_plan:
            async with get_engine().connect() as db:
                status_value = "completed"
                score: dict[str, Any] = {}
                try:
                    await run_topology(
                        dataset.prompt,
                        db,
                        rounds=rounds_count,
                        mode=cast(ConsensusMode, mode),
                        agent_context=dataset.agent_context,
                        trial_id=trial_id,
                        topology=topology,
                        fanout=fanout,
                    )
                    await update_trial_status(db, trial_id, "completed")
                    score = await _score_trial(db, trial_id, dataset)
                except Exception as exc:
                    logger.exception("Benchmark suite %s trial %s failed", suite_id, trial_id)
                    status_value = "failed"
                    score = {"error": str(exc)}
                    await update_trial_status(db, trial_id, "failed")

                await db.execute(
                    benchmark_suite_runs.update()
                    .where(benchmark_suite_runs.c.id == run_id)
                    .values(
                        status=status_value,
                        score_json=json.dumps(score, ensure_ascii=True),
                        completed_at=_now_iso(),
                    )
                )
                await db.commit()
                await _refresh_suite_status(db, suite_id)
    finally:
        _creds_var.reset(token)


@router.get("/benchmark-datasets", response_model=list[BenchmarkDatasetSummary])
async def list_benchmark_datasets() -> list[BenchmarkDatasetSummary]:
    return [dataset.summary() for dataset in DATASETS.values()]


@router.get("/benchmark-datasets/{dataset_id}/canvas", response_model=BenchmarkCanvasResponse)
async def benchmark_dataset_canvas(dataset_id: str) -> BenchmarkCanvasResponse:
    return _load_benchmark_canvas(dataset_id)


@router.get("/benchmark-suites", response_model=list[BenchmarkSuiteSummary])
async def list_benchmark_suites(db: DBDep) -> list[BenchmarkSuiteSummary]:
    rows = (
        await db.execute(select(benchmark_suites).order_by(benchmark_suites.c.created_at.desc()))
    ).mappings()
    return [BenchmarkSuiteSummary(**dict(row)) for row in rows]


@router.post(
    "/benchmark-suites",
    response_model=BenchmarkSuiteStartResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(use_credentials)],
)
async def create_benchmark_suite(
    body: BenchmarkSuiteCreateRequest,
    db: DBDep,
    background_tasks: BackgroundTasks,
) -> BenchmarkSuiteStartResponse:
    agent_ids = await _agent_ids(db)
    if not agent_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No agents found. Add at least one agent before running a benchmark suite.",
        )
    dataset = _prepare_dataset(body.dataset_id, agent_ids, body.prompt)
    planned_trials = sum(item.runs for item in body.mechanisms)
    suite_topologies = {item.topology for item in body.mechanisms}
    suite_topology = suite_topologies.pop() if len(suite_topologies) == 1 else "mixed"
    suite_id = str(uuid.uuid4())
    suite_name = f"{dataset.name} benchmark"
    await db.execute(
        benchmark_suites.insert().values(
            id=suite_id,
            name=suite_name,
            dataset_id=dataset.dataset_id,
            prompt=dataset.prompt,
            topology=suite_topology,
            fanout=body.fanout,
            rounds=body.rounds,
            status="running",
            planned_trials=planned_trials,
            completed_trials=0,
            created_at=_now_iso(),
        )
    )
    await db.commit()

    experiment_ids: list[str] = []
    trial_ids: list[str] = []
    trial_plan: list[tuple[str, str, str, str, str, int]] = []
    for mechanism in body.mechanisms:
        experiment_id = await resolve_experiment(
            db,
            prompt=dataset.prompt,
            rounds_count=body.rounds,
            mode=mechanism.mode,
            ruleset=None,
            topology=mechanism.topology,
            fanout=body.fanout,
            agent_context=dataset.agent_context,
            reuse_existing=False,
        )
        experiment_ids.append(experiment_id)
        for run_index in range(1, mechanism.runs + 1):
            trial_id = await create_trial(
                db,
                dataset.prompt,
                f"{mechanism.topology} {mechanism.mode} benchmark run {run_index}",
                mechanism.mode,
                experiment_id,
            )
            run_id = str(uuid.uuid4())
            await db.execute(
                benchmark_suite_runs.insert().values(
                    id=run_id,
                    suite_id=suite_id,
                    experiment_id=experiment_id,
                    trial_id=trial_id,
                    consensus_mode=mechanism.mode,
                    topology=mechanism.topology,
                    run_index=run_index,
                    dataset_variant_id=dataset.variant_id,
                    status="running",
                    score_json="{}",
                    created_at=_now_iso(),
                )
            )
            await db.commit()
            trial_ids.append(trial_id)
            trial_plan.append(
                (
                    run_id,
                    experiment_id,
                    trial_id,
                    mechanism.mode,
                    mechanism.topology,
                    run_index,
                )
            )

    background_tasks.add_task(
        _run_suite_background,
        suite_id,
        dataset,
        trial_plan,
        body.rounds,
        body.fanout,
        current_credentials(),
    )
    return BenchmarkSuiteStartResponse(
        suite_id=suite_id,
        planned_trials=planned_trials,
        experiment_ids=experiment_ids,
        trial_ids=trial_ids,
    )


@router.get("/benchmark-suites/{suite_id}/results", response_model=BenchmarkSuiteResultsResponse)
async def benchmark_suite_results(suite_id: str, db: DBDep) -> BenchmarkSuiteResultsResponse:
    suite_row = (
        (await db.execute(select(benchmark_suites).where(benchmark_suites.c.id == suite_id)))
        .mappings()
        .first()
    )
    if suite_row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Benchmark suite not found.")

    run_rows = (
        (
            await db.execute(
                select(benchmark_suite_runs)
                .where(benchmark_suite_runs.c.suite_id == suite_id)
                .order_by(
                    benchmark_suite_runs.c.topology,
                    benchmark_suite_runs.c.consensus_mode,
                    benchmark_suite_runs.c.run_index,
                )
            )
        )
        .mappings()
        .all()
    )

    runs: list[BenchmarkSuiteRunResult] = []
    grouped: dict[tuple[str, str], list[BenchmarkSuiteRunResult]] = defaultdict(list)
    for row in run_rows:
        data = dict(row)
        score = json.loads(data.pop("score_json") or "{}")
        result = BenchmarkSuiteRunResult(score=score, **data)
        runs.append(result)
        grouped[(result.topology, result.consensus_mode)].append(result)

    aggregates: list[BenchmarkMechanismAggregate] = []
    for (topology, mode), mode_runs in grouped.items():
        completed = [run for run in mode_runs if run.status == "completed"]
        failed = [run for run in mode_runs if run.status == "failed"]
        scored = [run for run in completed if "answer_correct" in run.score]
        accuracy = (
            sum(1 for run in scored if run.score.get("answer_correct")) / len(scored)
            if scored
            else None
        )
        round_values = [
            float(run.score["round_count"])
            for run in completed
            if isinstance(run.score.get("round_count"), (int, float))
        ]
        message_values = [
            float(run.score["message_count"])
            for run in completed
            if isinstance(run.score.get("message_count"), (int, float))
        ]
        llm_usage = await _llm_usage_for_trials([run.trial_id for run in completed])
        total_tokens = int(llm_usage["total_tokens"])
        total_cost = float(llm_usage["total_cost"])
        aggregates.append(
            BenchmarkMechanismAggregate(
                consensus_mode=mode,
                topology=topology,
                runs=len(mode_runs),
                completed=len(completed),
                failed=len(failed),
                accuracy=accuracy,
                avg_rounds=(sum(round_values) / len(round_values) if round_values else None),
                avg_messages=(
                    sum(message_values) / len(message_values) if message_values else None
                ),
                generation_count=int(llm_usage["generation_count"]),
                input_tokens=int(llm_usage["input_tokens"]),
                output_tokens=int(llm_usage["output_tokens"]),
                total_tokens=total_tokens,
                total_cost=total_cost,
                avg_tokens=(total_tokens / len(completed) if completed else None),
                avg_cost=(total_cost / len(completed) if completed else None),
            )
        )

    return BenchmarkSuiteResultsResponse(
        suite=BenchmarkSuiteSummary(**dict(suite_row)),
        runs=runs,
        aggregates=aggregates,
    )

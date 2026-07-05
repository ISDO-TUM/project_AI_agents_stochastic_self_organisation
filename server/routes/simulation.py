"""Simulation entrypoint — the mode-dispatched ``POST /api/simulation/run``.

This is shared infrastructure: it validates the request, creates trial rows and
dispatches to the selected reasoning engine. Topology runs go to
``server.topology.run_topology``; the Market-Hive (swarm) pipeline and its
blackboard/audit/status views live in ``server.market_hive``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, get_engine, resolve_experiment, update_trial_status
from server.db.tables import agents
from server.llm.credentials import RequestCredentials, current_credentials, use_credentials
from server.market_hive.amendment import LiveAmendmentProcessor
from server.market_hive.history import SwarmHistoryRecorder
from server.market_hive.market_maker import MarketMaker
from server.market_hive.orchestrator import run_swarm
from server.market_hive.schemas import SwarmRunConfig
from server.market_hive.synthesis import AnswerSynthesizer
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.topology import ConsensusMode, run_topology
from server.users import UserIdDep, scoped

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]


async def _run_batch_background(
    trial_ids: list[str],
    prompt: str,
    rounds: int,
    mode: ConsensusMode,
    agent_context: dict[str, str] | None,
    ruleset: str | None,
    topology: str,
    fanout: int,
    credentials: RequestCredentials,
    user_id: str | None,
) -> None:
    """Run trial_ids sequentially, marking each completed or failed."""
    # Re-publish the request credentials onto the ContextVar so that
    # provider clients inside run_topology can resolve API keys.
    # (BackgroundTasks run after the response is sent, so the original
    # request-scoped ContextVar has already been reset.)
    from server.llm.credentials import _current as _creds_var

    token = _creds_var.set(credentials)
    try:
        for trial_id in trial_ids:
            # Open a fresh DB connection — the request-scoped connection is closed
            # by the time the background task runs.
            async with get_engine().connect() as db:
                try:
                    await run_topology(
                        prompt,
                        db,
                        rounds=rounds,
                        mode=mode,
                        agent_context=agent_context,
                        trial_id=trial_id,
                        ruleset=ruleset,
                        topology=topology,
                        fanout=fanout,
                        user_id=user_id,
                    )
                except Exception:
                    logger.exception("Trial %s failed", trial_id)
                    await update_trial_status(db, trial_id, "failed")
                    continue
                await update_trial_status(db, trial_id, "completed")
    finally:
        _creds_var.reset(token)


async def _swarm_event_stream(
    config: SwarmRunConfig, credentials: RequestCredentials, *, parent_run_id: str | None = None
) -> AsyncGenerator[str, None]:
    """Stream a swarm run's ``SimulationStep`` events as SSE ``data:`` frames.

    Runs on a fresh connection (the request-scoped one closes once streaming
    starts) and republishes the request credentials onto the ContextVar so LLM
    and embedding calls inside ``run_swarm`` can resolve API keys.
    """
    from server.llm.credentials import _current as _creds_var

    # Flush an SSE comment immediately so the client/proxy opens the stream
    # before the first (embedding-bound) step is produced — defeats lazy buffering.
    yield ": stream open\n\n"

    token = _creds_var.set(credentials)
    try:
        async with get_engine().connect() as db:
            # The real Market Maker (one LLM call) produces a typed, scoped
            # contract — decomposed into threads for multi-step prompts — so the
            # auction invites the right specialists, and the real
            # AnswerSynthesizer (one LLM call at the end) condenses the confirmed
            # findings into a brief final answer. Both fall back to their no-LLM
            # stand-ins internally on failure, so a run never blocks. Tests drive
            # run_swarm on the no-LLM defaults.
            #
            # The amendment processor resolves request_expertise proposals at
            # end-of-round: takers vote with their own LLMs and the same Market
            # Maker casts its one equal vote (PRD §6.5).
            #
            # The recorder mirrors the run into the shared history tables so it
            # shows up on the history page and statistics dashboards like any
            # topology trial.
            recorder = SwarmHistoryRecorder(db, config.trial_id) if config.trial_id else None
            market_maker = MarketMaker()
            async for step in run_swarm(
                config,
                db,
                contract_source=market_maker,
                amendment_processor=LiveAmendmentProcessor(
                    mm_vote=market_maker.cast_amendment_vote, config=config
                ),
                synthesizer=AnswerSynthesizer(),
                parent_run_id=parent_run_id,
                recorder=recorder,
            ):
                yield f"data: {step.model_dump_json()}\n\n"
    finally:
        _creds_var.reset(token)


async def _swarm_resume_event_stream(
    run_id: str, credentials: RequestCredentials
) -> AsyncGenerator[str, None]:
    """Stream a resumed swarm run's events, same plumbing as a fresh run.

    ``run_swarm`` reconstructs the original ``SwarmRunConfig`` from the
    persisted ``swarm_runs.config`` column once it validates ``run_id`` is
    ``interrupted`` — the placeholder passed here is never used for a real run.
    """
    from server.llm.credentials import _current as _creds_var

    yield ": stream open\n\n"

    token = _creds_var.set(credentials)
    try:
        async with get_engine().connect() as db:
            async for step in run_swarm(
                SwarmRunConfig(prompt=""),
                db,
                contract_source=MarketMaker(),
                synthesizer=AnswerSynthesizer(),
                resume_run_id=run_id,
            ):
                yield f"data: {step.model_dump_json()}\n\n"
    finally:
        _creds_var.reset(token)


@router.post(
    "/{run_id}/resume",
    summary="Resume an interrupted swarm run",
    dependencies=[Depends(use_credentials)],
)
async def resume_simulation(run_id: str) -> StreamingResponse:
    return StreamingResponse(
        _swarm_resume_event_stream(run_id, current_credentials()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/run",
    response_model=SimulationStartResponse,
    summary="Run a topology simulation",
    description=(
        "Broadcast a prompt to all agents, then run discussion rounds where agents "
        "with incoming connections receive their neighbours' responses and reply with "
        "an updated view. Set iterations > 1 to run the same experiment multiple times."
    ),
    dependencies=[Depends(use_credentials)],
)
async def run_simulation(
    body: SimulationRunRequest,
    db: DBDep,
    background_tasks: BackgroundTasks,
    user_id: UserIdDep = None,
) -> SimulationStartResponse | StreamingResponse:
    count_stmt = scoped(select(func.count()).select_from(agents), agents.c.user_id, user_id)
    result = await db.execute(count_stmt)
    if result.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No agents found. Add at least one agent before running a simulation.",
        )

    # ── Swarm (ECSAS) engine: stream the run's events as SSE ──────────────────
    if body.engine == "swarm":
        if body.parent_run_id is not None:
            # Pre-validate before opening the SSE stream — an SSE response can't
            # 404/409 mid-stream once headers are sent, so fail fast here.
            parent = (
                (
                    await db.execute(
                        text("SELECT status FROM swarm_runs WHERE id = :id"),
                        {"id": body.parent_run_id},
                    )
                )
                .mappings()
                .fetchone()
            )
            if parent is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"parent_run_id {body.parent_run_id!r} not found.",
                )
            if parent["status"] == "running":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"parent_run_id {body.parent_run_id!r} is still running.",
                )

        # Swarm runs join the shared history/statistics world exactly like
        # topology runs: one experiment + one trial per click. The trial id also
        # becomes the Langfuse session id for every LLM call in the run.
        experiment_id = await resolve_experiment(
            db,
            prompt=body.prompt,
            rounds_count=body.rounds,
            mode="swarm",
            ruleset=None,
            topology="swarm",
            fanout=0,
            agent_context=None,
            reuse_existing=False,
            user_id=user_id,
        )
        trial_id = await create_trial(db, body.prompt, "swarm run", "swarm", experiment_id, user_id)
        config = SwarmRunConfig(
            prompt=body.prompt,
            trial_id=trial_id,
            experiment_id=experiment_id,
            user_id=user_id,
        )
        return StreamingResponse(
            _swarm_event_stream(config, current_credentials(), parent_run_id=body.parent_run_id),
            media_type="text/event-stream",
            headers={
                # Stream incrementally: disable client/proxy buffering so each
                # event is flushed as it is produced (Next rewrite proxy, nginx).
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    experiment_id = await resolve_experiment(
        db,
        prompt=body.prompt,
        rounds_count=body.rounds,
        mode=body.mode,
        ruleset=body.ruleset,
        topology=body.topology,
        fanout=body.fanout,
        agent_context=body.agent_context,
        reuse_existing=False,
        user_id=user_id,
    )

    trial_ids = [
        await create_trial(db, body.prompt, f"{body.mode} run", body.mode, experiment_id, user_id)
        for _ in range(body.iterations)
    ]

    captured_creds = current_credentials()
    background_tasks.add_task(
        _run_batch_background,
        trial_ids,
        body.prompt,
        body.rounds,
        body.mode,
        body.agent_context,
        body.ruleset,
        body.topology,
        body.fanout,
        captured_creds,
        user_id,
    )
    return SimulationStartResponse(
        experiment_id=experiment_id,
        trial_id=trial_ids[0],
        trial_ids=trial_ids,
    )

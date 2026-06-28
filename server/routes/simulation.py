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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, get_engine, resolve_experiment, update_trial_status
from server.db.tables import agents
from server.llm.credentials import RequestCredentials, current_credentials, use_credentials
from server.market_hive.market_maker import MarketMaker
from server.market_hive.orchestrator import run_swarm
from server.market_hive.schemas import SwarmRunConfig
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.topology import ConsensusMode, run_topology

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
                    )
                except Exception:
                    logger.exception("Trial %s failed", trial_id)
                    await update_trial_status(db, trial_id, "failed")
                    continue
                await update_trial_status(db, trial_id, "completed")
    finally:
        _creds_var.reset(token)


async def _swarm_event_stream(
    config: SwarmRunConfig, credentials: RequestCredentials
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
            # contract so the auction invites the right specialists. It falls back
            # to the no-LLM source internally if the call fails, so a run never
            # blocks. Tests drive run_swarm on the no-LLM default.
            async for step in run_swarm(config, db, contract_source=MarketMaker()):
                yield f"data: {step.model_dump_json()}\n\n"
    finally:
        _creds_var.reset(token)


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
) -> SimulationStartResponse | StreamingResponse:
    result = await db.execute(select(func.count()).select_from(agents))
    if result.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No agents found. Add at least one agent before running a simulation.",
        )

    # ── Swarm (ECSAS) engine: stream the run's events as SSE ──────────────────
    if body.engine == "swarm":
        config = SwarmRunConfig(prompt=body.prompt)
        return StreamingResponse(
            _swarm_event_stream(config, current_credentials()),
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
    )

    trial_ids = [
        await create_trial(db, body.prompt, f"{body.mode} run", body.mode, experiment_id)
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
    )
    return SimulationStartResponse(
        experiment_id=experiment_id,
        trial_id=trial_ids[0],
        trial_ids=trial_ids,
    )

"""Simulation routes — topology-aware multi-agent run."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from server.db import create_trial, get_engine, update_trial_status
from server.db.tables import agents
from server.llm.credentials import (
    RequestCredentials,
    bind_credentials,
    current_credentials,
    use_credentials,
)
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.simulation import ConsensusMode, run_topology

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


async def _mark_trial_status(engine: AsyncEngine, trial_id: str, status_value: str) -> None:
    """Record a terminal trial status on its own short-lived connection.

    Never raises: a failure to persist the status must not mask the original
    error or crash the background task.
    """
    try:
        async with engine.connect() as conn:
            await update_trial_status(conn, trial_id, status_value)
    except Exception:
        logger.exception("Failed to mark trial %s as %s", trial_id, status_value)


async def _run_simulation_background(
    prompt: str,
    engine: AsyncEngine,
    rounds: int,
    mode: ConsensusMode,
    agent_context: dict[str, str] | None,
    trial_id: str,
    ruleset: str | None,
    topology: str,
    fanout: int,
    credentials: RequestCredentials,
) -> None:
    """Run a simulation after the HTTP response has been sent.

    Runs fully decoupled from the request scope: it opens its own pooled
    connection and rebinds the credentials snapshot captured at request time,
    rather than depending on FastAPI keeping the request's yield-dependencies
    (DB connection, credentials ContextVar) alive across the background task.
    That coupling is a fragile FastAPI implementation detail and would also pin
    the request's connection for the whole multi-round run. Terminal trial
    status is always recorded, even on failure.
    """
    with bind_credentials(credentials):
        try:
            async with engine.connect() as db:
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
            logger.exception("Simulation trial %s failed", trial_id)
            await _mark_trial_status(engine, trial_id, "failed")
            return
        await _mark_trial_status(engine, trial_id, "completed")


@router.post(
    "/run",
    response_model=SimulationStartResponse,
    summary="Run a topology simulation",
    description=(
        "Broadcast a prompt to all agents, then run discussion rounds where agents "
        "with incoming connections receive their neighbours' responses and reply with "
        "an updated view."
    ),
    dependencies=[Depends(use_credentials)],
)
async def run_simulation(
    body: SimulationRunRequest,
    background_tasks: BackgroundTasks,
) -> SimulationStartResponse:
    engine = get_engine()
    # Use a short-lived connection for the pre-flight check and trial creation,
    # then release it. The simulation itself may run for minutes; we must not
    # keep a pooled connection checked out for that whole time, so the long-
    # running background task opens its own connection (see below).
    async with engine.connect() as db:
        result = await db.execute(select(func.count()).select_from(agents))
        if result.scalar_one() == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No agents found. Add at least one agent before running a simulation.",
            )
        trial_id = await create_trial(db, body.prompt, f"{body.mode} run", body.mode)

    # Capture the request-scoped credentials now: the ContextVar that backs them
    # is request-scoped, so the background task rebinds this snapshot rather than
    # relying on the request context still being active when it runs.
    credentials = current_credentials()
    background_tasks.add_task(
        _run_simulation_background,
        body.prompt,
        engine,
        body.rounds,
        body.mode,
        body.agent_context,
        trial_id,
        body.ruleset,
        body.topology,
        body.fanout,
        credentials,
    )
    return SimulationStartResponse(trial_id=trial_id)

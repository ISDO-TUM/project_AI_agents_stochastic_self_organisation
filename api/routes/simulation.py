"""Simulation routes — topology-aware multi-agent run."""

from __future__ import annotations

from typing import Annotated

import aiosqlite
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from api.db import create_trial, get_db, update_trial_status
from api.schemas import SimulationRunRequest, SimulationStartResponse
from api.simulation import ConsensusMode, run_topology

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


async def _run_simulation_background(
    prompt: str,
    db: aiosqlite.Connection,
    rounds: int,
    mode: ConsensusMode,
    agent_context: dict[str, str] | None,
    trial_id: str,
    ruleset: str | None,
) -> None:
    try:
        await run_topology(
            prompt,
            db,
            rounds=rounds,
            mode=mode,
            agent_context=agent_context,
            trial_id=trial_id,
            ruleset=ruleset,
        )
    except Exception:
        await update_trial_status(db, trial_id, "failed")
        raise
    await update_trial_status(db, trial_id, "completed")


@router.post(
    "/run",
    response_model=SimulationStartResponse,
    summary="Run a topology simulation",
    description=(
        "Broadcast a prompt to all agents, then run discussion rounds where agents "
        "with incoming connections receive their neighbours' responses and reply with "
        "an updated view."
    ),
)
async def run_simulation(
    body: SimulationRunRequest,
    db: DBDep,
    background_tasks: BackgroundTasks,
) -> SimulationStartResponse:
    async with db.execute("SELECT COUNT(*) as n FROM agents") as cur:
        row = await cur.fetchone()
    if row is None or row["n"] == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No agents found. Add at least one agent before running a simulation.",
        )

    trial_id = await create_trial(db, body.prompt, f"{body.mode} run", body.mode)
    background_tasks.add_task(
        _run_simulation_background,
        body.prompt,
        db,
        body.rounds,
        body.mode,
        body.agent_context,
        trial_id,
        body.ruleset,
    )
    return SimulationStartResponse(trial_id=trial_id)

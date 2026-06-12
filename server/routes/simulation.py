"""Simulation routes — topology-aware multi-agent run."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, resolve_experiment, update_trial_status
from server.db.tables import agents
from server.llm.credentials import use_credentials
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.simulation import ConsensusMode, run_topology

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]


async def _run_simulation_background(
    prompt: str,
    db: AsyncConnection,
    rounds: int,
    mode: ConsensusMode,
    agent_context: dict[str, str] | None,
    trial_id: str,
    ruleset: str | None,
    topology: str,
    fanout: int,
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
            topology=topology,
            fanout=fanout,
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
    dependencies=[Depends(use_credentials)],
)
async def run_simulation(
    body: SimulationRunRequest,
    db: DBDep,
    background_tasks: BackgroundTasks,
) -> SimulationStartResponse:
    result = await db.execute(select(func.count()).select_from(agents))
    if result.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No agents found. Add at least one agent before running a simulation.",
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
    )
    trial_id = await create_trial(db, body.prompt, f"{body.mode} run", body.mode, experiment_id)
    background_tasks.add_task(
        _run_simulation_background,
        body.prompt,
        db,
        body.rounds,
        body.mode,
        body.agent_context,
        trial_id,
        body.ruleset,
        body.topology,
        body.fanout,
    )
    return SimulationStartResponse(trial_id=trial_id)

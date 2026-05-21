"""Simulation routes — topology-aware multi-agent run."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import get_db
from server.db.tables import agents
from server.llm.credentials import use_credentials
from server.schemas import SimulationRunRequest, SimulationRunResponse
from server.simulation import run_topology

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]


@router.post(
    "/run",
    response_model=SimulationRunResponse,
    summary="Run a topology simulation",
    description=(
        "Broadcast a prompt to all agents, then run discussion rounds where agents "
        "with incoming connections receive their neighbours' responses and reply with "
        "an updated view."
    ),
    dependencies=[Depends(use_credentials)],
)
async def run_simulation(body: SimulationRunRequest, db: DBDep) -> SimulationRunResponse:
    result = await db.execute(select(func.count()).select_from(agents))
    if result.scalar_one() == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No agents found. Add at least one agent before running a simulation.",
        )

    outcome = await run_topology(
        body.prompt,
        db,
        rounds=body.rounds,
        mode=body.mode,
        agent_context=body.agent_context,
    )
    return SimulationRunResponse(
        steps=outcome.steps,
        consensus=outcome.consensus,
        consensus_agent_id=outcome.consensus_agent_id,
        converged=outcome.converged,
        rounds_used=outcome.rounds_used,
    )

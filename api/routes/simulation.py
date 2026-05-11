"""Simulation routes — topology-aware multi-agent run."""

from __future__ import annotations

from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from api.db import get_db
from api.schemas import SimulationRunRequest, SimulationRunResponse
from api.simulation import run_topology

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


@router.post(
    "/run",
    response_model=SimulationRunResponse,
    summary="Run a topology simulation",
    description=(
        "Broadcast a prompt to all agents, then run discussion rounds where agents "
        "with incoming connections receive their neighbours' responses and reply with "
        "an updated view."
    ),
)
async def run_simulation(body: SimulationRunRequest, db: DBDep) -> SimulationRunResponse:
    async with db.execute("SELECT COUNT(*) as n FROM agents") as cur:
        row = await cur.fetchone()
    if row is None or row["n"] == 0:
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

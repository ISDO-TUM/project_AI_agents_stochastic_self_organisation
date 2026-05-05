"""Trial run + retrieval routes, mounted at ``/api/trials``."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Annotated, Any

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.db import deserialise_agent_row, get_db
from api.llm.anthropic_provider import call_anthropic
from api.llm.openai_provider import call_openai
from api.simulation import (
    AgentSpec,
    CompleteGraphTopology,
    InMemoryPool,
    SimpleMajorityConsensus,
    Task,
)
from api.simulation.persistence import load_trial, record_trial

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trials", tags=["Trials"])
DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


class TrialRunRequest(BaseModel):
    task_prompt: str = Field(..., examples=["Should we ship on Friday?"])
    description: str = ""
    agent_ids: list[str] | None = Field(
        default=None,
        description="Agents to include. If omitted, all agents in the DB are used.",
    )
    max_rounds: int = Field(2, ge=1, le=10)


class TrialRunResponse(BaseModel):
    trial_id: str
    answer: str
    stopped_reason: str
    rounds: int


def _build_llm_call(provider: str, model: str) -> Callable[[str], str]:
    if provider == "openai":
        return lambda prompt: call_openai(prompt, model=model)
    if provider == "anthropic":
        return lambda prompt: call_anthropic(prompt, model=model)
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        f"Unsupported provider {provider!r}",
    )


async def _load_agents(
    db: aiosqlite.Connection, agent_ids: list[str] | None
) -> list[dict[str, Any]]:
    if agent_ids:
        placeholders = ",".join("?" * len(agent_ids))
        query = f"SELECT * FROM agents WHERE id IN ({placeholders})"  # noqa: S608
        async with db.execute(query, agent_ids) as cur:
            rows = await cur.fetchall()
    else:
        async with db.execute("SELECT * FROM agents") as cur:
            rows = await cur.fetchall()
    return [deserialise_agent_row(row) for row in rows]


@router.post(
    "/run",
    response_model=TrialRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run SimpleMajorityConsensus over the agent pool and persist the trace",
)
async def run_trial(body: TrialRunRequest, db: DBDep) -> TrialRunResponse:
    agents = await _load_agents(db, body.agent_ids)
    if not agents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No agents available to run the trial")

    pool = InMemoryPool(
        AgentSpec(
            id=row["id"],
            profile=row["system_prompt"],
            llm_call=_build_llm_call(row["provider"], row["model"]),
            metadata={"name": row["name"], "description": row["description"]},
        )
        for row in agents
    )
    topology = CompleteGraphTopology(pool.ids())
    task = Task(prompt=body.task_prompt)
    consensus = SimpleMajorityConsensus(max_rounds=body.max_rounds)

    try:
        result = await run_in_threadpool(consensus.run, pool, topology, task)
    except Exception as exc:
        logger.exception("Consensus run failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "LLM provider unavailable") from exc

    trial_id = await record_trial(
        db,
        description=body.description,
        protocol_name="SimpleMajorityConsensus",
        task=task,
        topology=topology,
        result=result,
    )

    return TrialRunResponse(
        trial_id=trial_id,
        answer=result.answer,
        stopped_reason=result.stopped_reason,
        rounds=len(result.rounds),
    )


@router.get(
    "/{trial_id}",
    summary="Fetch a trial with its full per-round telemetry",
)
async def get_trial(trial_id: str, db: DBDep) -> dict[str, Any]:
    trial = await load_trial(db, trial_id)
    if trial is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trial not found")
    return trial

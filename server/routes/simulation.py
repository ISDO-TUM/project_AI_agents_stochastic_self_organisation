"""Simulation routes — blackboard read endpoint, dev seed endpoint, and topology run."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, get_engine, resolve_experiment, update_trial_status
from server.db.tables import agents
from server.llm.credentials import RequestCredentials, current_credentials, use_credentials
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.simulation import ConsensusMode, run_topology
from server.swarm.blackboard import Blackboard
from server.swarm.schemas import (
    BlackboardResponse,
    ConfirmedEntrySchema,
    DraftEntrySchema,
    SeedRequest,
    SeedResponse,
    ThreadSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _build_draft_tree(entries: list[DraftEntrySchema]) -> list[DraftEntrySchema]:
    """Nest draft entries: populate children lists, return root entries only."""
    by_id = {e.id: e for e in entries}
    roots: list[DraftEntrySchema] = []
    for entry in entries:
        if entry.reply_to is None or entry.reply_to not in by_id:
            roots.append(entry)
        else:
            by_id[entry.reply_to].children.append(entry)
    return roots


@router.get(
    "/{run_id}/blackboard",
    response_model=BlackboardResponse,
    summary="Get blackboard state for a run",
)
async def get_blackboard(
    run_id: str,
    db: DBDep,
    thread_id: str | None = Query(default=None),
    layer: Literal["draft", "confirmed", "both"] = Query(default="both"),
    include_deleted: bool = Query(default=False),
) -> BlackboardResponse:
    result = await db.execute(text("SELECT id FROM swarm_runs WHERE id = :id"), {"id": run_id})
    if result.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    thread_clause = "AND id = :thread_id" if thread_id else ""
    t_params: dict[str, Any] = {"run_id": run_id}
    if thread_id:
        t_params["thread_id"] = thread_id
    t_result = await db.execute(
        text(
            f"SELECT * FROM threads WHERE run_id = :run_id {thread_clause} ORDER BY created_at ASC"
        ),
        t_params,
    )
    threads = [ThreadSchema(**dict(r._mapping)) for r in t_result.fetchall()]

    confirmed: list[ConfirmedEntrySchema] = []
    if layer in ("confirmed", "both"):
        bb = Blackboard(db)
        confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    draft: list[DraftEntrySchema] = []
    if layer in ("draft", "both"):
        vis_clause = "" if include_deleted else "AND de.is_visible = true"
        d_clause = "AND de.thread_id = :thread_id" if thread_id else ""
        d_params: dict[str, Any] = {"run_id1": run_id, "run_id2": run_id}
        if thread_id:
            d_params["thread_id"] = thread_id

        d_result = await db.execute(
            text(
                f"""
                SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                       COALESCE(a.name, de.author_id) AS author_name,
                       de.entry_type, de.content,
                       de.reply_to, de.mention_agents, de.is_visible,
                       de.deleted_at, de.last_cited_round, de.created_at,
                       COALESCE(cc.cnt, 0) AS citation_count
                FROM draft_entries de
                LEFT JOIN agents a ON a.id = de.author_id
                LEFT JOIN (
                    SELECT cited_entry_id, COUNT(*) AS cnt
                    FROM citations WHERE run_id = :run_id1
                    GROUP BY cited_entry_id
                ) cc ON cc.cited_entry_id = de.id
                WHERE de.run_id = :run_id2 {vis_clause} {d_clause}
                ORDER BY de.round ASC, de.created_at ASC
                """
            ),
            d_params,
        )

        flat: list[DraftEntrySchema] = []
        for row in d_result.mappings().fetchall():
            d = dict(row)
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            flat.append(DraftEntrySchema(**d))

        draft = _build_draft_tree(flat)

    return BlackboardResponse(threads=threads, confirmed=confirmed, draft=draft)


@router.post(
    "/seed",
    response_model=SeedResponse,
    summary="Seed test blackboard data (DEBUG only)",
)
async def seed_blackboard(body: SeedRequest, db: DBDep) -> SeedResponse:
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="seed endpoint disabled in production",
        )

    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    now = _now_iso()

    await db.execute(
        text(
            "INSERT INTO swarm_runs (id, status, mode, created_at) "
            "VALUES (:id, :status, :mode, :now)"
        ),
        {"id": run_id, "status": "running", "mode": "swarm", "now": now},
    )
    await db.execute(
        text(
            "INSERT INTO contracts "
            "(id, run_id, original_prompt, task_type, task_nature, created_at) "
            "VALUES (:id, :run_id, :prompt, :task_type, :task_nature, :now)"
        ),
        {
            "id": contract_id,
            "run_id": run_id,
            "prompt": body.prompt,
            "task_type": "analysis",
            "task_nature": "single",
            "now": now,
        },
    )
    await db.execute(
        text(
            "INSERT INTO threads "
            "(id, contract_id, run_id, title, description, created_at) "
            "VALUES (:id, :contract_id, :run_id, :title, :description, :now)"
        ),
        {
            "id": thread_id,
            "contract_id": contract_id,
            "run_id": run_id,
            "title": "Main Thread",
            "description": body.prompt,
            "now": now,
        },
    )
    await db.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, content, entry_type, round_confirmed, created_at) "
            "VALUES (:id, :run_id, :thread_id, :content, :entry_type, :round, :now)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "thread_id": thread_id,
            "content": f"[ANCHOR] Contract: {body.prompt}",
            "entry_type": "anchor",
            "round": 0,
            "now": now,
        },
    )

    bb = Blackboard(db)
    for agent_id in body.agent_ids[:5]:
        agent_result = await db.execute(select(agents.c.id).where(agents.c.id == agent_id))
        if agent_result.fetchone() is None:
            continue
        await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=agent_id,
            content=f"Seed proposal from agent {agent_id[:8]}. Analyzing: {body.prompt}",
            entry_type="proposal",
            round=1,
        )

    await db.commit()
    return SeedResponse(run_id=run_id, thread_id=thread_id)


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
    return SimulationStartResponse(trial_id=trial_ids[0], trial_ids=trial_ids)

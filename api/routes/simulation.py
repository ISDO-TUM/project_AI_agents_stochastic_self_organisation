"""Simulation routes — blackboard read endpoint and dev seed endpoint."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.db import get_db
from api.swarm.blackboard import Blackboard
from api.swarm.schemas import (
    BlackboardResponse,
    ConfirmedEntrySchema,
    DraftEntrySchema,
    SeedRequest,
    SeedResponse,
    ThreadSchema,
)

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    # Verify run exists
    async with db.execute(
        "SELECT id FROM swarm_runs WHERE id=?", (run_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    # Fetch threads
    thread_clause = "AND id=?" if thread_id else ""
    thread_params = [run_id] + ([thread_id] if thread_id else [])
    async with db.execute(
        f"SELECT * FROM threads WHERE run_id=? {thread_clause} ORDER BY created_at ASC",
        thread_params,
    ) as cur:
        thread_rows = await cur.fetchall()
    threads = [ThreadSchema(**dict(r)) for r in thread_rows]

    # Fetch confirmed entries
    confirmed: list[ConfirmedEntrySchema] = []
    if layer in ("confirmed", "both"):
        bb = Blackboard(db)
        confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    # Fetch draft entries
    draft: list[DraftEntrySchema] = []
    if layer in ("draft", "both"):
        vis_clause = "" if include_deleted else "AND de.is_visible=1"
        t_clause = "AND de.thread_id=?" if thread_id else ""
        params: list = [run_id, run_id]
        if thread_id:
            params.append(thread_id)

        async with db.execute(
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
                FROM citations WHERE run_id=?
                GROUP BY cited_entry_id
            ) cc ON cc.cited_entry_id = de.id
            WHERE de.run_id=? {vis_clause} {t_clause}
            ORDER BY de.round ASC, de.created_at ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()

        flat: list[DraftEntrySchema] = []
        for row in rows:
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
        "INSERT INTO swarm_runs (id, status, mode, created_at) VALUES (?,?,?,?)",
        (run_id, "running", "swarm", now),
    )
    await db.execute(
        "INSERT INTO contracts "
        "(id, run_id, original_prompt, task_type, task_nature, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (contract_id, run_id, body.prompt, "analysis", "single", now),
    )
    await db.execute(
        "INSERT INTO threads "
        "(id, contract_id, run_id, title, description, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (thread_id, contract_id, run_id, "Main Thread", body.prompt, now),
    )

    # Confirmed anchor
    await db.execute(
        "INSERT INTO confirmed_entries "
        "(id, run_id, thread_id, content, entry_type, round_confirmed, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()), run_id, thread_id,
            f"[ANCHOR] Contract: {body.prompt}", "anchor", 0, now,
        ),
    )

    # Draft proposals from each agent
    bb = Blackboard(db)
    for agent_id in body.agent_ids[:5]:  # cap at 5 agents
        async with db.execute(
            "SELECT id FROM agents WHERE id=?", (agent_id,)
        ) as cur:
            if await cur.fetchone() is None:
                continue
        await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=agent_id,
            content=f"Seed proposal from agent {agent_id[:8]}. "
                    f"Analyzing: {body.prompt}",
            entry_type="proposal",
            round=1,
        )

    await db.commit()
    return SeedResponse(run_id=run_id, thread_id=thread_id)

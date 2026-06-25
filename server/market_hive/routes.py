"""HTTP routes owned by the Market-Hive (ECSAS) engine.

Read-only blackboard / audit / status views plus the dev seed endpoint and the
cross-run agent-trust lookup. The mode-dispatched ``POST /api/simulation/run``
stays in the shared ``server/routes/simulation.py`` (it dispatches to either
engine); everything here is Market-Hive domain.

The router carries no prefix and spells out full paths, so it can host both the
``/api/simulation/*`` blackboard surface and ``/api/agents/{id}/trust`` while
keeping the entire Market-Hive HTTP surface in one place.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import get_db
from server.db.tables import agent_trust, agents
from server.market_hive.blackboard import Blackboard
from server.market_hive.schemas import (
    AgentTrustEntry,
    AmendmentSchema,
    AuditResponse,
    BidSchema,
    BlackboardResponse,
    CitationSchema,
    ConfirmedEntrySchema,
    ContractSchema,
    DraftEntrySchema,
    ReputationSchema,
    RunStatusResponse,
    SeedRequest,
    SeedResponse,
    SwarmRunSchema,
    ThreadSchema,
    VoteSchema,
)

router = APIRouter(tags=["Market Hive"])

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


async def _fetch_draft_entries(
    db: AsyncConnection, run_id: str, *, include_deleted: bool
) -> list[DraftEntrySchema]:
    """Flat list of draft entries with author_name + citation_count joined in."""
    vis_clause = "" if include_deleted else "AND de.is_visible = true"
    result = await db.execute(
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
            WHERE de.run_id = :run_id2 {vis_clause}
            ORDER BY de.round ASC, de.created_at ASC
            """
        ),
        {"run_id1": run_id, "run_id2": run_id},
    )
    entries: list[DraftEntrySchema] = []
    for row in result.mappings().fetchall():
        d = dict(row)
        d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
        d["children"] = []
        entries.append(DraftEntrySchema(**d))
    return entries


@router.get(
    "/api/simulation/{run_id}/blackboard",
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
        all_entries = await _fetch_draft_entries(db, run_id, include_deleted=include_deleted)
        if thread_id:
            all_entries = [e for e in all_entries if e.thread_id == thread_id]
        draft = _build_draft_tree(all_entries)

    return BlackboardResponse(threads=threads, confirmed=confirmed, draft=draft)


@router.get(
    "/api/simulation/{run_id}/audit",
    response_model=AuditResponse,
    summary="Full audit trail for a run",
)
async def get_audit(run_id: str, db: DBDep) -> AuditResponse:
    """Dump every table scoped to *run_id*, including soft-deleted draft entries.

    Implements the auditability-by-construction principle (PRD §P-11): nothing is
    hidden, soft-deleted entries are returned so the full discussion is reproducible.
    """
    run_result = await db.execute(text("SELECT * FROM swarm_runs WHERE id = :id"), {"id": run_id})
    run_row = run_result.mappings().fetchone()
    if run_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    contract_result = await db.execute(
        text("SELECT * FROM contracts WHERE run_id = :id ORDER BY created_at ASC LIMIT 1"),
        {"id": run_id},
    )
    contract_row = contract_result.mappings().fetchone()
    contract = ContractSchema(**dict(contract_row)) if contract_row else None

    async def _rows(table: str, order: str = "created_at ASC") -> list[dict[str, Any]]:
        res = await db.execute(
            text(f"SELECT * FROM {table} WHERE run_id = :id ORDER BY {order}"),
            {"id": run_id},
        )
        return [dict(r) for r in res.mappings().fetchall()]

    threads = [ThreadSchema(**r) for r in await _rows("threads")]
    bids = [BidSchema(**r) for r in await _rows("bids")]
    citations = [CitationSchema(**r) for r in await _rows("citations")]
    votes = [VoteSchema(**r) for r in await _rows("votes")]
    confirmed = [
        ConfirmedEntrySchema(**r) for r in await _rows("confirmed_entries", "round_confirmed ASC")
    ]
    amendments = [AmendmentSchema(**r) for r in await _rows("amendments")]
    reputation = [ReputationSchema(**r) for r in await _rows("reputation", "updated_at ASC")]
    draft_entries = await _fetch_draft_entries(db, run_id, include_deleted=True)

    return AuditResponse(
        run=SwarmRunSchema(**dict(run_row)),
        contract=contract,
        threads=threads,
        bids=bids,
        draft_entries=draft_entries,
        citations=citations,
        votes=votes,
        confirmed_entries=confirmed,
        amendments=amendments,
        reputation=reputation,
        final_output=None,
    )


@router.get(
    "/api/simulation/{run_id}/status",
    response_model=RunStatusResponse,
    summary="Run status summary",
)
async def get_run_status(run_id: str, db: DBDep) -> RunStatusResponse:
    run_result = await db.execute(
        text("SELECT status, termination_reason, token_usage FROM swarm_runs WHERE id = :id"),
        {"id": run_id},
    )
    run_row = run_result.mappings().fetchone()
    if run_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    round_result = await db.execute(
        text("SELECT COALESCE(MAX(round), 0) AS r FROM draft_entries WHERE run_id = :id"),
        {"id": run_id},
    )
    current_round = int(round_result.scalar_one() or 0)

    return RunStatusResponse(
        run_id=run_id,
        status=run_row["status"],
        current_round=current_round,
        termination_reason=run_row["termination_reason"],
        token_usage=json.loads(run_row["token_usage"] or "{}"),
    )


@router.post(
    "/api/simulation/seed",
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


@router.get(
    "/api/agents/{agent_id}/trust",
    response_model=list[AgentTrustEntry],
    summary="Get cross-run trust scores for an agent",
)
async def get_agent_trust(agent_id: str, db: DBDep) -> list[AgentTrustEntry]:
    """Return the agent's persistent per-domain trust scores.

    Empty list for an agent that has never participated in a swarm run.
    """
    result = await db.execute(
        select(
            agent_trust.c.domain,
            agent_trust.c.trust_score,
            agent_trust.c.runs_participated,
            agent_trust.c.updated_at,
        )
        .where(agent_trust.c.agent_id == agent_id)
        .order_by(agent_trust.c.trust_score.desc())
    )
    return [AgentTrustEntry(**dict(row)) for row in result.mappings().all()]

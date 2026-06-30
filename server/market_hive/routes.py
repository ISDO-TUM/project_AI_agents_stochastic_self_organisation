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
from typing import Annotated, Any, Literal, cast

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
    SeedRichResponse,
    SwarmRunSchema,
    ThreadSchema,
    VoteSchema,
)
from server.market_hive.termination import TerminationEngine, TerminationReason

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
    final_output = None
    reason = run_row["termination_reason"]
    term_round = run_row["termination_round"]
    if reason in ("equilibrium", "max_rounds", "budget") and term_round is not None:
        final_output = await TerminationEngine(db).format_output(
            run_id=run_id,
            termination_round=int(term_round),
            termination_reason=cast(TerminationReason, reason),
            metadata={"token_usage": json.loads(run_row["token_usage"] or "{}")},
        )

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
        final_output=final_output,
    )


@router.get(
    "/api/simulation/{run_id}/status",
    response_model=RunStatusResponse,
    summary="Run status summary",
)
async def get_run_status(run_id: str, db: DBDep) -> RunStatusResponse:
    run_result = await db.execute(
        text(
            "SELECT status, termination_reason, termination_round, token_usage "
            "FROM swarm_runs WHERE id = :id"
        ),
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
        termination_round=run_row["termination_round"],
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


@router.post(
    "/api/simulation/seed-rich",
    response_model=SeedRichResponse,
    summary="Seed rich multi-agent blackboard scenario (DEBUG only)",
)
async def seed_blackboard_rich(db: DBDep) -> SeedRichResponse:
    if os.getenv("DEBUG", "").lower() not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="seed endpoint disabled in production",
        )

    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread1_id = str(uuid.uuid4())
    thread2_id = str(uuid.uuid4())
    alpha_id = str(uuid.uuid4())
    beta_id = str(uuid.uuid4())
    gamma_id = str(uuid.uuid4())
    now = _now_iso()

    for aid, name, desc in [
        (alpha_id, "Alpha", "Contract law specialist"),
        (beta_id, "Beta", "Financial risk analyst"),
        (gamma_id, "Gamma", "General reasoning agent"),
    ]:
        await db.execute(
            text(
                "INSERT INTO agents (id, name, description, system_prompt, provider, model, "
                "tools, connections, created_at) "
                "VALUES (:id, :name, :desc, :sp, 'anthropic', 'claude-opus-4-8', "
                "'[]', '[]', :now)"
            ),
            {"id": aid, "name": name, "desc": desc, "sp": f"You are {name}.", "now": now},
        )

    prompt = "Analyze this energy procurement contract for legal and financial compliance issues."
    await db.execute(
        text(
            "INSERT INTO swarm_runs (id, status, mode, created_at) "
            "VALUES (:id, 'running', 'swarm', :now)"
        ),
        {"id": run_id, "now": now},
    )
    await db.execute(
        text(
            "INSERT INTO contracts "
            "(id, run_id, original_prompt, task_type, task_nature, required_expertise, created_at) "
            "VALUES (:id, :run_id, :prompt, 'analysis', 'multi', "
            '\'["contract_law","finance"]\', :now)'
        ),
        {"id": contract_id, "run_id": run_id, "prompt": prompt, "now": now},
    )
    for tid, title, desc, expertise in [
        (
            thread1_id,
            "Legal Compliance Analysis",
            "Review all clauses for legal compliance and enforceability.",
            '["contract_law"]',
        ),
        (
            thread2_id,
            "Financial Risk Assessment",
            "Assess pricing, DCF assumptions, and hedging provisions.",
            '["finance"]',
        ),
    ]:
        await db.execute(
            text(
                "INSERT INTO threads "
                "(id, contract_id, run_id, title, description, required_expertise, created_at) "
                "VALUES (:id, :cid, :run_id, :title, :desc, :exp, :now)"
            ),
            {
                "id": tid,
                "cid": contract_id,
                "run_id": run_id,
                "title": title,
                "desc": desc,
                "exp": expertise,
                "now": now,
            },
        )

    bb = Blackboard(db)
    await bb.post_anchor(run_id=run_id, thread_id=thread1_id, content=f"[CONTRACT] {prompt}")
    await bb.post_anchor(
        run_id=run_id,
        thread_id=thread1_id,
        content="[THREAD] Legal Compliance Analysis — expertise: contract_law",
    )
    await bb.post_anchor(
        run_id=run_id,
        thread_id=thread2_id,
        content="[THREAD] Financial Risk Assessment — expertise: finance",
    )

    bb1 = await bb.post(
        run_id=run_id,
        thread_id=thread1_id,
        author_id=alpha_id,
        content=(
            "The penalty clause in §4.2 is ambiguous: the liquidated damages formula "
            "contradicts the hard cap in §7.1. One of these must be struck."
        ),
        entry_type="proposal",
        round=1,
    )
    await bb.post(
        run_id=run_id,
        thread_id=thread1_id,
        author_id=gamma_id,
        content=(
            "Force majeure clause in §9 is broader than standard — it includes "
            "supplier insolvency, which is uncommon and may void termination rights."
        ),
        entry_type="proposal",
        round=1,
    )
    bb3 = await bb.post(
        run_id=run_id,
        thread_id=thread1_id,
        author_id=beta_id,
        content="Agree — the formula in §7.1 sets a hard cap that §4.2 ignores.",
        entry_type="reply",
        round=1,
        reply_to=bb1,
    )
    await bb.post(
        run_id=run_id,
        thread_id=thread1_id,
        author_id=beta_id,
        content="VOTE: BB-001 (§4.2 analysis) is the most legally grounded proposal.",
        entry_type="vote",
        round=2,
    )
    bb5 = await bb.post(
        run_id=run_id,
        thread_id=thread2_id,
        author_id=beta_id,
        content=(
            "The DCF assumptions in the pricing schedule use a 7% discount rate "
            "with no sensitivity analysis. This understates financial exposure."
        ),
        entry_type="proposal",
        round=1,
    )
    await bb.post(
        run_id=run_id,
        thread_id=thread2_id,
        author_id=gamma_id,
        content=(
            "Currency hedging provisions are entirely absent from the FX schedule, "
            "leaving both parties exposed to exchange rate volatility."
        ),
        entry_type="proposal",
        round=1,
    )

    await bb.cite(run_id=run_id, citing_agent_id=beta_id, entry_ids=[bb1], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=gamma_id, entry_ids=[bb1], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=alpha_id, entry_ids=[bb3], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=alpha_id, entry_ids=[bb5], round=2)

    await bb.post(
        run_id=run_id,
        thread_id=thread1_id,
        author_id=alpha_id,
        content="@Gamma, can you verify the financial exposure of the §7.1 cap?",
        entry_type="reply",
        round=2,
        reply_to=bb3,
        mention_agents=[gamma_id],
    )
    await bb.post(
        run_id=run_id,
        thread_id=thread2_id,
        author_id=gamma_id,
        content="The 7% rate is outdated — current WACC for this sector is closer to 8.5%.",
        entry_type="reply",
        round=2,
        reply_to=bb5,
    )

    await bb.check_promotions(
        run_id=run_id,
        current_round=2,
        participants_by_thread={thread1_id: 3, thread2_id: 2},
    )
    await bb.soft_delete_stale(run_id=run_id, current_round=4, decay_rounds=3)

    await db.commit()
    return SeedRichResponse(
        run_id=run_id,
        thread_ids=[thread1_id, thread2_id],
        agent_ids=[alpha_id, beta_id, gamma_id],
    )


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

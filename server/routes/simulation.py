"""Simulation routes — blackboard read endpoint, dev seed endpoint, and topology run."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import create_trial, get_db, get_engine, update_trial_status
from server.db.tables import agents
from server.llm.credentials import RequestCredentials, current_credentials, use_credentials
from server.schemas import SimulationRunRequest, SimulationStartResponse
from server.simulation import ConsensusMode, run_topology
from server.swarm.blackboard import Blackboard
from server.swarm.schemas import (
    AuditCitation,
    AuditResponse,
    AuditVote,
    BlackboardResponse,
    ConfirmedEntrySchema,
    DraftEntrySchema,
    SeedRequest,
    SeedResponse,
    SeedRichResponse,
    ThreadSchema,
)

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


@router.get(
    "/{run_id}/audit",
    response_model=AuditResponse,
    summary="Full audit trail for a run (includes soft-deleted entries)",
)
async def get_audit(run_id: str, db: DBDep) -> AuditResponse:
    result = await db.execute(text("SELECT id FROM swarm_runs WHERE id = :id"), {"id": run_id})
    if result.fetchone() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")

    d_result = await db.execute(
        text(
            """
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
            WHERE de.run_id = :run_id2
            ORDER BY de.round ASC, de.created_at ASC
            """
        ),
        {"run_id1": run_id, "run_id2": run_id},
    )
    all_drafts: list[DraftEntrySchema] = []
    for row in d_result.mappings().fetchall():
        d = dict(row)
        d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
        d["children"] = []
        all_drafts.append(DraftEntrySchema(**d))

    c_result = await db.execute(
        text("SELECT * FROM citations WHERE run_id = :run_id ORDER BY created_at ASC"),
        {"run_id": run_id},
    )
    citations = [AuditCitation(**dict(r._mapping)) for r in c_result.fetchall()]

    v_result = await db.execute(
        text("SELECT * FROM votes WHERE run_id = :run_id ORDER BY created_at ASC"),
        {"run_id": run_id},
    )
    votes = [AuditVote(**dict(r._mapping)) for r in v_result.fetchall()]

    bb = Blackboard(db)
    confirmed = await bb.get_confirmed(run_id=run_id)

    return AuditResponse(
        run_id=run_id,
        all_draft_entries=all_drafts,
        citations=citations,
        votes=votes,
        confirmed_entries=confirmed,
    )


@router.post(
    "/seed-rich",
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

    # ── agents ────────────────────────────────────────────────────────────
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

    # ── run + contract ────────────────────────────────────────────────────
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

    # ── threads ───────────────────────────────────────────────────────────
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

    # ── anchors ───────────────────────────────────────────────────────────
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

    # ── round 1 draft entries ─────────────────────────────────────────────
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

    # ── citations (round 2) ───────────────────────────────────────────────
    # BB-001: cited by Beta + Gamma → citation_count=2, last_cited_round=2
    await bb.cite(run_id=run_id, citing_agent_id=beta_id, entry_ids=[bb1], round=2)
    await bb.cite(run_id=run_id, citing_agent_id=gamma_id, entry_ids=[bb1], round=2)
    # BB-003: cited by Alpha
    await bb.cite(run_id=run_id, citing_agent_id=alpha_id, entry_ids=[bb3], round=2)
    # BB-005: cited by Alpha
    await bb.cite(run_id=run_id, citing_agent_id=alpha_id, entry_ids=[bb5], round=2)

    # ── round 2 draft entries ─────────────────────────────────────────────
    # Alpha replies to BB-003 and mentions Gamma
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

    # ── promote entries that met the threshold ────────────────────────────
    # Thread1: 3 participants → M=2; BB-001 has 2 distinct citers → promoted
    # Thread2: 2 participants → M=1; BB-005 has 1 distinct citer → promoted
    await bb.check_promotions(
        run_id=run_id,
        current_round=2,
        participants_by_thread={thread1_id: 3, thread2_id: 2},
    )

    # ── soft-delete stale entries (BB-002, BB-006 never cited) ────────────
    # last_cited_round=1 for those entries; at current_round=4, decay_rounds=3:
    # 4-1=3 >= 3 → deleted. BB-001/003/005: last_cited_round=2, 4-2=2 < 3 → kept.
    await bb.soft_delete_stale(run_id=run_id, current_round=4, decay_rounds=3)

    await db.commit()
    return SeedRichResponse(
        run_id=run_id,
        thread_ids=[thread1_id, thread2_id],
        agent_ids=[alpha_id, beta_id, gamma_id],
    )


async def _run_simulation_background(
    prompt: str,
    rounds: int,
    mode: ConsensusMode,
    agent_context: dict[str, str] | None,
    trial_id: str,
    ruleset: str | None,
    topology: str,
    fanout: int,
    credentials: RequestCredentials,
) -> None:
    # Re-publish the request credentials onto the ContextVar so that
    # provider clients inside run_topology can resolve API keys.
    # (BackgroundTasks run after the response is sent, so the original
    # request-scoped ContextVar has already been reset.)
    from server.llm.credentials import _current as _creds_var

    token = _creds_var.set(credentials)
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
            await update_trial_status(db, trial_id, "failed")
            raise
        finally:
            _creds_var.reset(token)
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

    trial_id = await create_trial(db, body.prompt, f"{body.mode} run", body.mode)
    # Capture credentials now — the ContextVar is reset once the response is sent,
    # so the background task would otherwise see empty/env-only credentials.
    captured_creds = current_credentials()
    background_tasks.add_task(
        _run_simulation_background,
        body.prompt,
        body.rounds,
        body.mode,
        body.agent_context,
        trial_id,
        body.ruleset,
        body.topology,
        body.fanout,
        captured_creds,
    )
    return SimulationStartResponse(trial_id=trial_id)

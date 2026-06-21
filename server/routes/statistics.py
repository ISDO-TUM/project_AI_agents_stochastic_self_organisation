"""Aggregated collaboration statistics endpoints."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import get_db
from server.db.tables import agents, connections, messages, rounds, trials
from server.schemas import (
    AgentStatistics,
    EdgeStatistics,
    LangfuseAgentStatistics,
    LangfuseModelStatistics,
    LangfuseRoundStatistics,
    LangfuseStatisticsResponse,
    LangfuseStatisticsSummary,
    RoundStatistics,
    TrialStatisticsSummary,
)

router = APIRouter(prefix="/api/statistics", tags=["Statistics"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]

_MSG_ROUNDS = messages.join(rounds, rounds.c.id == messages.c.round_id)
_CONN_ROUNDS = connections.join(rounds, rounds.c.id == connections.c.round_id)


def _is_agent_edge(from_agent_id: str | None, to_agent_id: str | None) -> bool:
    """True for real agent-to-agent communication edges, not system/self rows."""
    return from_agent_id is not None and to_agent_id is not None and from_agent_id != to_agent_id


async def _require_trial(db: AsyncConnection, trial_id: str) -> dict[str, object]:
    result = await db.execute(select(trials).where(trials.c.id == trial_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trial not found.")
    return dict(row)


async def _agent_names(db: AsyncConnection, ids: set[str]) -> dict[str, str]:
    if not ids:
        return {}
    rows = await db.execute(select(agents.c.id, agents.c.name).where(agents.c.id.in_(ids)))
    return {row.id: row.name for row in rows.all()}


@router.get("/trials/{trial_id}/summary", response_model=TrialStatisticsSummary)
async def trial_summary(trial_id: str, db: DBDep) -> TrialStatisticsSummary:
    trial = await _require_trial(db, trial_id)

    round_count = await db.scalar(
        select(func.count()).select_from(rounds).where(rounds.c.trial_id == trial_id)
    )
    total_messages = await db.scalar(
        select(func.count()).select_from(_MSG_ROUNDS).where(rounds.c.trial_id == trial_id)
    )

    type_rows = await db.execute(
        select(messages.c.message_type, func.count().label("n"))
        .select_from(_MSG_ROUNDS)
        .where(rounds.c.trial_id == trial_id)
        .group_by(messages.c.message_type)
    )
    message_type_counts = {row.message_type: row.n for row in type_rows.all()}

    connection_rows = (
        await db.execute(
            select(connections.c.from_agent_id, connections.c.to_agent_id)
            .select_from(_CONN_ROUNDS)
            .where(rounds.c.trial_id == trial_id)
        )
    ).all()
    agent_ids: set[str] = set()
    edges: set[tuple[str, str]] = set()
    for frm, to in connection_rows:
        if frm is not None:
            agent_ids.add(frm)
        if to is not None:
            agent_ids.add(to)
        if _is_agent_edge(frm, to):
            edges.add((frm, to))

    return TrialStatisticsSummary(
        trial_id=trial_id,
        user_prompt=str(trial["user_prompt"]),
        description=str(trial["description"]),
        mode=str(trial["mode"]) if trial["mode"] is not None else None,
        status=str(trial["status"]),
        created_at=str(trial["created_at"]),
        round_count=round_count or 0,
        agent_count=len(agent_ids),
        total_messages=total_messages or 0,
        total_edges=len(edges),
        message_type_counts=message_type_counts,
    )


@router.get("/trials/{trial_id}/agents", response_model=list[AgentStatistics])
async def trial_agents(trial_id: str, db: DBDep) -> list[AgentStatistics]:
    await _require_trial(db, trial_id)

    message_rows = (
        await db.execute(
            select(
                messages.c.from_agent_id,
                messages.c.to_agent_id,
                messages.c.message_type,
                messages.c.from_agent_name,
                messages.c.to_agent_name,
            )
            .select_from(_MSG_ROUNDS)
            .where(rounds.c.trial_id == trial_id)
        )
    ).all()
    connection_rows = (
        await db.execute(
            select(
                connections.c.from_agent_id,
                connections.c.to_agent_id,
                connections.c.from_agent_name,
                connections.c.to_agent_name,
            )
            .select_from(_CONN_ROUNDS)
            .where(rounds.c.trial_id == trial_id)
        )
    ).all()

    sent: Counter[str] = Counter()
    received: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    out_targets: defaultdict[str, set[str]] = defaultdict(set)
    in_sources: defaultdict[str, set[str]] = defaultdict(set)
    involved: set[str] = set()
    # Names snapshotted on the history rows, so they survive agent deletion.
    names: dict[str, str] = {}

    def _remember(agent_id: str | None, name: str | None) -> None:
        if agent_id is not None and name:
            names.setdefault(agent_id, name)

    for frm, to, frm_name, to_name in connection_rows:
        _remember(frm, frm_name)
        _remember(to, to_name)
        if frm is not None:
            involved.add(frm)
        if to is not None:
            involved.add(to)
        if _is_agent_edge(frm, to):
            out_targets[frm].add(to)
            in_sources[to].add(frm)

    for frm, to, mtype, frm_name, to_name in message_rows:
        _remember(frm, frm_name)
        _remember(to, to_name)
        if frm is not None:
            sent[frm] += 1
            involved.add(frm)
            if mtype == "tool":
                tools[frm] += 1
        if to is not None:
            received[to] += 1
            involved.add(to)

    # Fall back to the live agents table for ids without a snapshotted name
    # (legacy rows written before name snapshots existed).
    missing = involved - names.keys()
    if missing:
        names.update(await _agent_names(db, missing))

    return [
        AgentStatistics(
            agent_id=aid,
            agent_name=names.get(aid, "Unknown"),
            messages_sent=sent[aid],
            messages_received=received[aid],
            out_degree=len(out_targets[aid]),
            in_degree=len(in_sources[aid]),
            tool_invocations=tools[aid],
        )
        for aid in sorted(involved, key=lambda a: sent[a] + received[a], reverse=True)
    ]


def _num(data: Any, *keys: str) -> float:
    """Read the first numeric value from a dict-like or object-like source."""
    for key in keys:
        value = data.get(key) if isinstance(data, dict) else getattr(data, key, None)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def _metadata(row: Any) -> dict[str, Any]:
    value = getattr(row, "metadata", None)
    return value if isinstance(value, dict) else {}


def _usage(row: Any) -> tuple[int, int]:
    usage_details = getattr(row, "usage_details", None)
    usage = getattr(row, "usage", None)
    input_tokens = _num(
        usage_details,
        "input",
        "input_tokens",
        "prompt_tokens",
        "promptTokens",
    ) or _num(usage, "input", "input_tokens", "prompt_tokens", "promptTokens")
    output_tokens = _num(
        usage_details,
        "output",
        "output_tokens",
        "completion_tokens",
        "completionTokens",
    ) or _num(usage, "output", "output_tokens", "completion_tokens", "completionTokens")
    return int(input_tokens), int(output_tokens)


def _cost(row: Any) -> float:
    cost_details = getattr(row, "cost_details", None)
    return (
        _num(row, "calculated_total_cost", "total_cost", "total_price")
        or _num(cost_details, "total", "total_cost")
        or 0.0
    )


def _latency_ms(row: Any) -> float:
    return float(_num(row, "latency") * 1000)


async def _fetch_langfuse_observations(trial_id: str) -> tuple[list[Any], str | None]:
    """Fetch all Langfuse observations for traces whose session_id is trial_id."""
    try:
        from langfuse import Langfuse

        client = Langfuse()
    except Exception as exc:
        return [], f"Langfuse client is not configured: {exc}"

    def _fetch() -> tuple[list[Any], str | None]:
        traces: list[Any] = []
        page = 1
        while True:
            res = client.fetch_traces(session_id=trial_id, page=page, limit=100)
            traces.extend(res.data)
            if page >= res.meta.total_pages:
                break
            page += 1

        observations: list[Any] = []
        for trace in traces:
            obs_page = 1
            while True:
                obs_res = client.fetch_observations(
                    trace_id=trace.id,
                    type="GENERATION",
                    page=obs_page,
                    limit=100,
                )
                observations.extend(obs_res.data)
                if obs_page >= obs_res.meta.total_pages:
                    break
                obs_page += 1
        return observations, None

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        return [], f"Langfuse request failed: {exc}"


def _empty_langfuse_response(trial_id: str, message: str | None) -> LangfuseStatisticsResponse:
    return LangfuseStatisticsResponse(
        summary=LangfuseStatisticsSummary(
            trial_id=trial_id,
            trace_count=0,
            generation_count=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            total_cost=0.0,
            average_latency_ms=0.0,
            slowest_agent_name=None,
            slowest_model=None,
        ),
        agents=[],
        models=[],
        rounds=[],
        available=False,
        message=message,
    )


@router.get("/trials/{trial_id}/langfuse", response_model=LangfuseStatisticsResponse)
async def trial_langfuse(trial_id: str, db: DBDep) -> LangfuseStatisticsResponse:
    await _require_trial(db, trial_id)

    observations, error = await _fetch_langfuse_observations(trial_id)
    if error:
        return _empty_langfuse_response(trial_id, error)
    if not observations:
        return _empty_langfuse_response(
            trial_id,
            "No Langfuse generations found for this trial. New runs include trial metadata.",
        )

    by_agent: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_round: dict[tuple[int, str], dict[str, Any]] = {}
    total_in = total_out = 0
    total_cost = 0.0
    latencies: list[float] = []
    slowest_latency = -1.0
    slowest_agent_name: str | None = None
    slowest_model: str | None = None
    trace_ids = {getattr(obs, "trace_id", "") for obs in observations}

    for obs in observations:
        md = _metadata(obs)
        in_tokens, out_tokens = _usage(obs)
        tokens = in_tokens + out_tokens
        cost = _cost(obs)
        latency = _latency_ms(obs)
        if latency:
            latencies.append(latency)

        total_in += in_tokens
        total_out += out_tokens
        total_cost += cost

        agent_id = str(md.get("agent_id") or "unknown")
        agent_name = str(md.get("agent_name") or "Unknown")
        agent_bucket = by_agent.setdefault(
            agent_id,
            {
                "agent_name": agent_name,
                "count": 0,
                "in": 0,
                "out": 0,
                "cost": 0.0,
                "latencies": [],
            },
        )
        agent_bucket["count"] += 1
        agent_bucket["in"] += in_tokens
        agent_bucket["out"] += out_tokens
        agent_bucket["cost"] += cost
        if latency:
            agent_bucket["latencies"].append(latency)

        model = str(getattr(obs, "model", None) or md.get("model") or "unknown")
        model_bucket = by_model.setdefault(
            model,
            {"count": 0, "in": 0, "out": 0, "cost": 0.0, "latencies": []},
        )
        model_bucket["count"] += 1
        model_bucket["in"] += in_tokens
        model_bucket["out"] += out_tokens
        model_bucket["cost"] += cost
        if latency:
            model_bucket["latencies"].append(latency)

        round_index = int(md.get("round_index") or 0)
        phase = str(md.get("phase") or "unknown")
        round_bucket = by_round.setdefault(
            (round_index, phase),
            {"count": 0, "tokens": 0, "cost": 0.0, "latencies": []},
        )
        round_bucket["count"] += 1
        round_bucket["tokens"] += tokens
        round_bucket["cost"] += cost
        if latency:
            round_bucket["latencies"].append(latency)

        if latency > slowest_latency:
            slowest_latency = latency
            slowest_agent_name = agent_name
            slowest_model = model

    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    agent_rows = [
        LangfuseAgentStatistics(
            agent_id=agent_id,
            agent_name=str(bucket["agent_name"]),
            generation_count=int(bucket["count"]),
            input_tokens=int(bucket["in"]),
            output_tokens=int(bucket["out"]),
            total_tokens=int(bucket["in"] + bucket["out"]),
            total_cost=float(bucket["cost"]),
            average_latency_ms=avg(bucket["latencies"]),
        )
        for agent_id, bucket in by_agent.items()
    ]
    model_rows = [
        LangfuseModelStatistics(
            model=model,
            generation_count=int(bucket["count"]),
            input_tokens=int(bucket["in"]),
            output_tokens=int(bucket["out"]),
            total_tokens=int(bucket["in"] + bucket["out"]),
            total_cost=float(bucket["cost"]),
            average_latency_ms=avg(bucket["latencies"]),
        )
        for model, bucket in by_model.items()
    ]
    round_rows = [
        LangfuseRoundStatistics(
            round_index=round_index,
            phase=phase,
            generation_count=int(bucket["count"]),
            total_tokens=int(bucket["tokens"]),
            total_cost=float(bucket["cost"]),
            average_latency_ms=avg(bucket["latencies"]),
        )
        for (round_index, phase), bucket in by_round.items()
    ]

    agent_rows.sort(key=lambda row: row.total_tokens, reverse=True)
    model_rows.sort(key=lambda row: row.total_tokens, reverse=True)
    round_rows.sort(key=lambda row: (row.round_index, row.phase))

    return LangfuseStatisticsResponse(
        summary=LangfuseStatisticsSummary(
            trial_id=trial_id,
            trace_count=len(trace_ids),
            generation_count=len(observations),
            input_tokens=total_in,
            output_tokens=total_out,
            total_tokens=total_in + total_out,
            total_cost=total_cost,
            average_latency_ms=avg(latencies),
            slowest_agent_name=slowest_agent_name,
            slowest_model=slowest_model,
        ),
        agents=agent_rows,
        models=model_rows,
        rounds=round_rows,
        available=True,
        message=None,
    )


@router.get("/trials/{trial_id}/edges", response_model=list[EdgeStatistics])
async def trial_edges(trial_id: str, db: DBDep) -> list[EdgeStatistics]:
    await _require_trial(db, trial_id)

    # Prefer the name snapshotted on the connection; fall back to the live agent
    # row (legacy data) and finally to "Unknown" once the agent is gone. The
    # agent joins are OUTER so edges survive their agents being deleted.
    from_agent = agents.alias("from_agent")
    to_agent = agents.alias("to_agent")
    from_name = func.coalesce(connections.c.from_agent_name, from_agent.c.name, "Unknown").label(
        "from_agent_name"
    )
    to_name = func.coalesce(connections.c.to_agent_name, to_agent.c.name, "Unknown").label(
        "to_agent_name"
    )
    stmt = (
        select(
            connections.c.from_agent_id,
            from_name,
            connections.c.to_agent_id,
            to_name,
            func.count(messages.c.id).label("message_count"),
        )
        .select_from(
            connections.join(rounds, rounds.c.id == connections.c.round_id)
            .outerjoin(messages, messages.c.connection_id == connections.c.id)
            .outerjoin(from_agent, from_agent.c.id == connections.c.from_agent_id)
            .outerjoin(to_agent, to_agent.c.id == connections.c.to_agent_id)
        )
        .where(
            rounds.c.trial_id == trial_id,
            connections.c.from_agent_id.is_not(None),
            connections.c.to_agent_id.is_not(None),
            connections.c.from_agent_id != connections.c.to_agent_id,
        )
        .group_by(
            connections.c.from_agent_id,
            from_name,
            connections.c.to_agent_id,
            to_name,
        )
        .order_by(func.count(messages.c.id).desc())
    )
    rows = (await db.execute(stmt)).mappings().all()
    return [EdgeStatistics(**dict(row)) for row in rows]


@router.get("/trials/{trial_id}/timeline", response_model=list[RoundStatistics])
async def trial_timeline(trial_id: str, db: DBDep) -> list[RoundStatistics]:
    await _require_trial(db, trial_id)

    round_rows = (
        await db.execute(
            select(rounds.c.id, rounds.c.round_index, rounds.c.phase)
            .where(rounds.c.trial_id == trial_id)
            .order_by(rounds.c.round_index.asc(), rounds.c.id.asc())
        )
    ).all()

    msg_rows = (
        await db.execute(
            select(messages.c.round_id)
            .select_from(_MSG_ROUNDS)
            .where(rounds.c.trial_id == trial_id)
        )
    ).all()
    connection_rows = (
        await db.execute(
            select(
                connections.c.round_id,
                connections.c.from_agent_id,
                connections.c.to_agent_id,
            )
            .select_from(_CONN_ROUNDS)
            .where(rounds.c.trial_id == trial_id)
        )
    ).all()

    counts: Counter[int] = Counter()
    edges: defaultdict[int, set[tuple[str, str]]] = defaultdict(set)
    for (rid,) in msg_rows:
        counts[rid] += 1
    for rid, frm, to in connection_rows:
        if _is_agent_edge(frm, to):
            edges[rid].add((frm, to))

    return [
        RoundStatistics(
            round_id=rid,
            round_index=ridx,
            phase=phase,
            message_count=counts[rid],
            active_edge_count=len(edges[rid]),
        )
        for rid, ridx, phase in round_rows
    ]

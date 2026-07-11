"""Aggregated collaboration statistics endpoints."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import get_db
from server.db.tables import agents, connections, experiments, messages, rounds, trials
from server.llm import call_agent
from server.llm.credentials import resolve_api_key, use_credentials
from server.llm.embeddings import cosine, embed_texts
from server.market_hive.history import (
    SWARM_BOARD_ID,
    SWARM_BOARD_MESSAGE_TYPES,
    SWARM_BOARD_NAME,
)
from server.schemas import (
    AgentStatistics,
    ConsistencyReport,
    EdgeStatistics,
    ExperimentAgentStatistics,
    ExperimentEdgeStatistics,
    ExperimentLangfuseResponse,
    ExperimentLangfuseSummary,
    ExperimentListItem,
    ExperimentRoundStatistics,
    ExperimentSummary,
    LangfuseAgentStatistics,
    LangfuseModelStatistics,
    LangfuseRoundStatistics,
    LangfuseStatisticsResponse,
    LangfuseStatisticsSummary,
    PairwiseSimilarity,
    RoundStatistics,
    TrialStatisticsSummary,
)
from server.users import UserIdDep, scoped

router = APIRouter(prefix="/api/statistics", tags=["Statistics"])
logger = logging.getLogger(__name__)

DBDep = Annotated[AsyncConnection, Depends(get_db)]

_MSG_ROUNDS = messages.join(rounds, rounds.c.id == messages.c.round_id)
_CONN_ROUNDS = connections.join(rounds, rounds.c.id == connections.c.round_id)
_BIDDING_BOARD_ID = "__bidding_board__"
_BIDDING_BOARD_NAME = "Board"
_BIDDING_BOARD_MESSAGE_TYPES = ("bidding_bid", "bidding_match")

# Modes whose agents converse with a shared board rather than each other. The
# graph views synthesise agent→board edges from these message types, since
# board-directed messages carry no to_agent_id.
_BOARD_BY_MODE: dict[str, tuple[tuple[str, ...], str, str]] = {
    "bidding": (_BIDDING_BOARD_MESSAGE_TYPES, _BIDDING_BOARD_ID, _BIDDING_BOARD_NAME),
    "swarm": (SWARM_BOARD_MESSAGE_TYPES, SWARM_BOARD_ID, SWARM_BOARD_NAME),
}


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

    board = _BOARD_BY_MODE.get(str(trial["mode"]))
    if board is not None:
        board_types, board_id, _ = board
        board_rows = await db.execute(
            select(messages.c.from_agent_id)
            .select_from(_MSG_ROUNDS)
            .where(
                rounds.c.trial_id == trial_id,
                messages.c.from_agent_id.is_not(None),
                messages.c.message_type.in_(board_types),
            )
            .group_by(messages.c.from_agent_id)
        )
        for (agent_id,) in board_rows.all():
            edges.add((agent_id, board_id))

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


# Pad the observation-fetch time window so events whose start time falls slightly
# outside a trial's [created_at, completed_at] bounds (clock skew, flush lag) are
# still captured.
_LANGFUSE_WINDOW_BUFFER = timedelta(minutes=5)


def _parse_iso(value: Any) -> datetime | None:
    """Parse a stored ISO timestamp into an aware UTC datetime, tolerantly."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _observation_window(
    created_ats: Sequence[Any], completed_ats: Sequence[Any]
) -> tuple[datetime, datetime]:
    """Padded [from, to] bounds spanning the given trials' lifetimes.

    Any trial without a ``completed_at`` (still running, or missing) extends the
    upper bound to *now* so its in-flight generations are included.
    """
    now = datetime.now(UTC)
    starts = [ts for ts in (_parse_iso(v) for v in created_ats) if ts]
    ends = [ts for ts in (_parse_iso(v) for v in completed_ats) if ts]
    from_time = (min(starts) if starts else now - timedelta(days=1)) - _LANGFUSE_WINDOW_BUFFER
    to_candidates = list(ends)
    if len(ends) < len(completed_ats):
        to_candidates.append(now)
    to_time = (max(to_candidates) if to_candidates else now) + _LANGFUSE_WINDOW_BUFFER
    return from_time, to_time


def _sweep_observations(
    client: Any, from_time: datetime, to_time: datetime, wanted_trial_ids: set[str]
) -> list[Any]:
    """Paginate the observations endpoint over a time window, keeping only the
    GENERATIONs whose ``trial_id`` metadata is in ``wanted_trial_ids``.

    This deliberately avoids ``fetch_traces``: the ``/api/public/traces`` endpoint
    is aggressively rate-limited on Langfuse Cloud, and the old per-trace
    observation fan-out (one request per trace) tripped its limiter (HTTP 429).
    A single time-windowed sweep of ``/api/public/observations`` is the read path
    Langfuse recommends for high volume, and every generation already carries its
    ``trial_id`` in metadata (see ``server.llm.langfuse_setup``), so we filter
    client-side instead of issuing one request per trace.
    """
    observations: list[Any] = []
    page = 1
    while True:
        res = client.fetch_observations(
            type="GENERATION",
            from_start_time=from_time,
            to_start_time=to_time,
            page=page,
            limit=100,
        )
        for obs in res.data:
            if str(_metadata(obs).get("trial_id") or "") in wanted_trial_ids:
                observations.append(obs)
        if page >= res.meta.total_pages:
            break
        page += 1
    return observations


async def _fetch_langfuse_observations(trial: dict[str, Any]) -> tuple[list[Any], str | None]:
    """Fetch all Langfuse GENERATION observations belonging to a trial."""
    try:
        from langfuse import Langfuse

        client = Langfuse()
    except Exception as exc:
        return [], f"Langfuse client is not configured: {exc}"

    trial_id = str(trial["id"])
    from_time, to_time = _observation_window([trial.get("created_at")], [trial.get("completed_at")])

    def _fetch() -> tuple[list[Any], str | None]:
        return _sweep_observations(client, from_time, to_time, {trial_id}), None

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
    trial = await _require_trial(db, trial_id)

    observations, error = await _fetch_langfuse_observations(trial)
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
    trial = await _require_trial(db, trial_id)

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
    edge_stats = [EdgeStatistics(**dict(row)) for row in rows]

    board = _BOARD_BY_MODE.get(str(trial["mode"]))
    if board is not None:
        board_types, board_id, board_name = board
        board_from_name = func.coalesce(messages.c.from_agent_name, agents.c.name, "Unknown").label(
            "from_agent_name"
        )
        board_stmt = (
            select(
                messages.c.from_agent_id,
                board_from_name,
                func.count(messages.c.id).label("message_count"),
            )
            .select_from(_MSG_ROUNDS.outerjoin(agents, agents.c.id == messages.c.from_agent_id))
            .where(
                rounds.c.trial_id == trial_id,
                messages.c.from_agent_id.is_not(None),
                messages.c.message_type.in_(board_types),
            )
            .group_by(messages.c.from_agent_id, board_from_name)
            .order_by(func.count(messages.c.id).desc())
        )
        board_rows = (await db.execute(board_stmt)).mappings().all()
        edge_stats.extend(
            EdgeStatistics(
                from_agent_id=str(row["from_agent_id"]),
                from_agent_name=str(row["from_agent_name"]),
                to_agent_id=board_id,
                to_agent_name=board_name,
                message_count=int(row["message_count"]),
            )
            for row in board_rows
        )

    return edge_stats


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


# ---------------------------------------------------------------------------
# Experiment-scoped endpoints (averaged across all trials)
# ---------------------------------------------------------------------------


async def _require_experiment(db: AsyncConnection, exp_id: str) -> dict[str, object]:
    result = await db.execute(select(experiments).where(experiments.c.id == exp_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Experiment not found.")
    return dict(row)


async def _experiment_trial_ids(db: AsyncConnection, exp_id: str) -> list[str]:
    rows = await db.execute(
        select(trials.c.id).where(trials.c.experiment_id == exp_id).order_by(trials.c.created_at)
    )
    return [row.id for row in rows.all()]


def _avg(values: Sequence[float | int]) -> float:
    return sum(values) / len(values) if values else 0.0


@router.get("/experiments", response_model=list[ExperimentListItem])
async def list_experiments(db: DBDep, user_id: UserIdDep = None) -> list[ExperimentListItem]:
    stmt = (
        select(
            experiments.c.id,
            experiments.c.description,
            experiments.c.created_at,
            experiments.c.simulation_params,
            func.count(trials.c.id).label("trial_count"),
        )
        .select_from(experiments.outerjoin(trials, trials.c.experiment_id == experiments.c.id))
        .group_by(experiments.c.id)
        .order_by(experiments.c.created_at.desc())
    )
    rows = (await db.execute(scoped(stmt, experiments.c.user_id, user_id))).mappings().all()

    import json as _json

    result = []
    for row in rows:
        params = _json.loads(row["simulation_params"]) if row["simulation_params"] else {}
        result.append(
            ExperimentListItem(
                id=str(row["id"]),
                description=str(row["description"]),
                trial_count=int(row["trial_count"]),
                created_at=str(row["created_at"]),
                mode=params.get("mode"),
                user_prompt=params.get("prompt"),
            )
        )
    return result


@router.get("/experiments/{exp_id}/summary", response_model=ExperimentSummary)
async def experiment_summary(exp_id: str, db: DBDep) -> ExperimentSummary:
    import json as _json

    exp = await _require_experiment(db, exp_id)
    trial_ids = await _experiment_trial_ids(db, exp_id)
    params = _json.loads(str(exp["simulation_params"])) if exp["simulation_params"] else {}

    if not trial_ids:
        return ExperimentSummary(
            experiment_id=exp_id,
            description=str(exp["description"]),
            mode=params.get("mode"),
            user_prompt=params.get("prompt"),
            trial_count=0,
            trial_ids=[],
            avg_round_count=0.0,
            avg_agent_count=0.0,
            avg_total_messages=0.0,
            avg_total_edges=0.0,
            message_type_counts={},
        )

    round_counts: list[int] = []
    agent_counts: list[int] = []
    msg_counts: list[int] = []
    edge_counts: list[int] = []
    type_accum: Counter[str] = Counter()

    for tid in trial_ids:
        rc = await db.scalar(
            select(func.count()).select_from(rounds).where(rounds.c.trial_id == tid)
        )
        round_counts.append(int(rc or 0))

        mc = await db.scalar(
            select(func.count()).select_from(_MSG_ROUNDS).where(rounds.c.trial_id == tid)
        )
        msg_counts.append(int(mc or 0))

        type_rows = await db.execute(
            select(messages.c.message_type, func.count().label("n"))
            .select_from(_MSG_ROUNDS)
            .where(rounds.c.trial_id == tid)
            .group_by(messages.c.message_type)
        )
        for mrow in type_rows.all():
            type_accum[mrow.message_type] += mrow.n

        conn_rows = (
            await db.execute(
                select(connections.c.from_agent_id, connections.c.to_agent_id)
                .select_from(_CONN_ROUNDS)
                .where(rounds.c.trial_id == tid)
            )
        ).all()
        agent_ids: set[str] = set()
        edges: set[tuple[str, str]] = set()
        for frm, to in conn_rows:
            if frm is not None:
                agent_ids.add(frm)
            if to is not None:
                agent_ids.add(to)
            if _is_agent_edge(frm, to):
                edges.add((frm, to))
        trial_mode = await db.scalar(select(trials.c.mode).where(trials.c.id == tid))
        board = _BOARD_BY_MODE.get(str(trial_mode))
        if board is not None:
            board_types, board_id, _ = board
            board_rows = await db.execute(
                select(messages.c.from_agent_id)
                .select_from(_MSG_ROUNDS)
                .where(
                    rounds.c.trial_id == tid,
                    messages.c.from_agent_id.is_not(None),
                    messages.c.message_type.in_(board_types),
                )
                .group_by(messages.c.from_agent_id)
            )
            for (agent_id,) in board_rows.all():
                edges.add((agent_id, board_id))
        agent_counts.append(len(agent_ids))
        edge_counts.append(len(edges))

    n = len(trial_ids)
    avg_type_counts = {k: v / n for k, v in type_accum.items()}

    return ExperimentSummary(
        experiment_id=exp_id,
        description=str(exp["description"]),
        mode=params.get("mode"),
        user_prompt=params.get("prompt"),
        trial_count=n,
        trial_ids=trial_ids,
        avg_round_count=_avg(round_counts),
        avg_agent_count=_avg(agent_counts),
        avg_total_messages=_avg(msg_counts),
        avg_total_edges=_avg(edge_counts),
        message_type_counts=avg_type_counts,
    )


@router.get("/experiments/{exp_id}/agents", response_model=list[ExperimentAgentStatistics])
async def experiment_agents(exp_id: str, db: DBDep) -> list[ExperimentAgentStatistics]:
    await _require_experiment(db, exp_id)
    trial_ids = await _experiment_trial_ids(db, exp_id)

    if not trial_ids:
        return []

    sent_acc: defaultdict[str, list[int]] = defaultdict(list)
    recv_acc: defaultdict[str, list[int]] = defaultdict(list)
    out_acc: defaultdict[str, list[int]] = defaultdict(list)
    in_acc: defaultdict[str, list[int]] = defaultdict(list)
    tool_acc: defaultdict[str, list[int]] = defaultdict(list)
    names: dict[str, str] = {}
    all_agents: set[str] = set()

    for tid in trial_ids:
        message_rows = (
            await db.execute(
                select(messages.c.from_agent_id, messages.c.to_agent_id, messages.c.message_type)
                .select_from(_MSG_ROUNDS)
                .where(rounds.c.trial_id == tid)
            )
        ).all()
        connection_rows = (
            await db.execute(
                select(connections.c.from_agent_id, connections.c.to_agent_id)
                .select_from(_CONN_ROUNDS)
                .where(rounds.c.trial_id == tid)
            )
        ).all()

        sent: Counter[str] = Counter()
        received: Counter[str] = Counter()
        tools: Counter[str] = Counter()
        out_targets: defaultdict[str, set[str]] = defaultdict(set)
        in_sources: defaultdict[str, set[str]] = defaultdict(set)
        involved: set[str] = set()

        for frm, to in connection_rows:
            if frm is not None:
                involved.add(frm)
            if to is not None:
                involved.add(to)
            if _is_agent_edge(frm, to):
                out_targets[frm].add(to)
                in_sources[to].add(frm)

        for frm, to, mtype in message_rows:
            if frm is not None:
                sent[frm] += 1
                involved.add(frm)
                if mtype == "tool":
                    tools[frm] += 1
            if to is not None:
                received[to] += 1
                involved.add(to)

        all_agents |= involved
        trial_names = await _agent_names(db, involved)
        names.update(trial_names)

        for aid in involved:
            sent_acc[aid].append(sent[aid])
            recv_acc[aid].append(received[aid])
            out_acc[aid].append(len(out_targets[aid]))
            in_acc[aid].append(len(in_sources[aid]))
            tool_acc[aid].append(tools[aid])

    return sorted(
        [
            ExperimentAgentStatistics(
                agent_id=aid,
                agent_name=names.get(aid, "Unknown"),
                avg_messages_sent=_avg(sent_acc[aid]),
                avg_messages_received=_avg(recv_acc[aid]),
                avg_out_degree=_avg(out_acc[aid]),
                avg_in_degree=_avg(in_acc[aid]),
                avg_tool_invocations=_avg(tool_acc[aid]),
            )
            for aid in all_agents
        ],
        key=lambda r: r.avg_messages_sent + r.avg_messages_received,
        reverse=True,
    )


@router.get("/experiments/{exp_id}/edges", response_model=list[ExperimentEdgeStatistics])
async def experiment_edges(exp_id: str, db: DBDep) -> list[ExperimentEdgeStatistics]:
    await _require_experiment(db, exp_id)
    trial_ids = await _experiment_trial_ids(db, exp_id)

    if not trial_ids:
        return []

    edge_counts: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
    edge_names: dict[tuple[str, str], tuple[str, str]] = {}

    for tid in trial_ids:
        from_agent = agents.alias("from_agent")
        to_agent = agents.alias("to_agent")
        from_name = func.coalesce(
            connections.c.from_agent_name, from_agent.c.name, "Unknown"
        ).label("from_agent_name")
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
                rounds.c.trial_id == tid,
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
        )
        rows = (await db.execute(stmt)).mappings().all()
        for row in rows:
            key = (str(row["from_agent_id"]), str(row["to_agent_id"]))
            edge_counts[key].append(int(row["message_count"]))
            edge_names[key] = (str(row["from_agent_name"]), str(row["to_agent_name"]))

        trial_mode = await db.scalar(select(trials.c.mode).where(trials.c.id == tid))
        board = _BOARD_BY_MODE.get(str(trial_mode))
        if board is not None:
            board_types, board_id, board_name = board
            board_from_name = func.coalesce(
                messages.c.from_agent_name, agents.c.name, "Unknown"
            ).label("from_agent_name")
            board_stmt = (
                select(
                    messages.c.from_agent_id,
                    board_from_name,
                    func.count(messages.c.id).label("message_count"),
                )
                .select_from(_MSG_ROUNDS.outerjoin(agents, agents.c.id == messages.c.from_agent_id))
                .where(
                    rounds.c.trial_id == tid,
                    messages.c.from_agent_id.is_not(None),
                    messages.c.message_type.in_(board_types),
                )
                .group_by(messages.c.from_agent_id, board_from_name)
            )
            board_rows = (await db.execute(board_stmt)).mappings().all()
            for row in board_rows:
                key = (str(row["from_agent_id"]), board_id)
                edge_counts[key].append(int(row["message_count"]))
                edge_names[key] = (str(row["from_agent_name"]), board_name)

    return sorted(
        [
            ExperimentEdgeStatistics(
                from_agent_id=frm,
                from_agent_name=edge_names[(frm, to)][0],
                to_agent_id=to,
                to_agent_name=edge_names[(frm, to)][1],
                avg_message_count=_avg(counts),
            )
            for (frm, to), counts in edge_counts.items()
        ],
        key=lambda r: r.avg_message_count,
        reverse=True,
    )


@router.get("/experiments/{exp_id}/timeline", response_model=list[ExperimentRoundStatistics])
async def experiment_timeline(exp_id: str, db: DBDep) -> list[ExperimentRoundStatistics]:
    await _require_experiment(db, exp_id)
    trial_ids = await _experiment_trial_ids(db, exp_id)

    if not trial_ids:
        return []

    msg_acc: defaultdict[tuple[int, str], list[int]] = defaultdict(list)
    edge_acc: defaultdict[tuple[int, str], list[int]] = defaultdict(list)

    for tid in trial_ids:
        round_rows = (
            await db.execute(
                select(rounds.c.id, rounds.c.round_index, rounds.c.phase)
                .where(rounds.c.trial_id == tid)
                .order_by(rounds.c.round_index.asc(), rounds.c.id.asc())
            )
        ).all()

        msg_rows = (
            await db.execute(
                select(messages.c.round_id).select_from(_MSG_ROUNDS).where(rounds.c.trial_id == tid)
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
                .where(rounds.c.trial_id == tid)
            )
        ).all()

        counts: Counter[int] = Counter()
        t_edges: defaultdict[int, set[tuple[str, str]]] = defaultdict(set)
        for (rid,) in msg_rows:
            counts[rid] += 1
        for rid, frm, to in connection_rows:
            if _is_agent_edge(frm, to):
                t_edges[rid].add((frm, to))

        for rid, ridx, phase in round_rows:
            key = (ridx, phase)
            msg_acc[key].append(counts[rid])
            edge_acc[key].append(len(t_edges[rid]))

    return sorted(
        [
            ExperimentRoundStatistics(
                round_index=ridx,
                phase=phase,
                avg_message_count=_avg(msg_acc[(ridx, phase)]),
                avg_active_edge_count=_avg(edge_acc[(ridx, phase)]),
            )
            for ridx, phase in msg_acc
        ],
        key=lambda r: (r.round_index, r.phase),
    )


async def _fetch_langfuse_observations_multi(
    trials: list[dict[str, Any]],
) -> tuple[list[Any], str | None]:
    """Fetch Langfuse GENERATION observations for multiple trials in one sweep."""
    try:
        from langfuse import Langfuse

        client = Langfuse()
    except Exception as exc:
        return [], f"Langfuse client is not configured: {exc}"

    wanted = {str(t["id"]) for t in trials}
    from_time, to_time = _observation_window(
        [t.get("created_at") for t in trials],
        [t.get("completed_at") for t in trials],
    )

    def _fetch() -> tuple[list[Any], str | None]:
        return _sweep_observations(client, from_time, to_time, wanted), None

    try:
        return await asyncio.to_thread(_fetch)
    except Exception as exc:
        return [], f"Langfuse request failed: {exc}"


@router.get("/experiments/{exp_id}/langfuse", response_model=ExperimentLangfuseResponse)
async def experiment_langfuse(exp_id: str, db: DBDep) -> ExperimentLangfuseResponse:
    rows = await db.execute(
        select(trials.c.id, trials.c.created_at, trials.c.completed_at)
        .where(trials.c.experiment_id == exp_id)
        .order_by(trials.c.created_at)
    )
    trial_rows = [dict(row) for row in rows.mappings().all()]
    trial_ids = [str(row["id"]) for row in trial_rows]

    def _empty(msg: str | None) -> ExperimentLangfuseResponse:
        return ExperimentLangfuseResponse(
            summary=ExperimentLangfuseSummary(
                experiment_id=exp_id,
                trial_count=len(trial_ids),
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
            message=msg,
        )

    if not trial_ids:
        return _empty("No trials in this experiment yet.")

    observations, error = await _fetch_langfuse_observations_multi(trial_rows)
    if error:
        return _empty(error)
    if not observations:
        return _empty("No Langfuse generations found for this experiment.")

    by_agent: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_round: dict[tuple[int, str], dict[str, Any]] = {}
    total_in = total_out = 0
    total_cost = 0.0
    latencies: list[float] = []
    slowest_latency = -1.0
    slowest_agent_name: str | None = None
    slowest_model: str | None = None
    trace_ids: set[str] = set()

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
        trace_ids.add(getattr(obs, "trace_id", ""))

        agent_id = str(md.get("agent_id") or "unknown")
        agent_name = str(md.get("agent_name") or "Unknown")
        ab = by_agent.setdefault(
            agent_id,
            {"agent_name": agent_name, "count": 0, "in": 0, "out": 0, "cost": 0.0, "latencies": []},
        )
        ab["count"] += 1
        ab["in"] += in_tokens
        ab["out"] += out_tokens
        ab["cost"] += cost
        if latency:
            ab["latencies"].append(latency)

        model = str(getattr(obs, "model", None) or md.get("model") or "unknown")
        mb = by_model.setdefault(
            model,
            {"count": 0, "in": 0, "out": 0, "cost": 0.0, "latencies": []},
        )
        mb["count"] += 1
        mb["in"] += in_tokens
        mb["out"] += out_tokens
        mb["cost"] += cost
        if latency:
            mb["latencies"].append(latency)

        round_index = int(md.get("round_index") or 0)
        phase = str(md.get("phase") or "unknown")
        rb = by_round.setdefault(
            (round_index, phase),
            {"count": 0, "tokens": 0, "cost": 0.0, "latencies": []},
        )
        rb["count"] += 1
        rb["tokens"] += tokens
        rb["cost"] += cost
        if latency:
            rb["latencies"].append(latency)

        if latency > slowest_latency:
            slowest_latency = latency
            slowest_agent_name = agent_name
            slowest_model = model

    def avg(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    agent_rows = sorted(
        [
            LangfuseAgentStatistics(
                agent_id=aid,
                agent_name=str(b["agent_name"]),
                generation_count=int(b["count"]),
                input_tokens=int(b["in"]),
                output_tokens=int(b["out"]),
                total_tokens=int(b["in"] + b["out"]),
                total_cost=float(b["cost"]),
                average_latency_ms=avg(b["latencies"]),
            )
            for aid, b in by_agent.items()
        ],
        key=lambda r: r.total_tokens,
        reverse=True,
    )
    model_rows = sorted(
        [
            LangfuseModelStatistics(
                model=model,
                generation_count=int(b["count"]),
                input_tokens=int(b["in"]),
                output_tokens=int(b["out"]),
                total_tokens=int(b["in"] + b["out"]),
                total_cost=float(b["cost"]),
                average_latency_ms=avg(b["latencies"]),
            )
            for model, b in by_model.items()
        ],
        key=lambda r: r.total_tokens,
        reverse=True,
    )
    round_rows = sorted(
        [
            LangfuseRoundStatistics(
                round_index=ri,
                phase=ph,
                generation_count=int(b["count"]),
                total_tokens=int(b["tokens"]),
                total_cost=float(b["cost"]),
                average_latency_ms=avg(b["latencies"]),
            )
            for (ri, ph), b in by_round.items()
        ],
        key=lambda r: (r.round_index, r.phase),
    )

    return ExperimentLangfuseResponse(
        summary=ExperimentLangfuseSummary(
            experiment_id=exp_id,
            trial_count=len(trial_ids),
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


# ---------------------------------------------------------------------------
# Consistency (cross-trial answer similarity)
# ---------------------------------------------------------------------------

_ANSWER_PRIORITY = (
    "swarm_final",
    "consensus",
    "bidding_final_output",
    "broadcast_no_consensus_outputs",
    "agent_output",
)


async def _extract_trial_answer(db: AsyncConnection, trial_id: str) -> str | None:
    """Return the concatenated final-answer messages for a trial."""
    max_round_idx = await db.scalar(
        select(func.max(rounds.c.round_index)).where(rounds.c.trial_id == trial_id)
    )
    if max_round_idx is None:
        return None

    for mtype in _ANSWER_PRIORITY:
        rows = (
            await db.execute(
                select(messages.c.message)
                .select_from(_MSG_ROUNDS)
                .where(
                    rounds.c.trial_id == trial_id,
                    rounds.c.round_index == max_round_idx,
                    messages.c.message_type == mtype,
                    messages.c.message.is_not(None),
                )
                .order_by(messages.c.id.asc())
            )
        ).all()
        if rows:
            return "\n\n".join(r.message for r in rows if r.message)
    return None


def _pick_provider_model() -> tuple[str, str] | None:
    """Return the first configured (provider, model) pair for the AI summary."""
    candidates = [
        ("anthropic", "claude-haiku-4-5-20251001"),
        ("openai", "gpt-4.1-nano"),
        ("groq", "llama-3.3-70b-versatile"),
        ("gemini", "gemini-2.0-flash"),
    ]
    for provider, model in candidates:
        try:
            resolve_api_key(provider)
            return provider, model
        except Exception:
            logger.debug("Provider %s unavailable: no API key configured", provider)
            continue
    return None


@router.get(
    "/experiments/{exp_id}/consistency",
    response_model=ConsistencyReport,
    dependencies=[Depends(use_credentials)],
)
async def experiment_consistency(exp_id: str, db: DBDep) -> ConsistencyReport:
    await _require_experiment(db, exp_id)
    trial_ids = await _experiment_trial_ids(db, exp_id)

    answers: list[tuple[str, str]] = []
    for tid in trial_ids:
        text = await _extract_trial_answer(db, tid)
        if text:
            answers.append((tid, text))

    n = len(trial_ids)
    na = len(answers)

    if na < 2:
        msg = (
            "Need at least 2 completed trials to compute consistency."
            if n < 2
            else "Not enough trials with extractable answers yet."
        )
        return ConsistencyReport(
            experiment_id=exp_id,
            trial_count=n,
            trials_with_answers=na,
            avg_cosine_similarity=None,
            pairwise_scores=[],
            ai_summary=None,
            available=False,
            message=msg,
        )

    answer_texts = [t for _, t in answers]
    answer_ids = [tid for tid, _ in answers]

    # Semantic embeddings + pairwise cosine similarities
    avg_cos: float | None = None
    pairs: list[PairwiseSimilarity] = []
    embeddings = await embed_texts(answer_texts)
    if embeddings and len(embeddings) == len(answer_texts):
        scores: list[float] = []
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                sim = cosine(embeddings[i], embeddings[j])
                pairs.append(
                    PairwiseSimilarity(
                        trial_id_a=answer_ids[i],
                        trial_id_b=answer_ids[j],
                        cosine_similarity=round(sim, 4),
                    )
                )
                scores.append(sim)
        avg_cos = round(sum(scores) / len(scores), 4) if scores else None

    # AI-generated consistency summary
    ai_summary: str | None = None
    pm = _pick_provider_model()
    if pm:
        provider, model = pm
        answers_block = "\n\n".join(
            f"Answer {i + 1} (trial {tid}):\n{txt}" for i, (tid, txt) in enumerate(answers)
        )
        summary_prompt = (
            f"Below are {na} answers to the same question, each from an independent "
            f"run of a multi-agent system.\n\n"
            f"{answers_block}\n\n"
            "Briefly assess (3-5 sentences) how consistent these answers are with each "
            "other. Note key points of agreement, any meaningful divergences, and whether "
            "the system appears reliable for this question."
        )
        try:
            ai_summary, _ = await call_agent(summary_prompt, provider, model)
        except Exception:
            ai_summary = None

    return ConsistencyReport(
        experiment_id=exp_id,
        trial_count=n,
        trials_with_answers=na,
        avg_cosine_similarity=avg_cos,
        pairwise_scores=pairs,
        ai_summary=ai_summary,
        available=True,
        message=None,
    )

"""Read-only endpoints for inspecting simulation history."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import (
    deserialise_connection_row,
    deserialise_round_row,
    deserialise_trial_row,
    get_db,
)
from server.db.tables import agents, connections, messages, rounds, trials
from server.schemas import (
    ConnectionResponse,
    MessageTraceResponse,
    RoundResponse,
    TrialResponse,
)

router = APIRouter(prefix="/api/history", tags=["History"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]


@router.get("/trials", response_model=list[TrialResponse])
async def list_trials(db: DBDep) -> list[TrialResponse]:
    result = await db.execute(
        select(trials).order_by(trials.c.created_at.desc(), trials.c.id.desc())
    )
    return [TrialResponse(**deserialise_trial_row(row)) for row in result.mappings().all()]


@router.get("/trials/{trial_id}", response_model=TrialResponse)
async def get_trial(trial_id: str, db: DBDep) -> TrialResponse:
    result = await db.execute(select(trials).where(trials.c.id == trial_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trial not found.")
    return TrialResponse(**deserialise_trial_row(row))


@router.get("/trials/{trial_id}/rounds", response_model=list[RoundResponse])
async def list_rounds(trial_id: str, db: DBDep) -> list[RoundResponse]:
    result = await db.execute(
        select(rounds)
        .where(rounds.c.trial_id == trial_id)
        .order_by(rounds.c.round_index.asc(), rounds.c.id.asc())
    )
    return [RoundResponse(**deserialise_round_row(row)) for row in result.mappings().all()]


@router.get("/rounds/{round_id}/connections", response_model=list[ConnectionResponse])
async def list_connections(round_id: int, db: DBDep) -> list[ConnectionResponse]:
    result = await db.execute(
        select(connections)
        .where(connections.c.round_id == round_id)
        .order_by(connections.c.id.asc())
    )
    return [
        ConnectionResponse(**deserialise_connection_row(row)) for row in result.mappings().all()
    ]


_VALID_MESSAGE_TYPES: frozenset[str] = frozenset(
    {
        "agent_input",
        "agent_output",
        "tool",
        "system",
        "broadcast",
        "consensus",
        "guardrail_blocked",
    }
)

_DEFAULT_MESSAGES_LIMIT = 500
_MAX_MESSAGES_LIMIT = 2000


@router.get("/messages", response_model=list[MessageTraceResponse])
async def list_messages(
    db: DBDep,
    trial_id: str | None = None,
    round_id: int | None = None,
    agent_id: str | None = None,
    message_type: str | None = None,
    after_id: int | None = None,
    limit: int = Query(default=_DEFAULT_MESSAGES_LIMIT, ge=1, le=_MAX_MESSAGES_LIMIT),
) -> list[MessageTraceResponse]:
    if message_type is not None and message_type not in _VALID_MESSAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid message_type '{message_type}'. "
                f"Allowed values: {sorted(_VALID_MESSAGE_TYPES)}"
            ),
        )
    from_agent = agents.alias("from_agent")
    to_agent = agents.alias("to_agent")

    stmt = (
        select(
            messages.c.id,
            trials.c.id.label("trial_id"),
            trials.c.description.label("trial_description"),
            rounds.c.id.label("round_id"),
            rounds.c.round_index,
            rounds.c.phase,
            messages.c.connection_id,
            messages.c.from_agent_id,
            from_agent.c.name.label("from_agent_name"),
            messages.c.to_agent_id,
            to_agent.c.name.label("to_agent_name"),
            messages.c.message_type,
            messages.c.message,
            messages.c.created_at,
        )
        .select_from(
            messages.join(rounds, rounds.c.id == messages.c.round_id)
            .join(trials, trials.c.id == rounds.c.trial_id)
            .outerjoin(from_agent, from_agent.c.id == messages.c.from_agent_id)
            .outerjoin(to_agent, to_agent.c.id == messages.c.to_agent_id)
        )
        .order_by(trials.c.created_at.desc(), rounds.c.round_index.asc(), messages.c.id.asc())
    )

    if trial_id is not None:
        stmt = stmt.where(trials.c.id == trial_id)
    if round_id is not None:
        stmt = stmt.where(rounds.c.id == round_id)
    if agent_id is not None:
        stmt = stmt.where(
            (messages.c.from_agent_id == agent_id) | (messages.c.to_agent_id == agent_id)
        )
    if message_type is not None:
        stmt = stmt.where(messages.c.message_type == message_type)
    if after_id is not None:
        stmt = stmt.where(messages.c.id > after_id)

    stmt = stmt.limit(limit)

    result = await db.execute(stmt)
    rows = result.mappings().all()
    return [
        MessageTraceResponse(
            **{
                **dict(row),
                "from_agent_name": row["from_agent_name"] or "SYSTEM",
                "to_agent_name": row["to_agent_name"] or "SYSTEM",
            }
        )
        for row in rows
    ]

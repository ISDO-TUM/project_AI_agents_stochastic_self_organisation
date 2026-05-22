"""Read-only endpoints for inspecting simulation history."""

from __future__ import annotations

from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from api.db import (
    deserialise_connection_row,
    deserialise_round_row,
    deserialise_trial_row,
    get_db,
)
from api.schemas import (
    ConnectionResponse,
    MessageTraceResponse,
    RoundResponse,
    TrialResponse,
)

router = APIRouter(prefix="/api/history", tags=["History"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]


@router.get("/trials", response_model=list[TrialResponse])
async def list_trials(db: DBDep) -> list[TrialResponse]:
    async with db.execute(
        """
        SELECT *
          FROM trials
         ORDER BY created_at DESC, id DESC
        """
    ) as cur:
        rows = await cur.fetchall()
    return [TrialResponse(**deserialise_trial_row(row)) for row in rows]


@router.get("/trials/{trial_id}", response_model=TrialResponse)
async def get_trial(trial_id: str, db: DBDep) -> TrialResponse:
    async with db.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trial not found.")
    return TrialResponse(**deserialise_trial_row(row))


@router.get("/trials/{trial_id}/rounds", response_model=list[RoundResponse])
async def list_rounds(trial_id: str, db: DBDep) -> list[RoundResponse]:
    async with db.execute(
        """
        SELECT *
          FROM rounds
         WHERE trial_id = ?
         ORDER BY round_index ASC, id ASC
        """,
        (trial_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [RoundResponse(**deserialise_round_row(row)) for row in rows]


@router.get("/rounds/{round_id}/connections", response_model=list[ConnectionResponse])
async def list_connections(round_id: int, db: DBDep) -> list[ConnectionResponse]:
    async with db.execute(
        """
        SELECT *
          FROM connections
         WHERE round_id = ?
         ORDER BY id ASC
        """,
        (round_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [ConnectionResponse(**deserialise_connection_row(row)) for row in rows]


@router.get("/messages", response_model=list[MessageTraceResponse])
async def list_messages(
    db: DBDep,
    trial_id: str | None = None,
    round_id: int | None = None,
    agent_id: str | None = None,
    message_type: str | None = None,
    after_id: int | None = None,
) -> list[MessageTraceResponse]:
    async with db.execute(
        """
        SELECT
            m.id,
            t.id AS trial_id,
            t.description AS trial_description,
            r.id AS round_id,
            r.round_index,
            r.phase,
            m.connection_id,
            m.from_agent_id,
            COALESCE(from_agent.name, 'SYSTEM') AS from_agent_name,
            m.to_agent_id,
            to_agent.name AS to_agent_name,
            m.message_type,
            m.message,
            m.created_at
          FROM messages m
          JOIN rounds r ON r.id = m.round_id
          JOIN trials t ON t.id = r.trial_id
          LEFT JOIN agents from_agent ON from_agent.id = m.from_agent_id
          JOIN agents to_agent ON to_agent.id = m.to_agent_id
         WHERE (? IS NULL OR t.id = ?)
           AND (? IS NULL OR r.id = ?)
           AND (? IS NULL OR m.from_agent_id = ? OR m.to_agent_id = ?)
           AND (? IS NULL OR m.message_type = ?)
           AND (? IS NULL OR m.id > ?)
         ORDER BY t.created_at DESC, r.round_index ASC, m.id ASC
        """,
        (
            trial_id,
            trial_id,
            round_id,
            round_id,
            agent_id,
            agent_id,
            agent_id,
            message_type,
            message_type,
            after_id,
            after_id,
        ),
    ) as cur:
        rows = await cur.fetchall()
    return [MessageTraceResponse(**dict(row)) for row in rows]

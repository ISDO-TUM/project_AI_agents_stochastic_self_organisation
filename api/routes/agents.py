"""Agent CRUD routes, mounted at ``/api/agents``."""

from __future__ import annotations

import json
import uuid
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from api.db import deserialise_agent_row, get_db
from api.schemas import AgentCreate, AgentResponse, AgentUpdate

router = APIRouter(prefix="/api/agents", tags=["Agents"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]
_PATCHABLE_COLUMNS: frozenset[str] = frozenset(AgentUpdate.model_fields.keys())


@router.post(
    "/",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
    description="Persist a new agent and return it with its generated UUID.",
)
async def create_agent(body: AgentCreate, db: DBDep) -> AgentResponse:
    agent_id = str(uuid.uuid4())
    await db.execute(
        """
        INSERT INTO agents
            (id, name, description, system_prompt, provider, model, tools, connections)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            agent_id,
            body.name,
            body.description,
            body.system_prompt,
            body.provider,
            body.model,
            json.dumps(body.tools),
            json.dumps(body.connections),
        ),
    )
    await db.commit()
    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.get(
    "/",
    response_model=list[AgentResponse],
    summary="List all agents",
)
async def list_agents(db: DBDep) -> list[AgentResponse]:
    async with db.execute("SELECT * FROM agents") as cur:
        rows = await cur.fetchall()
    return [AgentResponse(**deserialise_agent_row(row)) for row in rows]


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get an agent by ID",
)
async def get_agent(agent_id: str, db: DBDep) -> AgentResponse:
    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Replace an agent",
    description="Fully replace all fields of an existing agent.",
)
async def replace_agent(agent_id: str, body: AgentCreate, db: DBDep) -> AgentResponse:
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute(
        """
        UPDATE agents
           SET name = ?, description = ?, system_prompt = ?,
               provider = ?, model = ?, tools = ?, connections = ?
         WHERE id = ?
        """,
        (
            body.name,
            body.description,
            body.system_prompt,
            body.provider,
            body.model,
            json.dumps(body.tools),
            json.dumps(body.connections),
            agent_id,
        ),
    )
    await db.commit()
    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Partially update an agent",
    description="Update only the supplied fields; all other fields remain unchanged.",
)
async def update_agent(agent_id: str, body: AgentUpdate, db: DBDep) -> AgentResponse:
    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    updates: dict[str, str] = {
        field: json.dumps(value) if isinstance(value, list) else value
        for field, value in body.model_dump(exclude_none=True).items()
        if field in _PATCHABLE_COLUMNS
    }

    if updates:
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        await db.execute(
            f"UPDATE agents SET {set_clause} WHERE id = ?",  # noqa: S608
            [*updates.values(), agent_id],
        )
        await db.commit()

    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(agent_id: str, db: DBDep) -> None:
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()

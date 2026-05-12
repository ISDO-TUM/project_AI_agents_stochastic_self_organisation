"""Agent CRUD routes, mounted at ``/api/agents``."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from api.db import (
    deserialise_agent_row,
    deserialise_knowledge_file_row,
    get_db,
    hint_files_in_prompt,
    load_agent_file_names,
)
from api.llm import call_agent
from api.schemas import (
    AgentCreate,
    AgentResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentUpdate,
    KnowledgeFileResponse,
)

logger = logging.getLogger(__name__)

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
    """Create a new agent and persist it to the database.

    Honours an optional caller-supplied ``id`` so canvas imports can preserve
    cross-references (returns 409 on collision). Otherwise generates a UUID.

    Args:
        body: Agent creation payload.
        db: Shared database connection injected by FastAPI.

    Returns:
        The newly created agent including its UUID.
    """
    agent_id = body.id or str(uuid.uuid4())
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Agent with this id already exists.",
            )
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
    """Return all agents in the database.

    Args:
        db: Shared database connection injected by FastAPI.

    Returns:
        A list of all agents, possibly empty.
    """
    async with db.execute("SELECT * FROM agents") as cur:
        rows = await cur.fetchall()
    return [AgentResponse(**deserialise_agent_row(row)) for row in rows]


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get an agent by ID",
)
async def get_agent(agent_id: str, db: DBDep) -> AgentResponse:
    """Fetch a single agent by its UUID.

    Args:
        agent_id: UUID of the agent.
        db: Shared database connection injected by FastAPI.

    Returns:
        The requested agent.

    Raises:
        HTTPException: 404 if no agent with the given ID exists.
    """
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
    """Fully replace all fields of an existing agent.

    Args:
        agent_id: UUID of the agent to replace.
        body: New agent payload; all fields are required.
        db: Shared database connection injected by FastAPI.

    Returns:
        The updated agent.

    Raises:
        HTTPException: 404 if no agent with the given ID exists.
    """
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
    """Partially update an agent; only supplied fields are written.

    Args:
        agent_id: UUID of the agent to update.
        body: Partial update payload; omitted fields are left unchanged.
        db: Shared database connection injected by FastAPI.

    Returns:
        The updated agent.

    Raises:
        HTTPException: 404 if no agent with the given ID exists.
    """
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
    "/",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete all agents, knowledge files, and simulation history",
)
async def delete_all(db: DBDep) -> None:
    """Wipe every agent, knowledge file, and simulation record from the database.

    Deletion order respects foreign-key constraints:
    messages → connections → rounds → trials → agents (cascades agent_files) → knowledge_files.
    """
    for table in ("messages", "connections", "rounds", "trials", "agents", "knowledge_files"):
        await db.execute(f"DELETE FROM {table}")  # noqa: S608
    await db.commit()


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(agent_id: str, db: DBDep) -> None:
    """Delete an agent from the database.

    Args:
        agent_id: UUID of the agent to delete.
        db: Shared database connection injected by FastAPI.

    Raises:
        HTTPException: 404 if no agent with the given ID exists.
    """
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
    await db.commit()


@router.post(
    "/{agent_id}/run",
    response_model=AgentRunResponse,
    summary="Run an agent",
    description=(
        "Send a prompt to an existing agent. The agent's configured system prompt, "
        "provider, model, and tools are loaded from the database and forwarded to "
        "the LLM.  The final text response is returned."
    ),
)
async def run_agent(agent_id: str, body: AgentRunRequest, db: DBDep) -> AgentRunResponse:
    async with db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    agent = deserialise_agent_row(row)

    tool_names: list[str] = agent["tools"] or []
    file_names = await load_agent_file_names(db, agent_id)
    system_prompt = hint_files_in_prompt(agent["system_prompt"] or None, file_names)

    try:
        response, tools_used = await call_agent(
            body.prompt,
            provider=agent["provider"],
            model=agent["model"],
            system_prompt=system_prompt,
            tool_names=tool_names or None,
            tool_context={"db": db, "agent_id": agent_id},
        )
    except Exception as exc:
        logger.exception("Agent run failed for agent_id=%s", agent_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider error. Check server logs for details.",
        ) from exc

    return AgentRunResponse(agent_id=agent_id, response=response, tools_used=tools_used)


@router.get(
    "/{agent_id}/files",
    response_model=list[KnowledgeFileResponse],
    summary="List files attached to an agent",
)
async def list_agent_files(agent_id: str, db: DBDep) -> list[KnowledgeFileResponse]:
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    async with db.execute(
        """
        SELECT kf.* FROM knowledge_files kf
        JOIN agent_files af ON af.file_id = kf.id
        WHERE af.agent_id = ?
        """,
        (agent_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [KnowledgeFileResponse(**deserialise_knowledge_file_row(row)) for row in rows]


@router.post(
    "/{agent_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a file to an agent",
)
async def attach_file_to_agent(agent_id: str, file_id: str, db: DBDep) -> None:
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    async with db.execute("SELECT id FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
            )
    await db.execute(
        "INSERT OR IGNORE INTO agent_files (agent_id, file_id) VALUES (?, ?)",
        (agent_id, file_id),
    )
    await db.commit()


@router.delete(
    "/{agent_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a file from an agent",
)
async def detach_file_from_agent(agent_id: str, file_id: str, db: DBDep) -> None:
    async with db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute(
        "DELETE FROM agent_files WHERE agent_id = ? AND file_id = ?",
        (agent_id, file_id),
    )
    await db.commit()

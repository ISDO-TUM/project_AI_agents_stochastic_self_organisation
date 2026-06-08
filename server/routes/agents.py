"""Agent CRUD routes, mounted at ``/api/agents``."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import (
    deserialise_agent_row,
    deserialise_knowledge_file_row,
    get_db,
    hint_files_in_prompt,
    load_agent_files,
)
from server.db.tables import (
    agent_files,
    agents,
    knowledge_files,
    trials,
)
from server.guardrails import sanitize_prompt, validate_llm_output
from server.guardrails.input_sanitizer import PromptInjectionError
from server.guardrails.output_validator import InjectionEchoError, LLMRefusalError
from server.llm import call_agent
from server.llm.credentials import MissingCredentialsError, use_credentials
from server.owner import OwnerDep, owner_match
from server.schemas import (
    AgentCreate,
    AgentResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentUpdate,
    KnowledgeFileResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["Agents"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]
_PATCHABLE_COLUMNS: frozenset[str] = frozenset(AgentUpdate.model_fields.keys())


@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new agent",
    description="Persist a new agent and return it with its generated UUID.",
)
async def create_agent(body: AgentCreate, db: DBDep, owner: OwnerDep) -> AgentResponse:
    """Create a new agent and persist it to the database.

    Honours an optional caller-supplied ``id`` so canvas imports can preserve
    cross-references (returns 409 on collision). Otherwise generates a UUID.

    Args:
        body: Agent creation payload.
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Returns:
        The newly created agent including its UUID.
    """
    agent_id = body.id or str(uuid.uuid4())
    # The id is the global primary key, so the collision check stays unscoped.
    existing = await db.execute(select(agents.c.id).where(agents.c.id == agent_id))
    if existing.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent with this id already exists.",
        )
    await db.execute(
        insert(agents).values(
            id=agent_id,
            owner_id=owner,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            provider=body.provider,
            model=body.model,
            tools=json.dumps(body.tools),
            connections=json.dumps(body.connections),
        )
    )
    await db.commit()
    result = await db.execute(select(agents).where(agents.c.id == agent_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.get(
    "",
    response_model=list[AgentResponse],
    summary="List all agents",
)
async def list_agents(db: DBDep, owner: OwnerDep) -> list[AgentResponse]:
    """Return the current owner's agents.

    Args:
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Returns:
        A list of the owner's agents, possibly empty.
    """
    result = await db.execute(select(agents).where(owner_match(agents.c.owner_id, owner)))
    rows = result.mappings().all()
    return [AgentResponse(**deserialise_agent_row(row)) for row in rows]


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get an agent by ID",
)
async def get_agent(agent_id: str, db: DBDep, owner: OwnerDep) -> AgentResponse:
    """Fetch a single agent owned by the current owner.

    Args:
        agent_id: UUID of the agent.
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Returns:
        The requested agent.

    Raises:
        HTTPException: 404 if the owner has no agent with the given ID.
    """
    result = await db.execute(
        select(agents).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Replace an agent",
    description="Fully replace all fields of an existing agent.",
)
async def replace_agent(
    agent_id: str, body: AgentCreate, db: DBDep, owner: OwnerDep
) -> AgentResponse:
    """Fully replace all fields of an existing agent owned by the current owner.

    Args:
        agent_id: UUID of the agent to replace.
        body: New agent payload; all fields are required.
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Returns:
        The updated agent.

    Raises:
        HTTPException: 404 if the owner has no agent with the given ID.
    """
    existing = await db.execute(
        select(agents.c.id).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    if existing.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute(
        update(agents)
        .where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
        .values(
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            provider=body.provider,
            model=body.model,
            tools=json.dumps(body.tools),
            connections=json.dumps(body.connections),
        )
    )
    await db.commit()
    result = await db.execute(select(agents).where(agents.c.id == agent_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Partially update an agent",
    description="Update only the supplied fields; all other fields remain unchanged.",
)
async def update_agent(
    agent_id: str, body: AgentUpdate, db: DBDep, owner: OwnerDep
) -> AgentResponse:
    """Partially update an agent; only supplied fields are written.

    Args:
        agent_id: UUID of the agent to update.
        body: Partial update payload; omitted fields are left unchanged.
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Returns:
        The updated agent.

    Raises:
        HTTPException: 404 if the owner has no agent with the given ID.
    """
    scope = (agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    result = await db.execute(select(agents).where(*scope))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    updates: dict[str, str] = {
        field: json.dumps(value) if isinstance(value, list) else value
        for field, value in body.model_dump(exclude_none=True).items()
        if field in _PATCHABLE_COLUMNS
    }

    if updates:
        await db.execute(update(agents).where(*scope).values(**updates))
        await db.commit()

    result = await db.execute(select(agents).where(*scope))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return AgentResponse(**deserialise_agent_row(row))


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete the current owner's agents, knowledge files, and simulation history",
)
async def delete_all(db: DBDep, owner: OwnerDep) -> None:
    """Wipe every agent, knowledge file, and simulation record owned by the caller.

    Only the current owner's data is removed. Deleting each owning row cascades
    to its children: trials → rounds → connections → messages, and agents /
    knowledge_files → agent_files.
    """
    await db.execute(delete(trials).where(owner_match(trials.c.owner_id, owner)))
    await db.execute(delete(agents).where(owner_match(agents.c.owner_id, owner)))
    await db.execute(delete(knowledge_files).where(owner_match(knowledge_files.c.owner_id, owner)))
    await db.commit()


@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent",
)
async def delete_agent(agent_id: str, db: DBDep, owner: OwnerDep) -> None:
    """Delete one of the current owner's agents.

    Args:
        agent_id: UUID of the agent to delete.
        db: Shared database connection injected by FastAPI.
        owner: Data owner resolved from the ``X-Owner-Id`` header.

    Raises:
        HTTPException: 404 if the owner has no agent with the given ID.
    """
    scope = (agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    existing = await db.execute(select(agents.c.id).where(*scope))
    if existing.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute(delete(agents).where(*scope))
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
    dependencies=[Depends(use_credentials)],
)
async def run_agent(
    agent_id: str, body: AgentRunRequest, db: DBDep, owner: OwnerDep
) -> AgentRunResponse:
    # ── Guardrail 1: sanitise incoming prompt ─────────────────────────────────
    try:
        sanitize_prompt(body.prompt, field_name="prompt")
    except PromptInjectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    result = await db.execute(
        select(agents).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")

    agent = deserialise_agent_row(row)

    tool_names: list[str] = agent["tools"] or []
    files = await load_agent_files(db, agent_id)
    system_prompt = hint_files_in_prompt(agent["system_prompt"] or None, list(files), tool_names)

    try:
        response, tools_used = await call_agent(
            body.prompt,
            provider=agent["provider"],
            model=agent["model"],
            system_prompt=system_prompt,
            tool_names=tool_names or None,
            tool_context={"files": files, "tables": {}},
        )
    except MissingCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Agent run failed for agent_id=%s", agent_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider error. Check server logs for details.",
        ) from exc

    # ── Guardrail 2: validate LLM output ─────────────────────────────────────
    try:
        validate_llm_output(response)
    except LLMRefusalError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except (InjectionEchoError, ValueError) as exc:
        logger.warning("Output guardrail triggered for agent_id=%s: %s", agent_id, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return AgentRunResponse(agent_id=agent_id, response=response, tools_used=tools_used)


@router.get(
    "/{agent_id}/files",
    response_model=list[KnowledgeFileResponse],
    summary="List files attached to an agent",
)
async def list_agent_files(
    agent_id: str, db: DBDep, owner: OwnerDep
) -> list[KnowledgeFileResponse]:
    existing = await db.execute(
        select(agents.c.id).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    if existing.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    result = await db.execute(
        select(knowledge_files)
        .select_from(
            knowledge_files.join(agent_files, agent_files.c.file_id == knowledge_files.c.id)
        )
        .where(agent_files.c.agent_id == agent_id)
    )
    rows = result.mappings().all()
    return [KnowledgeFileResponse(**deserialise_knowledge_file_row(row)) for row in rows]


@router.post(
    "/{agent_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Attach a file to an agent",
)
async def attach_file_to_agent(agent_id: str, file_id: str, db: DBDep, owner: OwnerDep) -> None:
    agent_exists = await db.execute(
        select(agents.c.id).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    if agent_exists.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    file_exists = await db.execute(
        select(knowledge_files.c.id).where(
            knowledge_files.c.id == file_id, owner_match(knowledge_files.c.owner_id, owner)
        )
    )
    if file_exists.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    link_exists = await db.execute(
        select(agent_files.c.agent_id).where(
            agent_files.c.agent_id == agent_id, agent_files.c.file_id == file_id
        )
    )
    if link_exists.first() is None:
        await db.execute(insert(agent_files).values(agent_id=agent_id, file_id=file_id))
        await db.commit()


@router.delete(
    "/{agent_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Detach a file from an agent",
)
async def detach_file_from_agent(agent_id: str, file_id: str, db: DBDep, owner: OwnerDep) -> None:
    existing = await db.execute(
        select(agents.c.id).where(agents.c.id == agent_id, owner_match(agents.c.owner_id, owner))
    )
    if existing.first() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    await db.execute(
        delete(agent_files).where(
            agent_files.c.agent_id == agent_id, agent_files.c.file_id == file_id
        )
    )
    await db.commit()

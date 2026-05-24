"""Knowledge-file CRUD routes, mounted at ``/api/files``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import deserialise_knowledge_file_row, get_db
from server.db.tables import knowledge_files
from server.schemas import KnowledgeFileCreate, KnowledgeFileResponse, KnowledgeFileUpdate

router = APIRouter(prefix="/api/files", tags=["Knowledge Files"])

DBDep = Annotated[AsyncConnection, Depends(get_db)]
_PATCHABLE_COLUMNS: frozenset[str] = frozenset(KnowledgeFileUpdate.model_fields.keys())


@router.post(
    "",
    response_model=KnowledgeFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new knowledge file",
    description="Persist a new knowledge file and return it with its generated UUID.",
)
async def create_knowledge_file(body: KnowledgeFileCreate, db: DBDep) -> KnowledgeFileResponse:
    file_id = body.id or str(uuid.uuid4())
    await db.execute(
        insert(knowledge_files).values(id=file_id, name=body.name, content=body.content)
    )
    await db.commit()
    result = await db.execute(select(knowledge_files).where(knowledge_files.c.id == file_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    return KnowledgeFileResponse(**deserialise_knowledge_file_row(row))


@router.get(
    "",
    response_model=list[KnowledgeFileResponse],
    summary="List all knowledge files",
)
async def list_knowledge_files(db: DBDep) -> list[KnowledgeFileResponse]:
    result = await db.execute(select(knowledge_files))
    rows = result.mappings().all()
    return [KnowledgeFileResponse(**deserialise_knowledge_file_row(row)) for row in rows]


@router.get(
    "/{file_id}",
    response_model=KnowledgeFileResponse,
    summary="Get a knowledge file by ID",
)
async def get_knowledge_file(file_id: str, db: DBDep) -> KnowledgeFileResponse:
    result = await db.execute(select(knowledge_files).where(knowledge_files.c.id == file_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    return KnowledgeFileResponse(**deserialise_knowledge_file_row(row))


@router.put(
    "/{file_id}",
    response_model=KnowledgeFileResponse,
    summary="Replace a knowledge file",
    description="Fully replace all fields of an existing knowledge file.",
)
async def replace_knowledge_file(
    file_id: str, body: KnowledgeFileCreate, db: DBDep
) -> KnowledgeFileResponse:
    existing = await db.execute(select(knowledge_files.c.id).where(knowledge_files.c.id == file_id))
    if existing.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    await db.execute(
        update(knowledge_files)
        .where(knowledge_files.c.id == file_id)
        .values(name=body.name, content=body.content)
    )
    await db.commit()
    result = await db.execute(select(knowledge_files).where(knowledge_files.c.id == file_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    return KnowledgeFileResponse(**deserialise_knowledge_file_row(row))


@router.patch(
    "/{file_id}",
    response_model=KnowledgeFileResponse,
    summary="Partially update a knowledge file",
    description="Update only the supplied fields; all other fields remain unchanged.",
)
async def update_knowledge_file(
    file_id: str, body: KnowledgeFileUpdate, db: DBDep
) -> KnowledgeFileResponse:
    result = await db.execute(select(knowledge_files).where(knowledge_files.c.id == file_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )

    updates: dict[str, str] = {
        field: value
        for field, value in body.model_dump(exclude_none=True).items()
        if field in _PATCHABLE_COLUMNS
    }

    if updates:
        await db.execute(
            update(knowledge_files).where(knowledge_files.c.id == file_id).values(**updates)
        )
        await db.commit()

    result = await db.execute(select(knowledge_files).where(knowledge_files.c.id == file_id))
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    return KnowledgeFileResponse(**deserialise_knowledge_file_row(row))


@router.delete(
    "/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a knowledge file",
    description="Delete a knowledge file and all its agent associations.",
)
async def delete_knowledge_file(file_id: str, db: DBDep) -> None:
    existing = await db.execute(select(knowledge_files.c.id).where(knowledge_files.c.id == file_id))
    if existing.first() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    await db.execute(delete(knowledge_files).where(knowledge_files.c.id == file_id))
    await db.commit()

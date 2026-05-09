"""Knowledge-file CRUD routes, mounted at ``/api/files``."""

from __future__ import annotations

import uuid
from typing import Annotated

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from api.db import deserialise_knowledge_file_row, get_db
from api.schemas import KnowledgeFileCreate, KnowledgeFileResponse, KnowledgeFileUpdate

router = APIRouter(prefix="/api/files", tags=["Knowledge Files"])

DBDep = Annotated[aiosqlite.Connection, Depends(get_db)]
_PATCHABLE_COLUMNS: frozenset[str] = frozenset(KnowledgeFileUpdate.model_fields.keys())


@router.post(
    "/",
    response_model=KnowledgeFileResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new knowledge file",
    description="Persist a new knowledge file and return it with its generated UUID.",
)
async def create_knowledge_file(body: KnowledgeFileCreate, db: DBDep) -> KnowledgeFileResponse:
    file_id = body.id or str(uuid.uuid4())
    await db.execute(
        "INSERT INTO knowledge_files (id, name, content) VALUES (?, ?, ?)",
        (file_id, body.name, body.content),
    )
    await db.commit()
    async with db.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
        )
    return KnowledgeFileResponse(**deserialise_knowledge_file_row(row))


@router.get(
    "/",
    response_model=list[KnowledgeFileResponse],
    summary="List all knowledge files",
)
async def list_knowledge_files(db: DBDep) -> list[KnowledgeFileResponse]:
    async with db.execute("SELECT * FROM knowledge_files") as cur:
        rows = await cur.fetchall()
    return [KnowledgeFileResponse(**deserialise_knowledge_file_row(row)) for row in rows]


@router.get(
    "/{file_id}",
    response_model=KnowledgeFileResponse,
    summary="Get a knowledge file by ID",
)
async def get_knowledge_file(file_id: str, db: DBDep) -> KnowledgeFileResponse:
    async with db.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
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
    async with db.execute("SELECT id FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
            )
    await db.execute(
        "UPDATE knowledge_files SET name = ?, content = ? WHERE id = ?",
        (body.name, body.content, file_id),
    )
    await db.commit()
    async with db.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
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
    async with db.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
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
        set_clause = ", ".join(f"{col} = ?" for col in updates)
        await db.execute(
            f"UPDATE knowledge_files SET {set_clause} WHERE id = ?",  # noqa: S608
            [*updates.values(), file_id],
        )
        await db.commit()

    async with db.execute("SELECT * FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        row = await cur.fetchone()
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
    async with db.execute("SELECT id FROM knowledge_files WHERE id = ?", (file_id,)) as cur:
        if await cur.fetchone() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found."
            )
    await db.execute("DELETE FROM knowledge_files WHERE id = ?", (file_id,))
    await db.commit()

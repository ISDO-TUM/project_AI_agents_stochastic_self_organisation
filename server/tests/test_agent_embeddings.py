"""Tests for agent capability embeddings (PRD §6.2 auction matching)."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.agent_embeddings import (
    backfill_capability_embeddings,
    capability_text,
    compute_capability_embedding,
)


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        yield conn


async def _insert_agent(
    db: AsyncConnection, agent_id: str, *, embedding: str | None = None
) -> None:
    await db.execute(
        text(
            "INSERT INTO agents "
            "(id, name, description, system_prompt, provider, model, capability_embedding) "
            "VALUES (:id, :name, :desc, :sp, 'openai', 'gpt-4o', :emb)"
        ),
        {
            "id": agent_id,
            "name": f"Agent {agent_id}",
            "desc": "A finance specialist",
            "sp": "You analyze contracts.",
            "emb": embedding,
        },
    )
    await db.commit()


def test_capability_text_joins_nonempty_parts() -> None:
    assert capability_text("Alpha", "Finance", "Be precise.") == "Alpha\nFinance\nBe precise."
    assert capability_text("Alpha", "", "  ") == "Alpha"


async def test_compute_returns_none_when_embedding_unavailable() -> None:
    with patch(
        "server.market_hive.agent_embeddings.embed_texts",
        new=AsyncMock(return_value=None),
    ):
        assert await compute_capability_embedding("a", "b", "c") is None


async def test_compute_returns_json_vector() -> None:
    with patch(
        "server.market_hive.agent_embeddings.embed_texts",
        new=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    ):
        result = await compute_capability_embedding("a", "b", "c")
    assert json.loads(result) == [0.1, 0.2, 0.3]


async def test_backfill_only_fills_missing(db: AsyncConnection) -> None:
    await _insert_agent(db, "missing")
    await _insert_agent(db, "present", embedding=json.dumps([9.9]))

    with patch(
        "server.market_hive.agent_embeddings.embed_texts",
        new=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    ):
        filled = await backfill_capability_embeddings(db)

    assert filled == 1
    rows = (
        (await db.execute(text("SELECT id, capability_embedding FROM agents ORDER BY id")))
        .mappings()
        .all()
    )
    by_id = {r["id"]: r["capability_embedding"] for r in rows}
    assert json.loads(by_id["missing"]) == [0.1, 0.2, 0.3]
    assert json.loads(by_id["present"]) == [9.9]  # untouched

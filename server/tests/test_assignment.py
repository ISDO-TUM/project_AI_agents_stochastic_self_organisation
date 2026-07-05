"""Unit tests for taker → thread assignment (PRD §6.2 Phase 4, deterministic v1)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.assignment import assign_takers_to_threads
from server.market_hive.schemas import ThreadSchema


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


async def _insert_agent(db: AsyncConnection, agent_id: str, embedding: list[float] | None) -> None:
    await db.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model, "
            "capability_embedding) VALUES (:id, :id, 'd', 's', 'openai', 'gpt-4o', :emb)"
        ),
        {"id": agent_id, "emb": json.dumps(embedding) if embedding else None},
    )
    await db.commit()


def _thread(title: str, embedding: list[float] | None) -> ThreadSchema:
    return ThreadSchema(
        id=str(uuid.uuid4()),
        contract_id="c1",
        run_id="r1",
        title=title,
        description=title,
        thread_embedding=embedding,
        created_at=datetime.now(UTC),
    )


async def test_single_thread_gets_all_takers(db: AsyncConnection) -> None:
    thread = _thread("Main", None)
    result = await assign_takers_to_threads(db, takers=["a", "b", "c"], threads=[thread])
    assert result == {thread.id: ["a", "b", "c"]}


async def test_tiny_team_works_every_thread(db: AsyncConnection) -> None:
    threads = [_thread("Legal", [1.0, 0.0]), _thread("Finance", [0.0, 1.0])]
    result = await assign_takers_to_threads(db, takers=["a", "b"], threads=threads)
    assert result == {threads[0].id: ["a", "b"], threads[1].id: ["a", "b"]}


async def test_takers_matched_to_best_thread(db: AsyncConnection) -> None:
    for agent_id, emb in [
        ("legal1", [1.0, 0.0]),
        ("legal2", [0.9, 0.1]),
        ("fin1", [0.0, 1.0]),
        ("fin2", [0.1, 0.9]),
    ]:
        await _insert_agent(db, agent_id, emb)
    legal, finance = _thread("Legal", [1.0, 0.0]), _thread("Finance", [0.0, 1.0])

    result = await assign_takers_to_threads(
        db, takers=["legal1", "legal2", "fin1", "fin2"], threads=[legal, finance]
    )
    assert result[legal.id] == ["legal1", "legal2"]
    assert result[finance.id] == ["fin1", "fin2"]


async def test_understaffed_thread_topped_up_with_best_matches(db: AsyncConnection) -> None:
    # All three takers match Legal best; Finance must still get two takers.
    for agent_id, emb in [
        ("a", [1.0, 0.0]),
        ("b", [0.9, 0.2]),  # second-best Finance match
        ("c", [0.8, 0.4]),  # best Finance match
    ]:
        await _insert_agent(db, agent_id, emb)
    legal, finance = _thread("Legal", [1.0, 0.0]), _thread("Finance", [0.0, 1.0])

    result = await assign_takers_to_threads(db, takers=["a", "b", "c"], threads=[legal, finance])
    assert result[legal.id] == ["a", "b", "c"]
    assert result[finance.id] == ["b", "c"]  # top-up by descending Finance cosine


async def test_taker_without_embedding_joins_every_thread(db: AsyncConnection) -> None:
    for agent_id, emb in [
        ("a", [1.0, 0.0]),
        ("b", [0.9, 0.1]),
        ("mystery", None),
    ]:
        await _insert_agent(db, agent_id, emb)
    legal, finance = _thread("Legal", [1.0, 0.0]), _thread("Finance", [0.0, 1.0])

    result = await assign_takers_to_threads(
        db, takers=["a", "b", "mystery"], threads=[legal, finance]
    )
    assert "mystery" in result[legal.id]
    assert "mystery" in result[finance.id]


async def test_thread_without_embedding_gets_everyone(db: AsyncConnection) -> None:
    for agent_id, emb in [("a", [1.0, 0.0]), ("b", [0.9, 0.1]), ("c", [0.8, 0.2])]:
        await _insert_agent(db, agent_id, emb)
    legal, blind = _thread("Legal", [1.0, 0.0]), _thread("Blind", None)

    result = await assign_takers_to_threads(db, takers=["a", "b", "c"], threads=[legal, blind])
    assert result[blind.id] == ["a", "b", "c"]

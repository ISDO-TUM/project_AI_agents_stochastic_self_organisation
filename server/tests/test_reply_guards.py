"""Reply-per-round cap and semantic self-dedup on post_to_blackboard.

Both guards target the same failure mode from a real run: one taker posted
12 replies in a single round, stretching a 4-taker/9-round run to ~25 minutes
(see server/market_hive/tools.py MAX_REPLIES_PER_ROUND for the full story).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.tools import (
    MAX_REPLIES_PER_ROUND,
    PostToBlackboardInput,
    PostToBlackboardTool,
)


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Iterator[None]:
    """Default to offline (no embedding vector) unless a test overrides it."""
    with patch("server.market_hive.tools.embed_texts", new=AsyncMock(return_value=None)):
        yield


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


async def _seed_run(conn: AsyncConnection, run_id: str, thread_id: str, agent_id: str) -> None:
    from sqlalchemy import text

    contract_id = str(uuid.uuid4())
    await conn.execute(text("INSERT OR IGNORE INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :prompt, :task_type)"
        ),
        {"id": contract_id, "run_id": run_id, "prompt": "test prompt", "task_type": "analysis"},
    )
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :contract_id, :run_id, :title, :desc)"
        ),
        {
            "id": thread_id,
            "contract_id": contract_id,
            "run_id": run_id,
            "title": "Test Thread",
            "desc": "A test thread",
        },
    )
    await conn.execute(
        text(
            "INSERT OR IGNORE INTO agents "
            "(id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :name, :desc, :sp, :prov, :model)"
        ),
        {
            "id": agent_id,
            "name": "TestAgent",
            "desc": "desc",
            "sp": "system",
            "prov": "openai",
            "model": "gpt-4o",
        },
    )
    await conn.commit()


async def _post_reply(
    db: AsyncConnection, *, run_id: str, thread_id: str, agent_id: str, round_: int, content: str
) -> str:
    tool = PostToBlackboardTool()
    return await tool.execute(
        PostToBlackboardInput(
            content=content, entry_type="reply", thread_id=thread_id, reply_to="deadbeef"
        ),
        {"db": db, "run_id": run_id, "agent_id": agent_id, "thread_id": thread_id, "round": round_},
    )


@pytest.mark.asyncio
async def test_reply_cap_allows_up_to_the_limit(db: AsyncConnection) -> None:
    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    for i in range(MAX_REPLIES_PER_ROUND):
        result = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
            content=f"distinct point number {i}",
        )
        assert "error" not in result


@pytest.mark.asyncio
async def test_reply_beyond_cap_is_rejected(db: AsyncConnection) -> None:
    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    for i in range(MAX_REPLIES_PER_ROUND):
        await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
            content=f"distinct point number {i}",
        )

    result = await _post_reply(
        db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
        content="one point too many",
    )
    assert "error" in result
    assert "cap" in result.lower()


@pytest.mark.asyncio
async def test_reply_cap_resets_next_round(db: AsyncConnection) -> None:
    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    for i in range(MAX_REPLIES_PER_ROUND):
        await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
            content=f"round 2 point {i}",
        )
    result = await _post_reply(
        db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=3,
        content="round 3 point",
    )
    assert "error" not in result


@pytest.mark.asyncio
async def test_near_duplicate_of_own_post_is_rejected(db: AsyncConnection) -> None:
    """A reply whose embedding is near-identical to the taker's own earlier
    post in this thread is rejected, even though it's well under the count cap."""
    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    same_vec = [1.0, 0.0, 0.0]
    with (
        patch("server.market_hive.tools.embed_texts", new=AsyncMock(return_value=[same_vec])),
        patch("server.market_hive.blackboard.embed_texts", new=AsyncMock(return_value=[same_vec])),
    ):
        first = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
            content="reject clause 4.2 as a penalty",
        )
        assert "error" not in first

        second = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=3,
            content="clause 4.2 should be rejected, it's a penalty clause",
        )
    assert "error" in second
    assert "restating" in second.lower() or "near-identical" in second.lower()


@pytest.mark.asyncio
async def test_different_authors_near_duplicate_is_not_blocked(db: AsyncConnection) -> None:
    """Two different agents independently landing on the same point must NOT be
    blocked — that convergence is exactly what the citation/promotion signal
    wants, not a duplicate to suppress."""
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_a)
    await _seed_run(db, run_id, thread_id, agent_b)

    same_vec = [1.0, 0.0, 0.0]
    with (
        patch("server.market_hive.tools.embed_texts", new=AsyncMock(return_value=[same_vec])),
        patch("server.market_hive.blackboard.embed_texts", new=AsyncMock(return_value=[same_vec])),
    ):
        first = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_a, round_=2,
            content="reject clause 4.2 as a penalty",
        )
        second = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_b, round_=2,
            content="clause 4.2 should be rejected, it's a penalty clause",
        )
    assert "error" not in first
    assert "error" not in second


@pytest.mark.asyncio
async def test_dedup_fails_open_when_embeddings_unavailable(db: AsyncConnection) -> None:
    """embed_texts returning None (offline / API failure) must never block a
    post — every other embedding consumer in this codebase fails open too."""
    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    with patch("server.market_hive.tools.embed_texts", new=AsyncMock(return_value=None)):
        first = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=2,
            content="reject clause 4.2 as a penalty",
        )
        second = await _post_reply(
            db, run_id=run_id, thread_id=thread_id, agent_id=agent_id, round_=3,
            content="reject clause 4.2 as a penalty",
        )
    assert "error" not in first
    assert "error" not in second

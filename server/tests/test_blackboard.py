"""Unit tests for the Blackboard class (SQLAlchemy backend)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.blackboard import Blackboard


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


async def test_post_returns_entry_id(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="My proposal",
        entry_type="proposal",
        round=1,
    )

    assert isinstance(entry_id, str)
    assert len(entry_id) > 0


async def test_post_then_read_returns_entry(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="My proposal",
        entry_type="proposal",
        round=1,
    )
    results = await bb.read(run_id=run_id, query="proposal", thread_id=thread_id)

    assert len(results) == 1
    assert results[0].id == entry_id
    assert results[0].content == "My proposal"
    assert results[0].author_name == "TestAgent"
    assert results[0].citation_count == 0


async def test_read_respects_thread_filter(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())

    await db.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await db.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :p, :t)"
        ),
        {"id": contract_id, "run_id": run_id, "p": "p", "t": "t"},
    )
    for tid, title in [(thread_a, "A"), (thread_b, "B")]:
        await db.execute(
            text(
                "INSERT INTO threads (id, contract_id, run_id, title, description) "
                "VALUES (:id, :cid, :run_id, :title, :desc)"
            ),
            {"id": tid, "cid": contract_id, "run_id": run_id, "title": title, "desc": "desc"},
        )
    await db.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :name, :desc, :sp, :prov, :model)"
        ),
        {
            "id": agent_id,
            "name": "Bot",
            "desc": "d",
            "sp": "s",
            "prov": "openai",
            "model": "gpt-4o",
        },
    )
    await db.commit()

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id,
        thread_id=thread_a,
        author_id=agent_id,
        content="Entry in A",
        entry_type="proposal",
        round=1,
    )
    await bb.post(
        run_id=run_id,
        thread_id=thread_b,
        author_id=agent_id,
        content="Entry in B",
        entry_type="proposal",
        round=1,
    )

    results_a = await bb.read(run_id=run_id, query="entry", thread_id=thread_a)
    results_b = await bb.read(run_id=run_id, query="entry", thread_id=thread_b)
    results_all = await bb.read(run_id=run_id, query="entry", thread_id=None)

    assert len(results_a) == 1
    assert results_a[0].content == "Entry in A"
    assert len(results_b) == 1
    assert results_b[0].content == "Entry in B"
    assert len(results_all) == 2


async def test_read_does_not_return_invisible_entries(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="Hidden",
        entry_type="proposal",
        round=1,
    )
    await db.execute(text("UPDATE draft_entries SET is_visible=0 WHERE id=:id"), {"id": entry_id})
    await db.commit()

    results = await bb.read(run_id=run_id, query="hidden", thread_id=thread_id)
    assert len(results) == 0


async def _seed_two_agents(conn: AsyncConnection, run_id: str, thread_id: str) -> tuple[str, str]:
    from sqlalchemy import text

    contract_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :p, :t)"
        ),
        {"id": contract_id, "run_id": run_id, "p": "p", "t": "t"},
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, :title, :desc)"
        ),
        {"id": thread_id, "cid": contract_id, "run_id": run_id, "title": "T", "desc": "desc"},
    )
    for aid, name in [(agent_a, "A"), (agent_b, "B")]:
        await conn.execute(
            text(
                "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
                "VALUES (:id, :name, :desc, :sp, :prov, :model)"
            ),
            {"id": aid, "name": name, "desc": "d", "sp": "s", "prov": "openai", "model": "gpt-4o"},
        )
    await conn.commit()
    return agent_a, agent_b


async def test_cite_increments_citation_count(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Proposal",
        entry_type="proposal",
        round=1,
    )
    result = await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2)

    assert result["cited"] == 1
    assert result["skipped_self"] == 0

    entries = await bb.read(run_id=run_id, query="", thread_id=thread_id)
    assert entries[0].citation_count == 1


async def test_cite_skips_self_citation(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_id,
        content="Mine",
        entry_type="proposal",
        round=1,
    )
    result = await bb.cite(run_id=run_id, citing_agent_id=agent_id, entry_ids=[entry_id], round=2)

    assert result["cited"] == 0
    assert result["skipped_self"] == 1


async def test_cite_deduplicates_repeated_entry_ids(db: AsyncConnection) -> None:
    """A duplicate entry_id in one call must not trip the UNIQUE constraint.

    The same agent citing the same entry twice in one round would otherwise raise
    an IntegrityError that aborts the whole transaction on PostgreSQL. De-duping
    plus per-insert savepoints keep the valid citation and stay portable.
    """
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Proposal",
        entry_type="proposal",
        round=1,
    )
    result = await bb.cite(
        run_id=run_id,
        citing_agent_id=agent_b,
        entry_ids=[entry_id, entry_id, entry_id],
        round=2,
    )

    assert result["cited"] == 1
    entries = await bb.read(run_id=run_id, query="", thread_id=thread_id)
    assert entries[0].citation_count == 1


async def test_vote_inserts_record(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Proposal",
        entry_type="proposal",
        round=1,
    )
    result = await bb.vote(run_id=run_id, voter_id=agent_b, entry_id=entry_id, thread_id=thread_id)

    assert result["ok"] is True
    row = (
        await db.execute(
            text("SELECT COUNT(*) FROM votes WHERE run_id=:run_id"), {"run_id": run_id}
        )
    ).scalar_one()
    assert row == 1


async def test_get_confirmed_returns_entries(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    await db.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, content, entry_type, round_confirmed) "
            "VALUES (:id, :run_id, :thread_id, :content, 'anchor', 1)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "thread_id": thread_id,
            "content": "Contract anchor",
        },
    )
    await db.commit()

    bb = Blackboard(db)
    confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    assert len(confirmed) == 1
    assert confirmed[0].content == "Contract anchor"
    assert confirmed[0].entry_type == "anchor"


async def test_check_promotions_promotes_entry_with_enough_citations(
    db: AsyncConnection,
) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Promotion candidate",
        entry_type="proposal",
        round=1,
    )
    # M = max(1, 2 // 3 + 1) = 1 — one distinct non-self citation is enough
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2)

    promoted = await bb.check_promotions(run_id=run_id, current_round=2)

    assert len(promoted) == 1
    assert promoted[0].source_draft_id == entry_id

    confirmed = await bb.get_confirmed(run_id=run_id)
    assert len(confirmed) == 1


async def test_check_promotions_does_not_double_promote(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Already promoted",
        entry_type="proposal",
        round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2)
    await bb.check_promotions(run_id=run_id, current_round=2)
    promoted_again = await bb.check_promotions(run_id=run_id, current_round=3)

    assert len(promoted_again) == 0


async def test_soft_delete_stale_entries(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Stale entry",
        entry_type="reply",
        round=2,
    )
    # decay_rounds=3, current_round=5: rounds_since_citation = 5-0 = 5 >= 3
    deleted = await bb.soft_delete_stale(run_id=run_id, current_round=5, decay_rounds=3)

    assert deleted == 1
    entries = await bb.read(run_id=run_id, query="stale", thread_id=thread_id)
    assert len(entries) == 0


async def test_soft_delete_exempts_round_1_entries(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Round 1 entry",
        entry_type="proposal",
        round=1,
    )
    # current_round=1: round-1 entries are exempt
    deleted = await bb.soft_delete_stale(run_id=run_id, current_round=1, decay_rounds=3)

    assert deleted == 0

"""Unit tests for the Blackboard class (SQLAlchemy backend)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.blackboard import Blackboard


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Iterator[None]:
    """Keep these tests offline + deterministic: never call the embedding API.

    ``Blackboard.post`` embeds every entry's content; with a real API key
    present that would hit the network on every test. Returning ``None``
    makes it fall back to the zero-vector path, exactly as it does offline —
    dedup tests that need real vectors overwrite ``content_embedding`` by hand.
    """
    with patch("server.market_hive.blackboard.embed_texts", new=AsyncMock(return_value=None)):
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


async def test_read_still_returns_invisible_entries(db: AsyncConnection) -> None:
    """Soft-deleted (decayed) entries stay in agents' reading/citing context.

    ``is_visible`` only declutters the human-facing board — hard-excluding a
    decayed entry from ``read`` would mean it can never be cited again (the
    only way it could ever be promoted or resurface), a one-way trap for any
    proposal that gained citations slowly.
    """
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
    assert len(results) == 1
    assert results[0].id == entry_id


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

    promoted = await bb.check_promotions(
        run_id=run_id,
        current_round=2,
        participants_by_thread={thread_id: 2},
    )

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
    await bb.check_promotions(
        run_id=run_id,
        current_round=2,
        participants_by_thread={thread_id: 2},
    )
    promoted_again = await bb.check_promotions(
        run_id=run_id,
        current_round=3,
        participants_by_thread={thread_id: 2},
    )

    assert len(promoted_again) == 0


async def test_soft_delete_stale_entries(db: AsyncConnection) -> None:
    from sqlalchemy import text

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
    # Marked invisible (declutters the human-facing board)...
    row = (
        await db.execute(
            text("SELECT is_visible FROM draft_entries WHERE run_id = :r"), {"r": run_id}
        )
    ).scalar_one()
    assert not row
    # ...but still reachable through `read` — decay must not cut an entry out of
    # agents' own citing context, or it can never be cited (and promoted) again.
    entries = await bb.read(run_id=run_id, query="stale", thread_id=thread_id)
    assert len(entries) == 1


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


async def test_check_promotions_respects_taker_count(db: AsyncConnection) -> None:
    """With 6 takers M = max(1, 6//3+1) = 3 — two citations must not suffice."""
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Needs 3 citers to promote",
        entry_type="proposal",
        round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2)

    # 1 citation, M=3 → should NOT promote
    promoted = await bb.check_promotions(
        run_id=run_id,
        current_round=2,
        participants_by_thread={thread_id: 6},
    )

    assert len(promoted) == 0
    confirmed = await bb.get_confirmed(run_id=run_id)
    assert len(confirmed) == 0


async def test_post_anchor_creates_confirmed_anchor(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    anchor_id = await bb.post_anchor(
        run_id=run_id,
        thread_id=thread_id,
        content="[ANCHOR] Contract: test prompt",
    )

    assert isinstance(anchor_id, str)

    confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)
    assert len(confirmed) == 1
    assert confirmed[0].id == anchor_id
    assert confirmed[0].entry_type == "anchor"
    assert confirmed[0].source_draft_id is None
    assert confirmed[0].round_confirmed == 0


async def test_mention_creates_system_entry(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    from sqlalchemy import text

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Hey, check this out",
        entry_type="reply",
        round=2,
        mention_agents=[agent_b],
    )

    # One system-typed entry should have been created as a reply to the original
    result = await db.execute(
        text(
            "SELECT id, entry_type, reply_to, mention_agents "
            "FROM draft_entries WHERE run_id=:run_id AND entry_type='system'"
        ),
        {"run_id": run_id},
    )
    rows = result.fetchall()
    assert len(rows) == 1
    system_row = rows[0]
    assert system_row[1] == "system"
    assert system_row[2] == entry_id
    import json

    assert agent_b in json.loads(system_row[3])


async def test_mention_pins_to_top_of_read(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    # Post a high-citation entry first
    popular_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Popular entry",
        entry_type="proposal",
        round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[popular_id], round=2)

    # Post a mention entry that would normally rank lower (zero citations)
    mention_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Hey agent_b, look at this",
        entry_type="reply",
        round=2,
        mention_agents=[agent_b],
    )

    results = await bb.read(run_id=run_id, query="", thread_id=thread_id, agent_id=agent_b)
    # The mentioned entry should be first even though popular_id has more citations
    assert results[0].id == mention_id


async def test_read_mention_pin_cross_thread(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())

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
            {"id": tid, "cid": contract_id, "run_id": run_id, "title": title, "desc": "d"},
        )
    for aid, name in [(agent_a, "A"), (agent_b, "B")]:
        await db.execute(
            text(
                "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
                "VALUES (:id, :name, :desc, :sp, :prov, :model)"
            ),
            {"id": aid, "name": name, "desc": "d", "sp": "s", "prov": "openai", "model": "gpt-4o"},
        )
    await db.commit()

    bb = Blackboard(db)
    # Post in thread_a mentioning agent_b
    mention_id = await bb.post(
        run_id=run_id,
        thread_id=thread_a,
        author_id=agent_a,
        content="Cross-thread mention",
        entry_type="reply",
        round=1,
        mention_agents=[agent_b],
    )
    # Post unrelated entry in thread_b
    await bb.post(
        run_id=run_id,
        thread_id=thread_b,
        author_id=agent_b,
        content="Unrelated",
        entry_type="proposal",
        round=1,
    )

    # Cross-thread read: agent_b should see the mention pinned first
    results = await bb.read(run_id=run_id, query="", thread_id=None, agent_id=agent_b)
    assert results[0].id == mention_id


async def test_mention_pins_outside_top_k_window(db: AsyncConnection) -> None:
    """A mentioned entry must surface at position 0 even if it would rank outside k."""
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)

    # Post the mention entry first (0 citations — will rank last by citation weight)
    mention_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Hey agent_b, this is for you",
        entry_type="reply",
        round=2,
        mention_agents=[agent_b],
    )

    # Post k=2 entries that each have a citation, so they crowd out the mention entry
    # when k=2 and only citation-count ranking is used.
    popular_ids = []
    for i in range(2):
        eid = await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=agent_a,
            content=f"Popular entry {i}",
            entry_type="proposal",
            round=1,
        )
        await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[eid], round=2)
        popular_ids.append(eid)

    # With k=2, top_k_visible would return the 2 popular entries and miss the mention.
    # read() must still surface the mention at position 0.
    results = await bb.read(run_id=run_id, query="", thread_id=thread_id, agent_id=agent_b, k=2)
    assert results[0].id == mention_id


async def test_mention_writes_to_messages_table(db: AsyncConnection) -> None:
    """When round_id is provided, a mention records a bb_mention row in the messages table."""
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    # Create the trial and round rows that the messages table requires as FKs.
    trial_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO trials (id, user_prompt, description, created_at) "
            "VALUES (:id, :prompt, :desc, :ts)"
        ),
        {"id": trial_id, "prompt": "test", "desc": "test trial", "ts": "2024-01-01T00:00:00"},
    )
    result = await db.execute(
        text(
            "INSERT INTO rounds (trial_id, round_index, phase, created_at) "
            "VALUES (:trial_id, :idx, :phase, :ts)"
        ),
        {"trial_id": trial_id, "idx": 1, "phase": "bb_round", "ts": "2024-01-01T00:00:00"},
    )
    await db.commit()
    round_id = result.lastrowid

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Hey agent_b!",
        entry_type="reply",
        round=1,
        mention_agents=[agent_b],
        round_id=round_id,
    )

    rows = (
        await db.execute(
            text(
                "SELECT from_agent_id, to_agent_id, message_type, message "
                "FROM messages WHERE round_id = :rid"
            ),
            {"rid": round_id},
        )
    ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == agent_a
    assert rows[0][1] == agent_b
    assert rows[0][2] == "bb_mention"
    assert rows[0][3] == "Hey agent_b!"


# ── id resolution (truncated display ids → real ids) ───────────────────────────


async def test_reply_to_resolves_truncated_id(db: AsyncConnection) -> None:
    """A reply whose reply_to is the 8-char display prefix links to the full entry."""
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    parent_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Parent proposal",
        entry_type="proposal",
        round=1,
    )
    # The LLM copies the 8-char prefix shown by read_blackboard.
    reply_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_b,
        content="Building on that",
        entry_type="reply",
        round=2,
        reply_to=parent_id[:8],
    )

    stored = (
        await db.execute(
            text("SELECT reply_to FROM draft_entries WHERE id = :id"), {"id": reply_id}
        )
    ).scalar_one()
    assert stored == parent_id  # resolved to the full id, not the 8-char prefix


async def test_reply_to_unknown_id_becomes_top_level(db: AsyncConnection) -> None:
    """An unresolvable reply_to is dropped (top-level post), never an FK violation."""
    from sqlalchemy import text

    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    reply_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Reply to a stale id",
        entry_type="reply",
        round=2,
        reply_to="deadbeef",  # no such entry
    )

    stored = (
        await db.execute(
            text("SELECT reply_to FROM draft_entries WHERE id = :id"), {"id": reply_id}
        )
    ).scalar_one()
    assert stored is None


async def test_cite_resolves_truncated_entry_id(db: AsyncConnection) -> None:
    """A citation using the 8-char display id is recorded, not silently dropped."""
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    target_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="Cite me",
        entry_type="proposal",
        round=1,
    )
    result = await bb.cite(
        run_id=run_id,
        citing_agent_id=agent_b,
        entry_ids=[target_id[:8]],
        round=2,
    )
    assert result["cited"] == 1


# ── Contestable consensus: dispute / contest / re-affirm / dedup ─────────────


async def _add_agent(conn: AsyncConnection, agent_id: str, name: str) -> None:
    from sqlalchemy import text

    await conn.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :name, 'd', 's', 'openai', 'gpt-4o')"
        ),
        {"id": agent_id, "name": name},
    )
    await conn.commit()


async def _seed_confirmed(conn: AsyncConnection, run_id: str, thread_id: str, author: str) -> str:
    """Post a draft entry by ``author`` and directly insert its confirmed row
    (bypassing the citation threshold) — returns the confirmed_entry id."""
    from sqlalchemy import text

    bb = Blackboard(conn)
    draft_id = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=author,
        content="a confirmed finding",
        entry_type="proposal",
        round=1,
    )
    confirmed_id = str(uuid.uuid4())
    await conn.execute(
        text(
            """
            INSERT INTO confirmed_entries
                (id, run_id, thread_id, source_draft_id, content,
                 entry_type, citation_count, round_confirmed)
            VALUES (:id, :run_id, :thread_id, :source_draft_id, :content,
                    'finding', 1, 1)
            """
        ),
        {
            "id": confirmed_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "source_draft_id": draft_id,
            "content": "a confirmed finding",
        },
    )
    await conn.commit()
    return confirmed_id


async def test_dispute_rejects_self(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)
    ce_id = await _seed_confirmed(db, run_id, thread_id, agent_a)

    bb = Blackboard(db)
    result = await bb.dispute(
        run_id=run_id,
        disputing_agent_id=agent_a,
        confirmed_entry_id=ce_id,
        reason="x",
        round=2,
    )
    assert result["ok"] is False
    n = (await db.execute(text("SELECT COUNT(*) FROM disputes"))).scalar_one()
    assert n == 0


async def test_dispute_rejects_duplicate(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    ce_id = await _seed_confirmed(db, run_id, thread_id, agent_a)

    bb = Blackboard(db)
    first = await bb.dispute(
        run_id=run_id, disputing_agent_id=agent_b, confirmed_entry_id=ce_id, reason="x", round=2
    )
    assert first["ok"] is True
    second = await bb.dispute(
        run_id=run_id, disputing_agent_id=agent_b, confirmed_entry_id=ce_id, reason="y", round=3
    )
    assert second["ok"] is False
    n = (await db.execute(text("SELECT COUNT(*) FROM disputes"))).scalar_one()
    assert n == 1


async def test_dispute_rejects_non_confirmed_target(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    _agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    result = await bb.dispute(
        run_id=run_id,
        disputing_agent_id=agent_b,
        confirmed_entry_id="no-such-entry",
        reason="x",
        round=2,
    )
    assert result["ok"] is False
    assert result["why"] == "not disputable"


async def test_dispute_below_threshold_keeps_status(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    ce_id = await _seed_confirmed(db, run_id, thread_id, agent_a)

    bb = Blackboard(db)
    r = await bb.dispute(
        run_id=run_id,
        disputing_agent_id=agent_b,
        confirmed_entry_id=ce_id,
        reason="stale data",
        round=3,
    )
    assert r["ok"]

    # M = max(1, 6 // 3 + 1) = 3 — one disputer is not enough.
    contested = await bb.contest_check(
        run_id=run_id, current_round=3, participants_by_thread={thread_id: 6}
    )
    assert contested == []
    status = (
        await db.execute(text("SELECT status FROM confirmed_entries WHERE id=:id"), {"id": ce_id})
    ).scalar_one()
    assert status == "confirmed"


async def test_m_distinct_disputes_flip_to_contested(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    agent_c = str(uuid.uuid4())
    await _add_agent(db, agent_c, "C")
    ce_id = await _seed_confirmed(db, run_id, thread_id, agent_a)

    bb = Blackboard(db)
    # M = max(1, 4 // 3 + 1) = 2 — two distinct disputers cross the threshold.
    for agent in (agent_b, agent_c):
        r = await bb.dispute(
            run_id=run_id,
            disputing_agent_id=agent,
            confirmed_entry_id=ce_id,
            reason="contradicted by §7",
            round=3,
        )
        assert r["ok"]

    contested = await bb.contest_check(
        run_id=run_id, current_round=3, participants_by_thread={thread_id: 4}
    )
    assert [c.id for c in contested] == [ce_id]
    assert contested[0].status == "contested"

    # A system note announcing the contest must be visible on the board.
    note = (
        await db.execute(
            text(
                "SELECT content FROM draft_entries WHERE entry_type = 'system' "
                "AND content LIKE '%contested%'"
            )
        )
    ).scalar()
    assert note is not None

    # Re-running contest_check is idempotent — status is already 'contested',
    # so the WHERE status='confirmed' filter excludes it from re-processing.
    again = await bb.contest_check(
        run_id=run_id, current_round=4, participants_by_thread={thread_id: 4}
    )
    assert again == []


async def test_reaffirm_check_flips_contested_back_to_confirmed(db: AsyncConnection) -> None:
    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    agent_c = str(uuid.uuid4())
    await _add_agent(db, agent_c, "C")
    ce_id = await _seed_confirmed(db, run_id, thread_id, agent_a)

    bb = Blackboard(db)
    for agent in (agent_b, agent_c):
        await bb.dispute(
            run_id=run_id,
            disputing_agent_id=agent,
            confirmed_entry_id=ce_id,
            reason="contradicted",
            round=3,
        )
    contested = await bb.contest_check(
        run_id=run_id, current_round=3, participants_by_thread={thread_id: 4}
    )
    assert len(contested) == 1

    source_draft_id = (
        await db.execute(
            text("SELECT source_draft_id FROM confirmed_entries WHERE id=:id"), {"id": ce_id}
        )
    ).scalar_one()

    # Fresh citations on the source draft, strictly after the contest round.
    for agent in (agent_b, agent_c):
        await bb.cite(run_id=run_id, citing_agent_id=agent, entry_ids=[source_draft_id], round=4)

    reaffirmed = await bb.reaffirm_check(run_id=run_id, participants_by_thread={thread_id: 4})
    assert [c.id for c in reaffirmed] == [ce_id]
    assert reaffirmed[0].status == "confirmed"

    status = (
        await db.execute(text("SELECT status FROM confirmed_entries WHERE id=:id"), {"id": ce_id})
    ).scalar_one()
    assert status == "confirmed"

    note = (
        await db.execute(
            text(
                "SELECT content FROM draft_entries WHERE entry_type = 'system' "
                "AND content LIKE '%re-affirmed%'"
            )
        )
    ).scalar()
    assert note is not None


async def test_check_promotions_dedup_merges_near_duplicate(db: AsyncConnection) -> None:
    """Two near-identical findings (hand-written embeddings, no API needed) merge
    into a single confirmed entry instead of both being promoted separately."""
    import json as json_lib

    from sqlalchemy import text

    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    agent_c = str(uuid.uuid4())
    await _add_agent(db, agent_c, "C")

    bb = Blackboard(db)
    vec = json_lib.dumps([1.0, 0.0, 0.0])
    entry1 = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="First phrasing of the finding",
        entry_type="proposal",
        round=1,
    )
    entry2 = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_c,
        content="Second phrasing of the same finding",
        entry_type="proposal",
        round=1,
    )
    for eid in (entry1, entry2):
        await db.execute(
            text("UPDATE draft_entries SET content_embedding = :emb WHERE id = :id"),
            {"emb": vec, "id": eid},
        )
    await db.commit()

    # Promote entry1 first (M=1 with 2 participants).
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry1], round=2)
    promoted1 = await bb.check_promotions(
        run_id=run_id, current_round=2, participants_by_thread={thread_id: 2}
    )
    assert len(promoted1) == 1
    confirmed_id = promoted1[0].id

    # entry2 crosses the threshold too, but its embedding is a near-duplicate —
    # it must merge into entry1's confirmed row, not create a second one.
    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry2], round=3)
    promoted2 = await bb.check_promotions(
        run_id=run_id, current_round=3, participants_by_thread={thread_id: 2}
    )
    assert promoted2 == []

    confirmed_rows = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)
    assert len(confirmed_rows) == 1

    merged_into = (
        await db.execute(
            text("SELECT merged_into FROM draft_entries WHERE id = :id"), {"id": entry2}
        )
    ).scalar_one()
    assert merged_into == confirmed_id

    citation_count = (
        await db.execute(
            text("SELECT citation_count FROM confirmed_entries WHERE id = :id"),
            {"id": confirmed_id},
        )
    ).scalar_one()
    assert citation_count == 2  # original + the merged entry's distinct citer

    note = (
        await db.execute(
            text(
                "SELECT content FROM draft_entries WHERE entry_type = 'system' "
                "AND content LIKE '%merged into an existing confirmed finding%'"
            )
        )
    ).scalar()
    assert note is not None


async def test_check_promotions_dedup_skipped_when_embeddings_zero(db: AsyncConnection) -> None:
    """Zero/offline embeddings must never block promotion — dedup is a pure gate,
    never a blocker, when no real vectors are available."""
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)
    agent_c = str(uuid.uuid4())
    await _add_agent(db, agent_c, "C")

    bb = Blackboard(db)
    # _offline_embeddings makes post() fall back to the zero vector for both —
    # identical zero vectors, yet dedup must NOT treat them as a match.
    entry1 = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_a,
        content="First finding",
        entry_type="proposal",
        round=1,
    )
    entry2 = await bb.post(
        run_id=run_id,
        thread_id=thread_id,
        author_id=agent_c,
        content="Second finding",
        entry_type="proposal",
        round=1,
    )

    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry1], round=2)
    promoted1 = await bb.check_promotions(
        run_id=run_id, current_round=2, participants_by_thread={thread_id: 2}
    )
    assert len(promoted1) == 1

    await bb.cite(run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry2], round=3)
    promoted2 = await bb.check_promotions(
        run_id=run_id, current_round=3, participants_by_thread={thread_id: 2}
    )
    assert len(promoted2) == 1  # NOT merged

    confirmed_rows = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)
    assert len(confirmed_rows) == 2


# ── carry_forward_findings (multi-turn contract sessions) ─────────────────────


async def _seed_anchor(conn: AsyncConnection, *, run_id: str, thread_id: str, content: str) -> str:
    """A pre-existing anchor (no source_draft_id) — must never carry forward."""
    from sqlalchemy import text

    anchor_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, content, entry_type, round_confirmed) "
            "VALUES (:id, :run_id, :thread_id, :content, 'anchor', 0)"
        ),
        {"id": anchor_id, "run_id": run_id, "thread_id": thread_id, "content": content},
    )
    await conn.commit()
    return anchor_id


async def test_carry_forward_brings_findings_as_anchors_with_provenance(
    db: AsyncConnection,
) -> None:
    from sqlalchemy import text

    from server.market_hive.blackboard import carry_forward_findings

    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)
    await _seed_confirmed(db, run_id, thread_id, agent_id)  # one finding
    await _seed_anchor(db, run_id=run_id, thread_id=thread_id, content="pre-existing anchor")

    child_id = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": child_id},
    )
    await db.commit()

    carried = await carry_forward_findings(db, parent_run_id=run_id, child_run_id=child_id)

    assert len(carried) == 1
    assert carried[0].entry_type == "anchor"
    assert carried[0].origin_run_id == run_id
    assert carried[0].content.startswith("[carried] ")

    rows = (
        await db.execute(
            text("SELECT COUNT(*) FROM confirmed_entries WHERE run_id = :r"), {"r": child_id}
        )
    ).scalar_one()
    assert rows == 1  # the parent's own anchor did NOT transfer


async def test_carry_forward_is_not_transitive(db: AsyncConnection) -> None:
    """r1 → r2 (carried anchor) → r3: r3 gets r2's *own* finding only — r2's
    carried anchor (entry_type='anchor') does not re-carry."""
    from sqlalchemy import text

    from server.market_hive.blackboard import carry_forward_findings

    r1, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, r1, thread_id, agent_id)
    await _seed_confirmed(db, r1, thread_id, agent_id)

    r2 = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": r2},
    )
    await db.commit()
    await carry_forward_findings(db, parent_run_id=r1, child_run_id=r2)
    # r2 gains its own genuine finding on top of the carried anchor:
    await _seed_confirmed(db, r2, thread_id, agent_id)

    r3 = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": r3},
    )
    await db.commit()
    carried = await carry_forward_findings(db, parent_run_id=r2, child_run_id=r3)

    assert len(carried) == 1  # only r2's own finding — its carried anchor did not re-carry
    assert all(c.origin_run_id == r2 for c in carried)


async def test_carry_forward_excludes_retracted_findings(db: AsyncConnection) -> None:
    from sqlalchemy import text

    from server.market_hive.blackboard import carry_forward_findings

    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)
    confirmed_id = await _seed_confirmed(db, run_id, thread_id, agent_id)
    await db.execute(
        text("UPDATE confirmed_entries SET status = 'retracted' WHERE id = :id"),
        {"id": confirmed_id},
    )
    await db.commit()

    child_id = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": child_id},
    )
    await db.commit()

    carried = await carry_forward_findings(db, parent_run_id=run_id, child_run_id=child_id)
    assert carried == []


async def test_carried_anchors_visible_via_get_confirmed_across_threads(
    db: AsyncConnection,
) -> None:
    """Carried anchors reference the parent's thread_id, which does not belong
    to the child run — get_confirmed(thread_id=None) must still surface them."""
    from sqlalchemy import text

    from server.market_hive.blackboard import carry_forward_findings

    run_id, thread_id, agent_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)
    await _seed_confirmed(db, run_id, thread_id, agent_id)

    child_id = str(uuid.uuid4())
    await db.execute(
        text("INSERT INTO swarm_runs (id, status, mode) VALUES (:id, 'running', 'swarm')"),
        {"id": child_id},
    )
    await db.commit()
    await carry_forward_findings(db, parent_run_id=run_id, child_run_id=child_id)

    bb = Blackboard(db)
    entries = await bb.get_confirmed(run_id=child_id, thread_id=None)
    assert len(entries) == 1
    assert entries[0].content.startswith("[carried] ")

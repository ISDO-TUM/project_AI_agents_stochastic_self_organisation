"""Unit tests for the Blackboard class."""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("DB_PATH", ":memory:")

from api.db import init_db, close_db
from api.swarm.blackboard import Blackboard


@pytest.fixture
async def db():
    await init_db()
    from api.db import _db
    yield _db
    await close_db()


async def _seed_run(db, run_id: str, thread_id: str, agent_id: str) -> None:
    """Insert minimal swarm_runs + threads + agents rows for FK constraints."""
    await db.execute(
        "INSERT OR IGNORE INTO swarm_runs (id) VALUES (?)", (run_id,)
    )
    # Insert a contract first (threads FK to contracts)
    contract_id = str(uuid.uuid4())
    await db.execute(
        "INSERT OR IGNORE INTO contracts (id, run_id, original_prompt, task_type) "
        "VALUES (?, ?, ?, ?)",
        (contract_id, run_id, "test prompt", "analysis"),
    )
    await db.execute(
        "INSERT OR IGNORE INTO threads (id, contract_id, run_id, title, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (thread_id, contract_id, run_id, "Test Thread", "A test thread"),
    )
    await db.execute(
        "INSERT OR IGNORE INTO agents "
        "(id, name, description, system_prompt, provider, model) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (agent_id, "TestAgent", "desc", "system", "openai", "gpt-4o"),
    )
    await db.commit()


async def test_post_returns_entry_id(db) -> None:
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


async def test_post_then_read_returns_entry(db) -> None:
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


async def test_read_respects_thread_filter(db) -> None:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_a = str(uuid.uuid4())
    thread_b = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())

    await db.execute("INSERT INTO swarm_runs (id) VALUES (?)", (run_id,))
    await db.execute(
        "INSERT INTO contracts (id, run_id, original_prompt, task_type) VALUES (?,?,?,?)",
        (contract_id, run_id, "p", "t"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_a, contract_id, run_id, "A", "desc"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_b, contract_id, run_id, "B", "desc"),
    )
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_id, "Bot", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    await bb.post(run_id=run_id, thread_id=thread_a, author_id=agent_id,
                  content="Entry in A", entry_type="proposal", round=1)
    await bb.post(run_id=run_id, thread_id=thread_b, author_id=agent_id,
                  content="Entry in B", entry_type="proposal", round=1)

    results_a = await bb.read(run_id=run_id, query="entry", thread_id=thread_a)
    results_b = await bb.read(run_id=run_id, query="entry", thread_id=thread_b)
    results_all = await bb.read(run_id=run_id, query="entry", thread_id=None)

    assert len(results_a) == 1
    assert results_a[0].content == "Entry in A"
    assert len(results_b) == 1
    assert results_b[0].content == "Entry in B"
    assert len(results_all) == 2


async def test_read_does_not_return_invisible_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_id,
        content="Hidden", entry_type="proposal", round=1,
    )
    # Manually soft-delete
    await db.execute(
        "UPDATE draft_entries SET is_visible=0 WHERE id=?", (entry_id,)
    )
    await db.commit()

    results = await bb.read(run_id=run_id, query="hidden", thread_id=thread_id)
    assert len(results) == 0


# ── Task 5 tests ──────────────────────────────────────────────────────────────

async def test_cite_increments_citation_count(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_a)
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_b, "AgentB", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Proposal", entry_type="proposal", round=1,
    )
    result = await bb.cite(
        run_id=run_id, citing_agent_id=agent_b, entry_ids=[entry_id], round=2
    )

    assert result["cited"] == 1
    assert result["skipped_self"] == 0

    entries = await bb.read(run_id=run_id, query="", thread_id=thread_id)
    assert entries[0].citation_count == 1


async def test_cite_skips_self_citation(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_id,
        content="Mine", entry_type="proposal", round=1,
    )
    result = await bb.cite(
        run_id=run_id, citing_agent_id=agent_id, entry_ids=[entry_id], round=2
    )

    assert result["cited"] == 0
    assert result["skipped_self"] == 1


async def test_vote_inserts_record(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_a)
    await db.execute(
        "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
        "VALUES (?,?,?,?,?,?)",
        (agent_b, "B", "d", "s", "openai", "gpt-4o"),
    )
    await db.commit()

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Proposal", entry_type="proposal", round=1,
    )
    result = await bb.vote(
        run_id=run_id, voter_id=agent_b, entry_id=entry_id, thread_id=thread_id
    )

    assert result["ok"] is True
    async with db.execute("SELECT COUNT(*) FROM votes WHERE run_id=?", (run_id,)) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


async def test_get_confirmed_returns_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    await _seed_run(db, run_id, thread_id, agent_id)

    await db.execute(
        """
        INSERT INTO confirmed_entries
            (id, run_id, thread_id, content, entry_type, round_confirmed)
        VALUES (?, ?, ?, ?, 'anchor', 1)
        """,
        (str(uuid.uuid4()), run_id, thread_id, "Contract anchor"),
    )
    await db.commit()

    bb = Blackboard(db)
    confirmed = await bb.get_confirmed(run_id=run_id, thread_id=thread_id)

    assert len(confirmed) == 1
    assert confirmed[0].content == "Contract anchor"
    assert confirmed[0].entry_type == "anchor"


# ── Task 6 tests ──────────────────────────────────────────────────────────────

async def _seed_two_agents(db, run_id: str, thread_id: str) -> tuple[str, str]:
    """Seed a run + thread + two agents. Returns (agent_a_id, agent_b_id)."""
    contract_id = str(uuid.uuid4())
    agent_a = str(uuid.uuid4())
    agent_b = str(uuid.uuid4())
    await db.execute("INSERT INTO swarm_runs (id) VALUES (?)", (run_id,))
    await db.execute(
        "INSERT INTO contracts (id, run_id, original_prompt, task_type) VALUES (?,?,?,?)",
        (contract_id, run_id, "p", "t"),
    )
    await db.execute(
        "INSERT INTO threads (id, contract_id, run_id, title, description) VALUES (?,?,?,?,?)",
        (thread_id, contract_id, run_id, "T", "desc"),
    )
    for aid, name in [(agent_a, "A"), (agent_b, "B")]:
        await db.execute(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (?,?,?,?,?,?)",
            (aid, name, "d", "s", "openai", "gpt-4o"),
        )
    await db.commit()
    return agent_a, agent_b


async def test_check_promotions_promotes_entry_with_enough_citations(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Promotion candidate", entry_type="proposal", round=1,
    )
    # M = max(1, 2 // 3 + 1) = 1 — one distinct non-self citation is enough
    await bb.cite(run_id=run_id, citing_agent_id=agent_b,
                  entry_ids=[entry_id], round=2)

    promoted = await bb.check_promotions(run_id=run_id, current_round=2)

    assert len(promoted) == 1
    assert promoted[0].source_draft_id == entry_id

    confirmed = await bb.get_confirmed(run_id=run_id)
    assert len(confirmed) == 1


async def test_check_promotions_does_not_double_promote(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, agent_b = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    entry_id = await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Already promoted", entry_type="proposal", round=1,
    )
    await bb.cite(run_id=run_id, citing_agent_id=agent_b,
                  entry_ids=[entry_id], round=2)
    await bb.check_promotions(run_id=run_id, current_round=2)
    promoted_again = await bb.check_promotions(run_id=run_id, current_round=3)

    assert len(promoted_again) == 0


async def test_soft_delete_stale_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    # Post in round 2 (not round 1, so not exempt from deletion)
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Stale entry", entry_type="reply", round=2,
    )
    # decay_rounds=3, current_round=5: rounds_since_citation = 5-0 = 5 >= 3
    deleted = await bb.soft_delete_stale(
        run_id=run_id, current_round=5, decay_rounds=3
    )

    assert deleted == 1
    entries = await bb.read(run_id=run_id, query="stale", thread_id=thread_id)
    assert len(entries) == 0


async def test_soft_delete_exempts_round_1_entries(db) -> None:
    run_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    agent_a, _ = await _seed_two_agents(db, run_id, thread_id)

    bb = Blackboard(db)
    await bb.post(
        run_id=run_id, thread_id=thread_id, author_id=agent_a,
        content="Round 1 entry", entry_type="proposal", round=1,
    )
    # current_round=1: round-1 entries are exempt
    deleted = await bb.soft_delete_stale(
        run_id=run_id, current_round=1, decay_rounds=3
    )

    assert deleted == 0

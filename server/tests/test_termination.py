"""Unit tests for the TerminationEngine (PRD §6.6)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.market_hive.schemas import SwarmRunConfig
from server.market_hive.termination import TerminationEngine, TokenTracker


@pytest.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await _create_minimal_schema(conn)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection, None]:
    async with engine.connect() as conn:
        yield conn


async def _create_minimal_schema(conn: AsyncConnection) -> None:
    """Create only the tables TerminationEngine touches.

    The full SQLAlchemy metadata DDL currently stalls in this sandbox, while the
    engine's behavior only needs this small table set.
    """
    statements = [
        """
        CREATE TABLE swarm_runs (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            mode TEXT NOT NULL DEFAULT 'swarm',
            termination_reason TEXT,
            termination_round INTEGER,
            amendment_count INTEGER NOT NULL DEFAULT 0,
            token_usage TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            tools TEXT NOT NULL DEFAULT '[]',
            connections TEXT NOT NULL DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            capability_embedding TEXT
        )
        """,
        """
        CREATE TABLE contracts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            original_prompt TEXT NOT NULL,
            task_type TEXT NOT NULL,
            task_nature TEXT NOT NULL DEFAULT 'single',
            required_expertise TEXT NOT NULL DEFAULT '[]',
            complexity TEXT NOT NULL DEFAULT 'medium',
            confidence REAL NOT NULL DEFAULT 0.0,
            contract_embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            contract_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            required_expertise TEXT NOT NULL DEFAULT '[]',
            complexity TEXT NOT NULL DEFAULT 'medium',
            thread_embedding TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE draft_entries (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            round INTEGER NOT NULL,
            author_id TEXT NOT NULL,
            entry_type TEXT NOT NULL,
            content TEXT NOT NULL,
            content_embedding TEXT,
            reply_to TEXT,
            mention_agents TEXT NOT NULL DEFAULT '[]',
            is_visible BOOLEAN NOT NULL DEFAULT true,
            deleted_at TIMESTAMP,
            last_cited_round INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE confirmed_entries (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            source_draft_id TEXT,
            content TEXT NOT NULL,
            content_embedding TEXT,
            entry_type TEXT NOT NULL DEFAULT 'finding',
            citation_count INTEGER NOT NULL DEFAULT 0,
            round_confirmed INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE bids (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            contract_id TEXT,
            thread_id TEXT,
            agent_id TEXT NOT NULL,
            justification TEXT NOT NULL DEFAULT '',
            preliminary_score REAL NOT NULL DEFAULT 0.0,
            is_taker BOOLEAN NOT NULL DEFAULT false,
            is_observer BOOLEAN NOT NULL DEFAULT false,
            abstained BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for statement in statements:
        await conn.execute(text(statement))


async def _seed_run(conn: AsyncConnection) -> tuple[str, str, str]:
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, :prompt, :task_type)"
        ),
        {
            "id": contract_id,
            "run_id": run_id,
            "prompt": "analyze this",
            "task_type": "analysis",
        },
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :contract_id, :run_id, :title, :description)"
        ),
        {
            "id": thread_id,
            "contract_id": contract_id,
            "run_id": run_id,
            "title": "Main",
            "description": "main thread",
        },
    )
    await conn.commit()
    return run_id, contract_id, thread_id


async def _confirmed(
    conn: AsyncConnection,
    *,
    run_id: str,
    thread_id: str,
    content: str,
    entry_type: str = "finding",
    citation_count: int = 0,
    round_confirmed: int = 1,
) -> str:
    entry_id = str(uuid.uuid4())
    await conn.execute(
        text(
            """
            INSERT INTO confirmed_entries
                (id, run_id, thread_id, content, entry_type, citation_count, round_confirmed)
            VALUES
                (:id, :run_id, :thread_id, :content, :entry_type,
                 :citation_count, :round_confirmed)
            """
        ),
        {
            "id": entry_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "content": content,
            "entry_type": entry_type,
            "citation_count": citation_count,
            "round_confirmed": round_confirmed,
        },
    )
    await conn.commit()
    return entry_id


async def test_equilibrium_false_before_min_rounds(db: AsyncConnection) -> None:
    run_id, _, _ = await _seed_run(db)
    eng = TerminationEngine(db, min_rounds=3, k_consecutive=2)

    assert not await eng.check_equilibrium(run_id=run_id, current_round=2)


async def test_equilibrium_requires_quiet_consecutive_finding_rounds(db: AsyncConnection) -> None:
    run_id, _, thread_id = await _seed_run(db)
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="new finding",
        citation_count=2,
        round_confirmed=2,
    )
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="system note",
        entry_type="system",
        round_confirmed=3,
    )
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="anchor",
        entry_type="anchor",
        round_confirmed=4,
    )
    eng = TerminationEngine(db, min_rounds=2, k_consecutive=2, epsilon_entropy=0)

    assert not await eng.check_equilibrium(run_id=run_id, current_round=3)
    assert await eng.check_equilibrium(run_id=run_id, current_round=4)


async def test_equilibrium_respects_epsilon_entropy(db: AsyncConnection) -> None:
    run_id, _, thread_id = await _seed_run(db)
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="one tolerated finding",
        round_confirmed=2,
    )
    eng = TerminationEngine(db, min_rounds=2, k_consecutive=1, epsilon_entropy=1)

    assert await eng.check_equilibrium(run_id=run_id, current_round=2)


async def test_equilibrium_false_on_cold_start_empty_board(db: AsyncConnection) -> None:
    """Regression: an all-quiet run with nothing confirmed must not look converged.

    Before the cold-start guard the empty Confirmed board satisfied the quiet
    K-round window on the first check, ending the run at round 2 with no final
    answer. Equilibrium must stay False every round while the board is empty.
    """
    run_id, _, _ = await _seed_run(db)
    eng = TerminationEngine(db, min_rounds=3, k_consecutive=2, epsilon_entropy=0)

    for current_round in range(2, 11):
        assert not await eng.check_equilibrium(run_id=run_id, current_round=current_round)


async def test_equilibrium_true_after_confirmation_then_quiet_rounds(db: AsyncConnection) -> None:
    """A finding is confirmed, then the window goes quiet → converged with an answer."""
    run_id, _, thread_id = await _seed_run(db)
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="answer",
        citation_count=2,
        round_confirmed=3,
    )
    eng = TerminationEngine(db, min_rounds=3, k_consecutive=2, epsilon_entropy=0)

    # Round 4: the [3, 4] window still holds the round-3 confirmation → not yet.
    assert not await eng.check_equilibrium(run_id=run_id, current_round=4)
    # Round 5: the [4, 5] window is quiet and the board is non-empty → converged.
    assert await eng.check_equilibrium(run_id=run_id, current_round=5)


async def test_has_confirmed_findings_ignores_non_findings(db: AsyncConnection) -> None:
    run_id, _, thread_id = await _seed_run(db)
    eng = TerminationEngine(db)
    assert not await eng.has_confirmed_findings(run_id=run_id)

    # Anchors / system rows are not findings — the swarm has produced nothing yet.
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="anchor",
        entry_type="anchor",
        round_confirmed=1,
    )
    assert not await eng.has_confirmed_findings(run_id=run_id)

    await _confirmed(db, run_id=run_id, thread_id=thread_id, content="finding", round_confirmed=2)
    assert await eng.has_confirmed_findings(run_id=run_id)


async def test_select_final_answer_orders_by_citations_then_earliest_round(
    db: AsyncConnection,
) -> None:
    run_id, _, thread_id = await _seed_run(db)
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="later tied",
        citation_count=5,
        round_confirmed=4,
    )
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="earlier tied",
        citation_count=5,
        round_confirmed=2,
    )
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="anchor ignored",
        entry_type="anchor",
        citation_count=99,
        round_confirmed=1,
    )

    answer = await TerminationEngine(db).select_final_answer(run_id=run_id, thread_id=thread_id)

    assert answer is not None
    assert answer.content == "earlier tied"


async def test_format_output_omits_threads_without_findings(db: AsyncConnection) -> None:
    run_id, contract_id, thread_id = await _seed_run(db)
    empty_thread = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :contract_id, :run_id, :title, :description)"
        ),
        {
            "id": empty_thread,
            "contract_id": contract_id,
            "run_id": run_id,
            "title": "Empty",
            "description": "empty thread",
        },
    )
    await db.commit()
    await _confirmed(
        db,
        run_id=run_id,
        thread_id=thread_id,
        content="answer",
        citation_count=3,
        round_confirmed=2,
    )

    output = await TerminationEngine(db).format_output(
        run_id=run_id,
        termination_round=3,
        termination_reason="equilibrium",
    )

    assert set(output.answers) == {thread_id}
    assert output.answers[thread_id].content == "answer"
    assert len(output.confirmed_layer) == 1


async def test_complete_run_persists_reason_round_and_token_usage(db: AsyncConnection) -> None:
    run_id, _, _ = await _seed_run(db)
    tracker = TokenTracker(budget=5_000)
    tracker.record(input_tokens=100, output_tokens=50, model="gpt", agent_id="a", phase="round")

    await TerminationEngine(db).complete_run(
        run_id=run_id,
        termination_round=4,
        termination_reason="budget",
        tracker=tracker,
    )

    row = (
        (
            await db.execute(
                text(
                    "SELECT status, termination_reason, termination_round, token_usage "
                    "FROM swarm_runs WHERE id = :id"
                ),
                {"id": run_id},
            )
        )
        .mappings()
        .one()
    )
    usage = json.loads(row["token_usage"])
    assert row["status"] == "completed"
    assert row["termination_reason"] == "budget"
    assert row["termination_round"] == 4
    assert usage["used"] == 150
    assert usage["by_model"] == {"gpt": 150}


def test_token_tracker_can_be_disabled() -> None:
    tracker = TokenTracker(budget=100, min_turn_budget=50, enabled=False)

    tracker.record(input_tokens=10_000, output_tokens=10_000)

    assert tracker.used() == 0
    assert tracker.remaining() == 100
    assert not tracker.exhausted()
    assert tracker.can_start_turn()
    assert tracker.snapshot()["enabled"] is False


def test_termination_engine_from_config_disables_token_budget() -> None:
    config = SwarmRunConfig(prompt="p", enable_token_budget=False)
    # The DB connection is not touched by new_tracker(), so None is fine here.
    eng = TerminationEngine.from_config(None, config)

    tracker = eng.new_tracker()

    assert tracker.enabled is False

"""Unit tests for server.market_hive.metrics (consensus observability)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.llm.embeddings import cosine
from server.market_hive.metrics import compute_run_metrics


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


# Four fixture vectors: e1/e2 are a near-identical pair, e3/e4 are not close to
# anything in particular — used both to seed the DB and to independently
# compute the expected duplication metric (same formula, different code path).
_E1 = [1.0, 0.0]
_E2 = [1.0, 0.02]
_E3 = [0.0, 1.0]
_E4 = [1.0, 1.0]


async def _seed_fixture_run(db: AsyncConnection) -> tuple[str, str, str]:
    """2 agents; 1 thread; 4 draft entries (e1/e2 by a1, e3/e4 by a2 — e1/e2
    near-identical embeddings); citations: a2->e1 (r2), a2->e1 (r3), a1->e3
    (r2); e1 promoted r2; e4 soft-deleted; token_usage {'total': 9000};
    completed run. Returns (run_id, e1_id, e3_id)."""
    run_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    e1, e2, e3, e4 = (str(uuid.uuid4()) for _ in range(4))

    await db.execute(
        text(
            "INSERT INTO swarm_runs (id, status, mode, token_usage) "
            "VALUES (:id, 'completed', 'swarm', :usage)"
        ),
        {"id": run_id, "usage": json.dumps({"total": 9000})},
    )
    await db.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, 'p', 'analysis')"
        ),
        {"id": contract_id, "run_id": run_id},
    )
    await db.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, 'T', 'd')"
        ),
        {"id": thread_id, "cid": contract_id, "run_id": run_id},
    )
    for aid in ("a1", "a2"):
        await db.execute(
            text(
                "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
                "VALUES (:id, :id, 'd', 's', 'openai', 'gpt-4o')"
            ),
            {"id": aid},
        )
        await db.execute(
            text("INSERT INTO bids (id, run_id, agent_id, is_taker) VALUES (:id, :r, :a, true)"),
            {"id": str(uuid.uuid4()), "r": run_id, "a": aid},
        )

    for entry_id, author, vec, visible in (
        (e1, "a1", _E1, True),
        (e2, "a1", _E2, True),
        (e3, "a2", _E3, True),
        (e4, "a2", _E4, False),
    ):
        await db.execute(
            text(
                "INSERT INTO draft_entries "
                "(id, run_id, thread_id, round, author_id, entry_type, content, "
                " content_embedding, is_visible) "
                "VALUES (:id, :r, :t, 1, :a, 'proposal', 'c', :emb, :vis)"
            ),
            {
                "id": entry_id,
                "r": run_id,
                "t": thread_id,
                "a": author,
                "emb": json.dumps(vec),
                "vis": visible,
            },
        )

    for citer, cited, round_ in (("a2", e1, 2), ("a2", e1, 3), ("a1", e3, 2)):
        await db.execute(
            text(
                "INSERT INTO citations (id, run_id, citing_agent_id, cited_entry_id, round) "
                "VALUES (:id, :r, :citer, :cited, :round)"
            ),
            {"id": str(uuid.uuid4()), "r": run_id, "citer": citer, "cited": cited, "round": round_},
        )

    await db.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, source_draft_id, content, entry_type, "
            " citation_count, round_confirmed) "
            "VALUES (:id, :r, :t, :src, 'c', 'finding', 2, 2)"
        ),
        {"id": str(uuid.uuid4()), "r": run_id, "t": thread_id, "src": e1},
    )
    await db.commit()
    return run_id, e1, e3


def _expected_duplication() -> float:
    """Independently recompute mean-max-pairwise-cosine from the raw fixture
    vectors, so the test pins the *formula* rather than a hand-typed literal."""
    vecs = [_E1, _E2, _E3, _E4]
    max_per_entry = [
        max(cosine(v, other) for j, other in enumerate(vecs) if j != i)
        for i, v in enumerate(vecs)
    ]
    return sum(max_per_entry) / len(max_per_entry)


async def test_metrics_exact_values(db: AsyncConnection) -> None:
    run_id, _e1, _e3 = await _seed_fixture_run(db)
    m = await compute_run_metrics(db, run_id)

    assert m["duplication"] is not None
    assert abs(m["duplication"]["mean_max_pairwise_cosine"] - _expected_duplication()) < 1e-9

    # a1 authored e1 (2 citations received), a2 authored e3 (1 citation received):
    assert m["citations"]["total"] == 3
    assert abs(m["citations"]["gini_received"] - (1 / 6)) < 1e-6

    assert m["convergence"]["confirmed_per_round"] == {"2": 1}
    assert m["convergence"]["first_promotion_round"] == 2
    assert abs(m["convergence"]["evaporation_rate"] - 0.25) < 1e-9

    assert m["cost"]["tokens_total"] == 9000
    assert m["cost"]["tokens_per_confirmed_finding"] == 9000.0

    # feature-tolerant blocks with nothing to report in this fixture:
    assert m["contestation"] is None
    assert m["ratification"] is None


async def test_offline_embeddings_null_duplication_only(db: AsyncConnection) -> None:
    run_id, _e1, _e3 = await _seed_fixture_run(db)
    zero = json.dumps([0.0, 0.0])
    await db.execute(
        text("UPDATE draft_entries SET content_embedding = :z WHERE run_id = :r"),
        {"z": zero, "r": run_id},
    )
    await db.commit()

    m = await compute_run_metrics(db, run_id)
    assert m["duplication"] is None
    assert m["citations"] is not None
    assert m["convergence"] is not None


async def test_participation_block_reports_posts_and_abstention(db: AsyncConnection) -> None:
    run_id, _e1, _e3 = await _seed_fixture_run(db)
    m = await compute_run_metrics(db, run_id)

    assert m["participation"]["posts_by_agent"] == {"a1": 2, "a2": 2}
    assert m["participation"]["abstention_rate"] == pytest.approx(0.0)
    # No turn_log rows in this fixture — skip_rate still computes (table exists,
    # just empty) rather than being None; it degrades to 0.0.
    assert m["participation"]["skip_rate"] == pytest.approx(0.0)


async def test_contestation_present_when_disputes_exist(db: AsyncConnection) -> None:
    run_id, e1, _e3 = await _seed_fixture_run(db)
    confirmed_id = (
        await db.execute(
            text("SELECT id FROM confirmed_entries WHERE run_id = :r"), {"r": run_id}
        )
    ).scalar_one()
    await db.execute(
        text(
            "INSERT INTO disputes (id, run_id, disputing_agent_id, confirmed_entry_id, "
            " reason, round) VALUES (:id, :r, 'a2', :ce, 'stale', 3)"
        ),
        {"id": str(uuid.uuid4()), "r": run_id, "ce": confirmed_id},
    )
    await db.commit()

    m = await compute_run_metrics(db, run_id)
    assert m["contestation"] is not None
    assert m["contestation"]["disputes_total"] == 1


async def test_ratification_reads_set_column(db: AsyncConnection) -> None:
    run_id, _e1, _e3 = await _seed_fixture_run(db)
    ratification = {"approved": True, "round": 1, "approvals": 2, "voters": 2, "objections": []}
    await db.execute(
        text("UPDATE swarm_runs SET ratification = :r2 WHERE id = :r"),
        {"r2": json.dumps(ratification), "r": run_id},
    )
    await db.commit()

    m = await compute_run_metrics(db, run_id)
    assert m["ratification"] == ratification


async def test_no_confirmed_findings_nulls_tokens_per_finding(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await db.execute(
        text(
            "INSERT INTO swarm_runs (id, status, mode, token_usage) "
            "VALUES (:id, 'completed', 'swarm', :usage)"
        ),
        {"id": run_id, "usage": json.dumps({"total": 500})},
    )
    await db.commit()

    m = await compute_run_metrics(db, run_id)
    assert m["cost"]["tokens_total"] == 500
    assert m["cost"]["tokens_per_confirmed_finding"] is None
    assert m["duplication"] is None

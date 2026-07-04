"""Unit tests for the hardened TrustRegistry (PRD §6.7, 2026-07-04 hardening).

Replaces the earlier zero-sum share/observer-penalty tests entirely — those
encoded the brittleness this hardening removes (string-domain matching, an
evidence-agnostic flat delta, and observers taking a penalty for work they
never did). Covers the pure scoring math (``score_events``), event emission at
run end (absolute, idempotent, zero-events for observers), and the
similarity-weighted auction lookup + legacy-score cutover.
"""

from __future__ import annotations

import json
import random
import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.trust import (
    DEFAULT_TRUST,
    NoopTrustRegistry,
    TrustEvent,
    TrustRegistry,
    migrate_agent_trust_to_ledger,
    score_events,
    trust_for_all,
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


# ── seeding helpers ────────────────────────────────────────────────────────────


async def _seed_run(conn: AsyncConnection, run_id: str) -> None:
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.commit()


async def _seed_contract(
    conn: AsyncConnection,
    *,
    run_id: str,
    task_type: str = "analysis",
    embedding: list[float] | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type, contract_embedding) "
            "VALUES (:id, :run_id, :p, :t, :emb)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "p": "prompt",
            "t": task_type,
            "emb": json.dumps(embedding) if embedding is not None else None,
        },
    )
    await conn.commit()


async def _seed_thread(conn: AsyncConnection, *, run_id: str, thread_id: str) -> None:
    cid = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
            "VALUES (:id, :run_id, 'p', 'analysis')"
        ),
        {"id": cid, "run_id": run_id},
    )
    await conn.execute(
        text(
            "INSERT INTO threads (id, contract_id, run_id, title, description) "
            "VALUES (:id, :cid, :run_id, 'T', 'd')"
        ),
        {"id": thread_id, "cid": cid, "run_id": run_id},
    )
    await conn.commit()


async def _seed_agent(conn: AsyncConnection, *, agent_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
            "VALUES (:id, :id, 'd', 's', 'openai', 'gpt-4o')"
        ),
        {"id": agent_id},
    )
    await conn.commit()


async def _seed_confirmed_finding(
    conn: AsyncConnection,
    *,
    run_id: str,
    thread_id: str,
    author_id: str,
    citers: list[str] | None = None,
) -> str:
    """A confirmed finding traced to ``author_id`` via its source draft entry,
    optionally with citations recorded from ``citers`` (round 2). Returns the
    draft entry id."""
    draft_id = str(uuid.uuid4())
    await conn.execute(
        text(
            "INSERT INTO draft_entries "
            "(id, run_id, thread_id, round, author_id, entry_type, content) "
            "VALUES (:id, :run_id, :tid, 1, :author, 'proposal', 'c')"
        ),
        {"id": draft_id, "run_id": run_id, "tid": thread_id, "author": author_id},
    )
    await conn.execute(
        text(
            "INSERT INTO confirmed_entries "
            "(id, run_id, thread_id, source_draft_id, content, entry_type, "
            " citation_count, round_confirmed) "
            "VALUES (:id, :run_id, :tid, :src, 'c', 'finding', :cites, 2)"
        ),
        {
            "id": str(uuid.uuid4()),
            "run_id": run_id,
            "tid": thread_id,
            "src": draft_id,
            "cites": len(citers or []),
        },
    )
    for citer in citers or []:
        await conn.execute(
            text(
                "INSERT INTO citations (id, run_id, citing_agent_id, cited_entry_id, round) "
                "VALUES (:id, :run_id, :citer, :cited, 2)"
            ),
            {"id": str(uuid.uuid4()), "run_id": run_id, "citer": citer, "cited": draft_id},
        )
    await conn.commit()
    return draft_id


async def _trust_row(
    conn: AsyncConnection, *, agent_id: str, domain: str
) -> tuple[float, int] | None:
    row = (
        await conn.execute(
            text(
                "SELECT trust_score, runs_participated FROM agent_trust "
                "WHERE agent_id = :aid AND domain = :domain"
            ),
            {"aid": agent_id, "domain": domain},
        )
    ).fetchone()
    return (float(row[0]), int(row[1])) if row is not None else None


# ── Task 1: pure scoring math ──────────────────────────────────────────────────


def test_one_lucky_run_beats_prior_less_than_ten_solid_runs() -> None:
    one = [TrustEvent("finding_confirmed", 1.0, 1.0, None, "analysis", 0)]
    ten = [TrustEvent("finding_confirmed", 1.0, 1.0, None, "analysis", i) for i in range(10)]
    s1 = score_events(one, contract_embedding=None)
    s10 = score_events(ten, contract_embedding=None)
    assert 0.5 < s1 < s10 < 1.0  # shrinkage: bounded, evidence-scaled


def test_recency_decay_prefers_fresh_evidence() -> None:
    fresh_bad = [TrustEvent("entry_evaporated", 0.0, 0.4, None, "analysis", 0)] + [
        TrustEvent("finding_confirmed", 1.0, 1.0, None, "analysis", i + 1) for i in range(5)
    ]
    old_bad = [
        TrustEvent("finding_confirmed", 1.0, 1.0, None, "analysis", i) for i in range(5)
    ] + [TrustEvent("entry_evaporated", 0.0, 0.4, None, "analysis", 6)]
    assert score_events(old_bad, contract_embedding=None) > score_events(
        fresh_bad, contract_embedding=None
    )


def test_domain_similarity_gates_transfer() -> None:
    legal = TrustEvent("finding_confirmed", 1.0, 1.0, [1.0, 0.0], "legal", 0)
    ortho = TrustEvent("finding_confirmed", 1.0, 1.0, [0.0, 1.0], "pricing", 0)
    near = score_events([legal], contract_embedding=[1.0, 0.0])
    far = score_events([ortho], contract_embedding=[1.0, 0.0])
    assert near > 0.5 and abs(far - 0.5) < 1e-9  # orthogonal history = prior only


def test_bounds_hold_for_random_sequences() -> None:
    rng = random.Random(7)
    for _ in range(200):
        evs = [
            TrustEvent("x", rng.random(), rng.random() * 2, None, "d", i)
            for i in range(rng.randint(0, 30))
        ]
        assert 0.0 <= score_events(evs, contract_embedding=None) <= 1.0


# ── Task 2: event emission at run end ──────────────────────────────────────────


async def test_update_emits_absolute_events_not_shares(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    for aid in ("a1", "a2", "a3"):
        await _seed_agent(db, agent_id=aid)
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="a1", citers=["a2"]
    )
    await _seed_confirmed_finding(
        db, run_id=run_id, thread_id=thread_id, author_id="a2", citers=["a1"]
    )

    await TrustRegistry().update(run_id=run_id, takers=["a1", "a2"], observers=["a3"], db=db)

    kinds = (
        await db.execute(text("SELECT agent_id, kind FROM trust_events ORDER BY agent_id"))
    ).fetchall()
    # both takers got the same absolute credit (no zero-sum split):
    assert ("a1", "finding_confirmed") in kinds and ("a2", "finding_confirmed") in kinds
    assert ("a1", "citations_received") in kinds and ("a2", "citations_received") in kinds
    # observer produced no events at all:
    assert not [k for k in kinds if k[0] == "a3"]


async def test_update_is_idempotent(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    await _seed_agent(db, agent_id="a1")
    await _seed_confirmed_finding(db, run_id=run_id, thread_id=thread_id, author_id="a1")

    reg = TrustRegistry()
    await reg.update(run_id=run_id, takers=["a1"], observers=[], db=db)
    before = (await db.execute(text("SELECT COUNT(*) FROM trust_events"))).scalar_one()
    await reg.update(run_id=run_id, takers=["a1"], observers=[], db=db)
    after = (await db.execute(text("SELECT COUNT(*) FROM trust_events"))).scalar_one()
    assert before == after


async def test_entry_evaporated_event_recorded(db: AsyncConnection) -> None:
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    await _seed_agent(db, agent_id="a1")
    await db.execute(
        text(
            "INSERT INTO draft_entries "
            "(id, run_id, thread_id, round, author_id, entry_type, content, is_visible) "
            "VALUES (:id, :run_id, :tid, 1, 'a1', 'proposal', 'stale', false)"
        ),
        {"id": str(uuid.uuid4()), "run_id": run_id, "tid": thread_id},
    )
    await db.commit()

    await TrustRegistry().update(run_id=run_id, takers=["a1"], observers=[], db=db)

    row = (
        await db.execute(
            text(
                "SELECT outcome, weight FROM trust_events "
                "WHERE agent_id = 'a1' AND kind = 'entry_evaporated'"
            )
        )
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.0)
    assert row[1] == pytest.approx(0.4)


async def test_taker_with_no_activity_gets_no_events_but_no_error(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id)
    await _seed_agent(db, agent_id="ghost")

    await TrustRegistry().update(run_id=run_id, takers=["ghost"], observers=[], db=db)

    n = (
        await db.execute(text("SELECT COUNT(*) FROM trust_events WHERE agent_id = 'ghost'"))
    ).scalar_one()
    assert n == 0


async def test_no_contract_is_noop(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)  # no contract → no domain
    await _seed_agent(db, agent_id="a1")

    await TrustRegistry().update(run_id=run_id, takers=["a1"], observers=[], db=db)

    rows = (await db.execute(text("SELECT COUNT(*) FROM trust_events"))).scalar_one()
    assert rows == 0


async def test_noop_registry_records_nothing(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_contract(db, run_id=run_id)
    await _seed_agent(db, agent_id="a1")

    await NoopTrustRegistry().update(run_id=run_id, takers=["a1"], observers=["a1"], db=db)

    rows = (await db.execute(text("SELECT COUNT(*) FROM trust_events"))).scalar_one()
    assert rows == 0


async def test_cache_row_reflects_shrinkage_not_raw_delta(db: AsyncConnection) -> None:
    """The agent_trust cache is a full recompute (score_events), not an additive
    delta — one confirmed finding should land meaningfully above DEFAULT_TRUST
    but nowhere near a saturated score."""
    run_id, thread_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_thread(db, run_id=run_id, thread_id=thread_id)
    await _seed_agent(db, agent_id="a1")
    await _seed_confirmed_finding(db, run_id=run_id, thread_id=thread_id, author_id="a1")

    await TrustRegistry().update(run_id=run_id, takers=["a1"], observers=[], db=db)

    score, runs = await _trust_row(db, agent_id="a1", domain="analysis")  # type: ignore[misc]
    assert DEFAULT_TRUST < score < 1.0
    assert runs == 1


# ── Task 3: similarity-weighted lookup + cutover ──────────────────────────────


async def test_trust_for_all_similarity_near_vs_orthogonal(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)
    await _seed_agent(db, agent_id="near")
    await _seed_agent(db, agent_id="far")
    for aid, emb in (("near", [1.0, 0.0]), ("far", [0.0, 1.0])):
        await db.execute(
            text(
                "INSERT INTO trust_events "
                "(id, run_id, agent_id, kind, outcome, weight, domain_label, domain_embedding) "
                "VALUES (:id, :run_id, :aid, 'finding_confirmed', 1.0, 1.0, 'legal', :emb)"
            ),
            {"id": str(uuid.uuid4()), "run_id": run_id, "aid": aid, "emb": json.dumps(emb)},
        )
    await db.commit()

    scores = await trust_for_all(db, contract_embedding=[1.0, 0.0], domain_label="legal")
    assert scores["near"] > DEFAULT_TRUST
    assert scores["far"] == pytest.approx(DEFAULT_TRUST)


async def test_trust_for_all_offline_matches_by_label_only(db: AsyncConnection) -> None:
    await _seed_agent(db, agent_id="a1")
    for domain in ("legal", "pricing"):
        run_id = str(uuid.uuid4())
        await _seed_run(db, run_id)
        await db.execute(
            text(
                "INSERT INTO trust_events "
                "(id, run_id, agent_id, kind, outcome, weight, domain_label) "
                "VALUES (:id, :run_id, 'a1', 'finding_confirmed', 1.0, 1.0, :domain)"
            ),
            {"id": str(uuid.uuid4()), "run_id": run_id, "domain": domain},
        )
    await db.commit()

    scores = await trust_for_all(db, contract_embedding=None, domain_label="legal")
    # Only the 'legal' event counted — a single matching event, not two.
    expected = score_events(
        [TrustEvent("finding_confirmed", 1.0, 1.0, None, "legal", 0)], contract_embedding=None
    )
    assert scores["a1"] == pytest.approx(expected)


async def test_migrate_agent_trust_to_ledger_creates_legacy_prior(db: AsyncConnection) -> None:
    await _seed_agent(db, agent_id="veteran")
    await _seed_agent(db, agent_id="fresh")
    await db.execute(
        text(
            "INSERT INTO agent_trust (agent_id, domain, trust_score, runs_participated) "
            "VALUES ('veteran', 'legal', 0.8, 5)"
        )
    )
    await db.commit()

    await migrate_agent_trust_to_ledger(db)

    legacy = (
        await db.execute(
            text(
                "SELECT outcome, weight, run_id FROM trust_events "
                "WHERE agent_id = 'veteran' AND kind = 'legacy_prior'"
            )
        )
    ).fetchone()
    assert legacy is not None
    assert legacy[0] == pytest.approx(0.8)
    assert legacy[1] == pytest.approx(5.0)
    assert legacy[2] is None

    scores = await trust_for_all(db, contract_embedding=None, domain_label="legal")
    assert scores["veteran"] > scores.get("fresh", DEFAULT_TRUST)

    # Idempotent: calling again does not duplicate the legacy row.
    await migrate_agent_trust_to_ledger(db)
    n = (
        await db.execute(
            text(
                "SELECT COUNT(*) FROM trust_events "
                "WHERE agent_id = 'veteran' AND kind = 'legacy_prior'"
            )
        )
    ).scalar_one()
    assert n == 1

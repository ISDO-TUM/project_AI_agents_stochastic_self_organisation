"""Unit tests for the minimal Market Maker (PRD §6.1)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.market_maker import (
    MarketMaker,
    _ContractAnalysis,
    _extract_json,
    _usable_threads,
)
from server.market_hive.schemas import AmendmentSchema


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


async def _seed_run(conn: AsyncConnection, run_id: str) -> None:
    await conn.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
    await conn.commit()


@pytest.fixture(autouse=True)
def _offline_embeddings() -> Iterator[None]:
    """A deterministic embedding so no network call happens during persistence."""
    with patch(
        "server.market_hive.contract_source.embed_texts",
        new=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
    ):
        yield


# ── _extract_json ─────────────────────────────────────────────────────────────


def test_extract_json_plain() -> None:
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_with_fences_and_prose() -> None:
    raw = 'Sure! Here is the contract:\n```json\n{"task_type": "x"}\n```\nThanks.'
    assert _extract_json(raw) == {"task_type": "x"}


def test_extract_json_returns_none_when_absent() -> None:
    assert _extract_json("no json here") is None
    assert _extract_json("not even { broken") is None


# ── _ContractAnalysis coercion ────────────────────────────────────────────────


def test_analysis_coerces_messy_fields() -> None:
    a = _ContractAnalysis.model_validate(
        {
            "task_type": "legal_review",
            "required_expertise": ["contract law", "  ", "energy pricing"],
            "complexity": "EXTREME",  # invalid → medium
            "brief": "A brief.",
            "confidence": 5.0,  # out of range → clamped to 1.0
        }
    )
    assert a.required_expertise == ["contract law", "energy pricing"]
    assert a.complexity == "medium"
    assert a.confidence == 1.0


def test_analysis_expertise_string_becomes_list() -> None:
    a = _ContractAnalysis.model_validate({"required_expertise": "contract law"})
    assert a.required_expertise == ["contract law"]


# ── make_contract ─────────────────────────────────────────────────────────────


async def test_make_contract_uses_llm_decomposition(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)

    llm_json = json.dumps(
        {
            "task_type": "energy_contract_review",
            "required_expertise": ["contract law", "energy pricing", "financial risk"],
            "complexity": "high",
            "brief": "Assess whether the supplier may revise the energy price monthly.",
            "confidence": 0.7,
        }
    )
    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(return_value=(llm_json, [])),
    ):
        contract, threads = await mm.make_contract(
            "Can the energy price be modified each month?", run_id, db
        )

    assert contract.task_type == "energy_contract_review"
    assert contract.required_expertise == ["contract law", "energy pricing", "financial risk"]
    assert contract.complexity == "high"
    assert contract.confidence == pytest.approx(0.7)
    assert contract.contract_embedding == [0.1, 0.2, 0.3]
    # The verbatim question is preserved; the thread carries the scoped brief.
    assert contract.original_prompt == "Can the energy price be modified each month?"
    assert len(threads) == 1
    assert "supplier" in threads[0].description

    # Persisted to the DB, not just returned.
    row = (
        (
            await db.execute(
                text(
                    "SELECT task_type, required_expertise, confidence FROM contracts WHERE id = :id"
                ),
                {"id": contract.id},
            )
        )
        .mappings()
        .fetchone()
    )
    assert row is not None
    assert row["task_type"] == "energy_contract_review"
    assert json.loads(row["required_expertise"]) == [
        "contract law",
        "energy pricing",
        "financial risk",
    ]


async def test_make_contract_falls_back_on_llm_error(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)

    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(side_effect=RuntimeError("no api key")),
    ):
        contract, threads = await mm.make_contract("Some prompt", run_id, db)

    # Fallback semantics: untyped, single thread, zero confidence.
    assert contract.task_type == "analysis"
    assert contract.required_expertise == []
    assert contract.confidence == 0.0
    assert len(threads) == 1
    assert contract.original_prompt == "Some prompt"


async def test_make_contract_falls_back_on_unparseable_response(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)

    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(return_value=("I cannot help with that.", [])),
    ):
        contract, _ = await mm.make_contract("Some prompt", run_id, db)

    assert contract.task_type == "analysis"
    assert contract.confidence == 0.0


# ── multi-step decomposition ──────────────────────────────────────────────────


def _multi_analysis_json() -> str:
    return json.dumps(
        {
            "task_type": "vendor_evaluation",
            "task_nature": "multi",
            "required_expertise": ["contract law", "financial modeling", "IT security"],
            "complexity": "high",
            "brief": "Evaluate the vendor offer legally, financially and technically.",
            "confidence": 0.8,
            "threads": [
                {
                    "title": "Legal Review",
                    "description": "Assess the contract terms and liability clauses.",
                    "required_expertise": ["contract law"],
                    "complexity": "medium",
                },
                {
                    "title": "Financial Analysis",
                    "description": "Model the total cost of ownership over 5 years.",
                    "required_expertise": ["financial modeling"],
                    "complexity": "high",
                },
            ],
        }
    )


async def test_make_contract_multi_persists_all_threads(db: AsyncConnection) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)

    # Distinct vector per embedded text so each thread gets its own embedding.
    async def fake_embed(texts: list[str]) -> list[list[float]]:
        return [[float(i + 1), 0.0] for i in range(len(texts))]

    mm = MarketMaker()
    with (
        patch(
            "server.market_hive.market_maker.call_agent",
            new=AsyncMock(return_value=(_multi_analysis_json(), [])),
        ),
        patch(
            "server.market_hive.contract_source.embed_texts",
            new=AsyncMock(side_effect=fake_embed),
        ),
    ):
        contract, threads = await mm.make_contract("Evaluate this vendor offer", run_id, db)

    assert contract.task_nature == "multi"
    assert len(threads) == 2
    assert [t.title for t in threads] == ["Legal Review", "Financial Analysis"]
    assert threads[0].required_expertise == ["contract law"]
    assert threads[1].complexity == "high"
    # Contract and each thread carry their own (distinct) embeddings.
    assert contract.contract_embedding is not None
    assert threads[0].thread_embedding != threads[1].thread_embedding

    rows = (
        (
            await db.execute(
                text("SELECT title, required_expertise FROM threads WHERE run_id = :r"),
                {"r": run_id},
            )
        )
        .mappings()
        .all()
    )
    assert {r["title"] for r in rows} == {"Legal Review", "Financial Analysis"}
    nature = (
        await db.execute(text("SELECT task_nature FROM contracts WHERE run_id = :r"), {"r": run_id})
    ).scalar_one()
    assert nature == "multi"


async def test_make_contract_multi_with_one_thread_collapses_to_single(
    db: AsyncConnection,
) -> None:
    run_id = str(uuid.uuid4())
    await _seed_run(db, run_id)

    llm_json = json.dumps(
        {
            "task_type": "review",
            "task_nature": "multi",
            "required_expertise": ["law"],
            "brief": "A brief.",
            "confidence": 0.6,
            "threads": [{"title": "Only one", "description": "d"}],
        }
    )
    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(return_value=(llm_json, [])),
    ):
        contract, threads = await mm.make_contract("Some prompt", run_id, db)

    # One thread is just the contract itself — reconciled server-side.
    assert contract.task_nature == "single"
    assert len(threads) == 1
    assert threads[0].title == "Main Thread"


def test_usable_threads_reconciliation() -> None:
    # "single" ignores any planned threads.
    single = _ContractAnalysis.model_validate(
        {"task_nature": "single", "threads": [{"title": "a", "description": "b"}] * 3}
    )
    assert _usable_threads(single) == []

    # Junk items and empty threads are dropped; titles are defaulted.
    messy = _ContractAnalysis.model_validate(
        {
            "task_nature": "multi",
            "threads": [
                "not a dict",
                {"title": "", "description": ""},
                {"title": "", "description": "only description"},
                {"title": "Titled", "description": ""},
            ],
        }
    )
    usable = _usable_threads(messy)
    assert [t.title for t in usable] == ["Sub-task 1", "Titled"]
    assert usable[1].description == "Titled"  # empty description falls back to title

    # Thread count is capped at 4.
    many = _ContractAnalysis.model_validate(
        {
            "task_nature": "multi",
            "threads": [{"title": f"T{i}", "description": "d"} for i in range(6)],
        }
    )
    assert len(_usable_threads(many)) == 4


# ── cast_amendment_vote ───────────────────────────────────────────────────────


def _amendment() -> AmendmentSchema:
    from datetime import UTC, datetime

    return AmendmentSchema(
        id=str(uuid.uuid4()),
        run_id=str(uuid.uuid4()),
        proposing_agent_id="a1",
        thread_id=None,
        requested_domain="tax law",
        reason="No one covers tax implications.",
        created_at=datetime.now(UTC),
    )


async def test_cast_amendment_vote_approve_and_reject() -> None:
    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(return_value=("APPROVE", [])),
    ):
        assert await mm.cast_amendment_vote(_amendment()) == "approve"
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(return_value=("REJECT — the team covers this.", [])),
    ):
        assert await mm.cast_amendment_vote(_amendment()) == "reject"


async def test_cast_amendment_vote_failure_counts_as_reject() -> None:
    mm = MarketMaker()
    with patch(
        "server.market_hive.market_maker.call_agent",
        new=AsyncMock(side_effect=RuntimeError("no api key")),
    ):
        assert await mm.cast_amendment_vote(_amendment()) == "reject"

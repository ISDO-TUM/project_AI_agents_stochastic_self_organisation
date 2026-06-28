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
from server.market_hive.market_maker import MarketMaker, _ContractAnalysis, _extract_json


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

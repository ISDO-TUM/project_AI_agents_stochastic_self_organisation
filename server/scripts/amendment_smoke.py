"""Manual smoke test for the Contract Amendment engine.

Drives a propose → vote → approve lifecycle against an in-memory DB and prints
each step.

Embedding mode is adaptive:
  * If an OpenAI key is configured (``OPENAI_API_KEY`` in ``.env``), the two idle
    agents are embedded from their REAL natural-language descriptions and the
    recruiter computes the REAL thread embedding — a genuine semantic test.
  * Otherwise it falls back to deterministic 3-dim fake vectors so it still runs
    offline. Either way the on-topic finance agent is recruited and the off-topic
    gardening agent is excluded.

Run from the repo root:
    server/.venv/bin/python -m server.scripts.amendment_smoke
"""

import asyncio
import json
import uuid
from typing import Literal

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.llm.credentials import resolve_api_key
from server.llm.embeddings import embed_texts
from server.market_hive.amendment import (
    AmendmentEngine,
    EmbedderFn,
    make_auction_recruiter,
)
from server.market_hive.schemas import AmendmentSchema

# Idle (non-taker) agents the mini-auction can recruit. One is genuinely about
# finance (on-topic for the amendment), one is about something unrelated.
IDLE_AGENTS = {
    "FinanceQuant": (
        "Expert in financial modeling, discounted cash flow analysis, valuation, "
        "interest-rate risk and quantitative finance."
    ),
    "GardenBot": (
        "Specialist in organic vegetable gardening, soil composition, composting, "
        "and seasonal planting schedules."
    ),
}

# Deterministic fallback vectors (used only when no OpenAI key is configured).
_FAKE_THREAD_VEC = [1.0, 0.0, 0.0]
_FAKE_CAPABILITY = {"FinanceQuant": [1.0, 0.0, 0.0], "GardenBot": [0.0, 1.0, 0.0]}


async def _fake_thread_embedder(texts: list[str]) -> list[list[float]] | None:
    return [_FAKE_THREAD_VEC for _ in texts]


def _openai_key_available() -> bool:
    try:
        return bool(resolve_api_key("openai"))
    except Exception:
        return False


async def main() -> None:
    load_dotenv()
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)

    async with engine.connect() as db:
        # ── seed a run: contract, one thread, three takers ──────────────────
        run_id, contract_id, thread_id = (str(uuid.uuid4()) for _ in range(3))
        await db.execute(text("INSERT INTO swarm_runs (id) VALUES (:id)"), {"id": run_id})
        await db.execute(
            text(
                "INSERT INTO contracts (id, run_id, original_prompt, task_type) "
                "VALUES (:id, :r, 'Analyze this energy contract', 'analysis')"
            ),
            {"id": contract_id, "r": run_id},
        )
        await db.execute(
            text(
                "INSERT INTO threads (id, contract_id, run_id, title, description) "
                "VALUES (:id, :c, :r, 'Pricing Fairness', 'is the pricing fair')"
            ),
            {"id": thread_id, "c": contract_id, "r": run_id},
        )
        takers = []
        for name in ("Alpha", "Beta", "Gamma"):
            aid = str(uuid.uuid4())
            takers.append(aid)
            await db.execute(
                text(
                    "INSERT INTO agents (id, name, description, system_prompt, provider, model) "
                    "VALUES (:id, :n, 'd', 's', 'openai', 'gpt-4o')"
                ),
                {"id": aid, "n": name},
            )

        # ── pick embedding mode: real OpenAI when a key is present ───────────
        names = list(IDLE_AGENTS)
        capability: dict[str, list[float]] | None = None
        if _openai_key_available():
            real = await embed_texts([IDLE_AGENTS[n] for n in names])
            if real is not None:
                capability = dict(zip(names, real, strict=True))
        embedder: EmbedderFn
        if capability is not None:
            embedder = embed_texts  # recruiter computes the REAL thread embedding
            print("Embedding mode: REAL OpenAI embeddings\n")
        else:
            capability = _FAKE_CAPABILITY
            embedder = _fake_thread_embedder
            print("Embedding mode: deterministic fakes (no OPENAI_API_KEY)\n")

        for name in names:
            await db.execute(
                text(
                    "INSERT INTO agents "
                    "(id, name, description, system_prompt, provider, model, capability_embedding) "
                    "VALUES (:id, :n, :desc, 's', 'openai', 'gpt-4o', :emb)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "n": name,
                    "desc": IDLE_AGENTS[name],
                    "emb": json.dumps(capability[name]),
                },
            )
        await db.commit()

        eng = AmendmentEngine(db)

        # ── 1. a taker proposes an amendment ────────────────────────────────
        print("1. Alpha calls request_expertise('financial_modeling')")
        res = await eng.propose(
            run_id=run_id,
            proposing_agent_id=takers[0],
            thread_id=thread_id,
            domain="financial_modeling",
            reason="The DCF assumptions need a finance specialist to verify.",
            current_round=2,
            max_amendments=2,
        )
        print(f"   -> {res}")
        print(f"   pending amendments: {len(await eng.list_pending(run_id))}")

        # ── 2. end-of-round: orchestrator resolves it (fake votes) ──────────
        async def all_approve_taker(
            taker_id: str, amendment: AmendmentSchema
        ) -> Literal["approve"]:
            return "approve"

        async def mm_approve(amendment: AmendmentSchema) -> Literal["approve"]:
            return "approve"

        print("\n2. End of round — vote opens (3 takers + Market Maker):")
        # Real mini-auction recruiter — invites non-taker agents via AuctionEngine,
        # re-scores each against the new thread's embedding (finance in, garden out),
        # auto-bids the matches (LLM self-selection is the orchestrator's seam),
        # and selects takers.
        recruiter = make_auction_recruiter(db, exclude_agent_ids=takers, embedder=embedder)
        async for step in eng.process_pending(
            run_id=run_id,
            current_round=2,
            takers=takers,
            vote_collector=all_approve_taker,
            mm_vote=mm_approve,
            recruiter=recruiter,
        ):
            print(f"   SSE [{step.type}] {step.msg}")

        # ── 3. inspect the result ───────────────────────────────────────────
        threads = (
            (
                await db.execute(
                    text("SELECT title, required_expertise FROM threads WHERE run_id = :r"),
                    {"r": run_id},
                )
            )
            .mappings()
            .fetchall()
        )
        print("\n3. Threads now in the run:")
        for t in threads:
            print(f"   - {t['title']}  (expertise: {t['required_expertise']})")

        recruited = (
            await db.execute(
                text(
                    "SELECT a.name FROM bids b JOIN agents a ON a.id = b.agent_id "
                    "WHERE b.run_id = :r AND b.is_taker = true AND b.thread_id IS NOT NULL "
                    "ORDER BY a.name"
                ),
                {"r": run_id},
            )
        ).fetchall()
        print("\n   Recruited onto the amendment thread (thread-scoped mini-auction):")
        print(f"   - {[r[0] for r in recruited]}  (GardenBot excluded: off-topic)")

        confirmed = (
            await db.execute(
                text(
                    "SELECT content FROM confirmed_entries "
                    "WHERE run_id = :r AND entry_type = 'system' ORDER BY created_at"
                ),
                {"r": run_id},
            )
        ).fetchall()
        print("\n   SYSTEM entries on the Confirmed layer:")
        for c in confirmed:
            print(f"   - {c[0]}")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

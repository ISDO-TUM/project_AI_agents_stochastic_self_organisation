"""Manual smoke test for the Contract Amendment engine.

Drives a propose → vote → approve lifecycle against an in-memory DB and prints
each step. No API keys needed — taker/MM votes and the thread embedding are
injected fakes.

The two idle agents are given capability embeddings: Delta aligns with the new
thread's vector, Epsilon is orthogonal — so the thread-scoped mini-auction should
recruit Delta and exclude Epsilon.

Run from the repo root:
    server/.venv/bin/python -m server.scripts.amendment_smoke
"""

import asyncio
import json
import uuid
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from server.db.tables import metadata
from server.market_hive.amendment import AmendmentEngine, make_auction_recruiter
from server.market_hive.schemas import AmendmentSchema

# A made-up 3-dim "embedding space". The thread points along the first axis.
_THREAD_VEC = [1.0, 0.0, 0.0]
_DELTA_VEC = [1.0, 0.0, 0.0]  # on-topic   → cosine 1.0 (recruited)
_EPSILON_VEC = [0.0, 1.0, 0.0]  # off-topic → cosine 0.0 (excluded)


async def main() -> None:
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
        # Two idle (non-taker) agents the mini-auction can recruit onto the new
        # thread. Delta's embedding aligns with the thread; Epsilon's is orthogonal.
        for name, vec in (("Delta", _DELTA_VEC), ("Epsilon", _EPSILON_VEC)):
            await db.execute(
                text(
                    "INSERT INTO agents "
                    "(id, name, description, system_prompt, provider, model, capability_embedding) "
                    "VALUES (:id, :n, 'd', 's', 'openai', 'gpt-4o', :emb)"
                ),
                {"id": str(uuid.uuid4()), "n": name, "emb": json.dumps(vec)},
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

        async def thread_embedder(texts: list[str]) -> list[list[float]]:
            return [_THREAD_VEC for _ in texts]  # deterministic stand-in for embed_texts

        # Real mini-auction recruiter — invites non-taker agents via AuctionEngine,
        # re-scores each against the new thread's embedding (Delta in, Epsilon out),
        # auto-bids the matches (LLM self-selection is the orchestrator's seam),
        # and selects takers.
        recruiter = make_auction_recruiter(db, exclude_agent_ids=takers, embedder=thread_embedder)
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
        print(f"   - {[r[0] for r in recruited]}  (Epsilon excluded: off-topic embedding)")

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

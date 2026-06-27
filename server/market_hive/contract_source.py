"""Contract source — turns a raw prompt into a persisted contract + threads.

This is the orchestrator's input boundary (PRD §5.3). The real Market Maker
(an LLM call that decomposes a prompt into a typed contract and, for multi-step
tasks, several threads) is a separate, not-yet-built component
(``server/market_hive/market_maker.py``).

Until it lands, ``FallbackContractSource`` provides exactly what the orchestrator
needs to run: a single thread spanning the whole prompt, embedded so the auction
can score agents against it. It does **no** LLM work — it is the MM's own
documented failure fallback (``task_nature="single"``, ``confidence=0.0``).

The real ``MarketMaker`` will implement the same ``make_contract`` signature
(the ``ContractSource`` protocol in ``orchestrator.py``), so swapping it in is a
one-line change in the orchestrator and nothing else moves.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import embed_texts
from server.market_hive.schemas import ContractSchema, ThreadSchema

_FALLBACK_TASK_TYPE = "analysis"
_FALLBACK_THREAD_TITLE = "Main Thread"


def _now() -> datetime:
    return datetime.now(UTC)


class FallbackContractSource:
    """A no-LLM stand-in for the Market Maker.

    Produces one contract and one thread spanning the entire prompt, persists
    both, and returns them. A real prompt embedding is stored on both rows so the
    auction's cosine matching works before the LLM Market Maker exists.
    """

    async def make_contract(
        self, prompt: str, run_id: str, db: AsyncConnection
    ) -> tuple[ContractSchema, list[ThreadSchema]]:
        contract_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())
        now = _now()

        vecs = await embed_texts([prompt])
        embedding = vecs[0] if vecs else None
        embedding_json = json.dumps(embedding) if embedding is not None else None

        await db.execute(
            text(
                """
                INSERT INTO contracts
                    (id, run_id, original_prompt, task_type, task_nature,
                     required_expertise, complexity, confidence,
                     contract_embedding, created_at)
                VALUES (:id, :run_id, :prompt, :task_type, 'single',
                        '[]', 'medium', 0.0, :embedding, :now)
                """
            ),
            {
                "id": contract_id,
                "run_id": run_id,
                "prompt": prompt,
                "task_type": _FALLBACK_TASK_TYPE,
                "embedding": embedding_json,
                "now": now,
            },
        )
        await db.execute(
            text(
                """
                INSERT INTO threads
                    (id, contract_id, run_id, title, description,
                     required_expertise, complexity, thread_embedding, created_at)
                VALUES (:id, :contract_id, :run_id, :title, :description,
                        '[]', 'medium', :embedding, :now)
                """
            ),
            {
                "id": thread_id,
                "contract_id": contract_id,
                "run_id": run_id,
                "title": _FALLBACK_THREAD_TITLE,
                "description": prompt,
                "embedding": embedding_json,
                "now": now,
            },
        )
        await db.commit()

        thread = ThreadSchema(
            id=thread_id,
            contract_id=contract_id,
            run_id=run_id,
            title=_FALLBACK_THREAD_TITLE,
            description=prompt,
            required_expertise=[],
            complexity="medium",
            thread_embedding=embedding,
            created_at=now,
        )
        contract = ContractSchema(
            id=contract_id,
            run_id=run_id,
            original_prompt=prompt,
            task_type=_FALLBACK_TASK_TYPE,
            task_nature="single",
            required_expertise=[],
            complexity="medium",
            confidence=0.0,
            contract_embedding=embedding,
            threads=[thread],
            created_at=now,
        )
        return contract, [thread]

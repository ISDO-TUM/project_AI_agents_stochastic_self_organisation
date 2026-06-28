"""Contract source — turns a raw prompt into a persisted contract + threads.

This is the orchestrator's input boundary (PRD §5.3). Two implementations of the
``ContractSource`` protocol (see ``orchestrator.py``) live in this layer:

* ``FallbackContractSource`` (here) — a no-LLM stand-in that wraps the whole
  prompt in a single thread. It is the Market Maker's own documented failure
  fallback (``task_nature="single"``, ``confidence=0.0``) and is what the tests
  and the orchestrator default run on.
* ``MarketMaker`` (``market_maker.py``) — one LLM call that decomposes the prompt
  into a *typed, scoped* contract. It reuses :func:`persist_contract` here for
  the actual DB write and falls back to ``FallbackContractSource`` on any error.

Both persist through :func:`persist_contract`, so there is a single INSERT path;
the implementations differ only in how they derive the contract's fields.
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


async def persist_contract(
    db: AsyncConnection,
    *,
    run_id: str,
    prompt: str,
    task_type: str,
    required_expertise: list[str],
    complexity: str,
    confidence: float,
    description: str,
    embedding_text: str,
    task_nature: str = "single",
) -> tuple[ContractSchema, list[ThreadSchema]]:
    """Persist one contract + one thread and return their schemas.

    ``embedding_text`` is what the auction matches agents against — pass the
    richest available text (e.g. a scoped brief plus the required expertise) so
    cosine matching invites the right specialists. ``description`` is the thread
    body shown to agents. The contract and thread share the one embedding (v1 is
    single-thread). The single shared run connection is committed here.
    """
    contract_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    now = _now()

    vecs = await embed_texts([embedding_text])
    embedding = vecs[0] if vecs else None
    embedding_json = json.dumps(embedding) if embedding is not None else None
    expertise_json = json.dumps(required_expertise)

    await db.execute(
        text(
            """
            INSERT INTO contracts
                (id, run_id, original_prompt, task_type, task_nature,
                 required_expertise, complexity, confidence,
                 contract_embedding, created_at)
            VALUES (:id, :run_id, :prompt, :task_type, :task_nature,
                    :expertise, :complexity, :confidence, :embedding, :now)
            """
        ),
        {
            "id": contract_id,
            "run_id": run_id,
            "prompt": prompt,
            "task_type": task_type,
            "task_nature": task_nature,
            "expertise": expertise_json,
            "complexity": complexity,
            "confidence": confidence,
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
                    :expertise, :complexity, :embedding, :now)
            """
        ),
        {
            "id": thread_id,
            "contract_id": contract_id,
            "run_id": run_id,
            "title": _FALLBACK_THREAD_TITLE,
            "description": description,
            "expertise": expertise_json,
            "complexity": complexity,
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
        description=description,
        required_expertise=required_expertise,
        complexity=complexity,
        thread_embedding=embedding,
        created_at=now,
    )
    contract = ContractSchema(
        id=contract_id,
        run_id=run_id,
        original_prompt=prompt,
        task_type=task_type,
        task_nature=task_nature,
        required_expertise=required_expertise,
        complexity=complexity,
        confidence=confidence,
        contract_embedding=embedding,
        threads=[thread],
        created_at=now,
    )
    return contract, [thread]


class FallbackContractSource:
    """A no-LLM stand-in for the Market Maker.

    Produces one contract and one thread spanning the entire prompt, persists
    both, and returns them. A real prompt embedding is stored on both rows so the
    auction's cosine matching works before the LLM Market Maker exists.
    """

    async def make_contract(
        self, prompt: str, run_id: str, db: AsyncConnection
    ) -> tuple[ContractSchema, list[ThreadSchema]]:
        return await persist_contract(
            db,
            run_id=run_id,
            prompt=prompt,
            task_type=_FALLBACK_TASK_TYPE,
            required_expertise=[],
            complexity="medium",
            confidence=0.0,
            description=prompt,
            embedding_text=prompt,
        )

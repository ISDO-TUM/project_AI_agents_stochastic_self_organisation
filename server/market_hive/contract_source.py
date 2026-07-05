"""Contract source — turns a raw prompt into a persisted contract + threads.

This is the orchestrator's input boundary (PRD §5.3). Two implementations of the
``ContractSource`` protocol (see ``orchestrator.py``) live in this layer:

* ``FallbackContractSource`` (here) — a no-LLM stand-in that wraps the whole
  prompt in a single thread. It is the Market Maker's own documented failure
  fallback (``task_nature="single"``, ``confidence=0.0``) and is what the tests
  and the orchestrator default run on.
* ``MarketMaker`` (``market_maker.py``) — one LLM call that decomposes the prompt
  into a *typed, scoped* contract, and for multi-step tasks into several threads.
  It reuses :func:`persist_contract` here for the actual DB write and falls back
  to ``FallbackContractSource`` on any error.

Both persist through :func:`persist_contract`, so there is a single INSERT path;
the implementations differ only in how they derive the contract's fields and how
many :class:`ThreadSpec` they pass.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm.embeddings import embed_texts
from server.market_hive.schemas import ContractSchema, ThreadSchema

_FALLBACK_TASK_TYPE = "analysis"
_FALLBACK_THREAD_TITLE = "Main Thread"


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ThreadSpec:
    """One thread to persist: what agents see plus what the auction matches on.

    ``embedding_text`` is what cosine matching runs against — pass the richest
    available text (title + scoped description + expertise) so thread-level
    matching invites the right specialists.
    """

    title: str
    description: str
    embedding_text: str
    required_expertise: list[str] = field(default_factory=list)
    complexity: str = "medium"


async def persist_contract(
    db: AsyncConnection,
    *,
    run_id: str,
    prompt: str,
    task_type: str,
    required_expertise: list[str],
    complexity: str,
    confidence: float,
    embedding_text: str,
    threads: list[ThreadSpec],
) -> tuple[ContractSchema, list[ThreadSchema]]:
    """Persist one contract + its threads and return their schemas.

    ``task_nature`` is derived from the thread count (>1 → ``"multi"``), so it can
    never disagree with the persisted threads. All embeddings — the contract's and
    every thread's — are produced by ONE batched ``embed_texts`` call, deduplicated
    so the single-thread case (thread text == contract text) embeds once. A failed
    embedding call degrades to NULL embeddings rather than raising; the auction
    treats those inclusively. The single shared run connection is committed here.
    """
    if not threads:
        raise ValueError("persist_contract requires at least one ThreadSpec")

    contract_id = str(uuid.uuid4())
    task_nature = "multi" if len(threads) > 1 else "single"
    now = _now()

    texts = list(dict.fromkeys([embedding_text, *(t.embedding_text for t in threads)]))
    vecs = await embed_texts(texts)
    # strict=False: a short/None batch degrades to missing embeddings, never raises.
    vec_by_text = dict(zip(texts, vecs, strict=False)) if vecs else {}

    contract_embedding = vec_by_text.get(embedding_text)
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
            "expertise": json.dumps(required_expertise),
            "complexity": complexity,
            "confidence": confidence,
            "embedding": json.dumps(contract_embedding) if contract_embedding else None,
            "now": now,
        },
    )

    thread_schemas: list[ThreadSchema] = []
    for spec in threads:
        thread_id = str(uuid.uuid4())
        thread_embedding = vec_by_text.get(spec.embedding_text)
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
                "title": spec.title,
                "description": spec.description,
                "expertise": json.dumps(spec.required_expertise),
                "complexity": spec.complexity,
                "embedding": json.dumps(thread_embedding) if thread_embedding else None,
                "now": now,
            },
        )
        thread_schemas.append(
            ThreadSchema(
                id=thread_id,
                contract_id=contract_id,
                run_id=run_id,
                title=spec.title,
                description=spec.description,
                required_expertise=spec.required_expertise,
                complexity=spec.complexity,
                thread_embedding=thread_embedding,
                created_at=now,
            )
        )
    await db.commit()

    contract = ContractSchema(
        id=contract_id,
        run_id=run_id,
        original_prompt=prompt,
        task_type=task_type,
        task_nature=task_nature,
        required_expertise=required_expertise,
        complexity=complexity,
        confidence=confidence,
        contract_embedding=contract_embedding,
        threads=thread_schemas,
        created_at=now,
    )
    return contract, thread_schemas


class FallbackContractSource:
    """A no-LLM stand-in for the Market Maker.

    Produces one contract and one thread spanning the entire prompt, persists
    both, and returns them. A real prompt embedding is stored on both rows so the
    auction's cosine matching works even when the LLM Market Maker is unavailable.
    """

    async def make_contract(
        self,
        prompt: str,
        run_id: str,
        db: AsyncConnection,
        *,
        session_context: str | None = None,
    ) -> tuple[ContractSchema, list[ThreadSchema]]:
        embedding_text = f"{prompt}\n{session_context}" if session_context else prompt
        contract, threads = await persist_contract(
            db,
            run_id=run_id,
            prompt=prompt,
            task_type=_FALLBACK_TASK_TYPE,
            required_expertise=[],
            complexity="medium",
            confidence=0.0,
            embedding_text=embedding_text,
            threads=[
                ThreadSpec(
                    title=_FALLBACK_THREAD_TITLE,
                    description=prompt,
                    embedding_text=embedding_text,
                )
            ],
        )
        return contract, threads

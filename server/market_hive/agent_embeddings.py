"""Capability embeddings for agents — the vector the auction matches on.

An agent's *capability embedding* is a single vector summarizing what the agent
is good at (its name + description + system prompt). The auction scores it
against the contract embedding to decide who is invited and how bids rank
(PRD §6.2). It is computed when an agent is created or updated, and backfilled
for agents that predate this wiring.

Embedding is best-effort: when the embedding API is unavailable, the helpers
return ``None`` and the auction falls back to inclusive invitation, so a missing
key never blocks agent CRUD or a run.
"""

from __future__ import annotations

import json

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db.tables import agents
from server.llm.embeddings import embed_texts


def capability_text(name: str, description: str, system_prompt: str) -> str:
    """Compose the text an agent's capability embedding is computed from."""
    parts = [p.strip() for p in (name, description, system_prompt) if p and p.strip()]
    return "\n".join(parts)


async def compute_capability_embedding(
    name: str, description: str, system_prompt: str
) -> str | None:
    """Return the JSON-encoded capability embedding, or ``None`` if embedding fails."""
    vecs = await embed_texts([capability_text(name, description, system_prompt)])
    return json.dumps(vecs[0]) if vecs else None


async def backfill_capability_embeddings(db: AsyncConnection) -> int:
    """Fill ``capability_embedding`` for agents missing one. Returns the count filled."""
    rows = (
        (
            await db.execute(
                select(
                    agents.c.id,
                    agents.c.name,
                    agents.c.description,
                    agents.c.system_prompt,
                ).where(agents.c.capability_embedding.is_(None))
            )
        )
        .mappings()
        .all()
    )

    filled = 0
    for row in rows:
        embedding = await compute_capability_embedding(
            row["name"], row["description"], row["system_prompt"]
        )
        if embedding is None:
            continue
        await db.execute(
            update(agents).where(agents.c.id == row["id"]).values(capability_embedding=embedding)
        )
        filled += 1

    if filled:
        await db.commit()
    return filled

"""Blackboard — shared append-only coordination substrate for the ECSAS swarm."""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from server.db import record_message
from server.llm.embeddings import cosine, embed_texts
from server.market_hive.schemas import (
    ConfirmedEntrySchema,
    DraftEntrySchema,
)

_ZERO_EMBEDDING = json.dumps([0.0] * 1536)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(mapping: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row to a plain dict."""
    return dict(mapping._mapping)


class Blackboard:
    """Encapsulates all blackboard read/write operations for one DB connection."""

    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    # ── write ─────────────────────────────────────────────────────────────

    async def post(
        self,
        *,
        run_id: str,
        thread_id: str,
        author_id: str,
        content: str,
        entry_type: str,
        round: int,
        reply_to: str | None = None,
        mention_agents: list[str] | None = None,
        round_id: int | None = None,
    ) -> str:
        """Insert a draft entry. Returns the new entry_id.

        When mention_agents is non-empty a companion system entry is also
        inserted so the mention is visible as a card on the blackboard.
        """
        entry_id = str(uuid.uuid4())
        vecs = await embed_texts([content])
        embedding = json.dumps(vecs[0]) if vecs else _ZERO_EMBEDDING
        await self._db.execute(
            text(
                """
                INSERT INTO draft_entries
                    (id, run_id, thread_id, round, author_id, entry_type,
                     content, content_embedding, reply_to, mention_agents,
                     is_visible, last_cited_round)
                VALUES (:id, :run_id, :thread_id, :round, :author_id, :entry_type,
                        :content, :embedding, :reply_to, :mention_agents, 1, :round)
                """
            ),
            {
                "id": entry_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "round": round,
                "author_id": author_id,
                "entry_type": entry_type,
                "content": content,
                "embedding": embedding,
                "reply_to": reply_to,
                "mention_agents": json.dumps(mention_agents or []),
            },
        )
        if mention_agents:
            mention_list = ", ".join(f"@{aid[:8]}" for aid in mention_agents)
            await self._db.execute(
                text(
                    """
                    INSERT INTO draft_entries
                        (id, run_id, thread_id, round, author_id, entry_type,
                         content, content_embedding, reply_to, mention_agents,
                         is_visible, last_cited_round)
                    VALUES (:id, :run_id, :thread_id, :round, :author_id, 'system',
                            :content, :embedding, :reply_to, :mention_agents, 1, :round)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "round": round,
                    "author_id": author_id,
                    "content": f"mentioned: {mention_list}",
                    "embedding": _ZERO_EMBEDDING,
                    "reply_to": entry_id,
                    "mention_agents": json.dumps(mention_agents),
                },
            )
            if round_id is not None:
                for mentioned_id in mention_agents:
                    await record_message(
                        self._db,
                        round_id,
                        author_id,
                        mentioned_id,
                        "bb_mention",
                        content,
                    )
        await self._db.commit()
        return entry_id

    # ── read ──────────────────────────────────────────────────────────────

    async def top_k_visible(
        self,
        *,
        query: str,
        thread_id: str | None,
        run_id: str,
        k: int = 10,
    ) -> list[DraftEntrySchema]:
        """Return top-k visible draft entries scored by cosine(query, entry) x log(1+citations).

        Falls back to pure citation-count ranking when the embedding API is unavailable.
        """
        thread_clause = "AND de.thread_id = :thread_id" if thread_id is not None else ""
        params: dict[str, Any] = {"run_id1": run_id, "run_id2": run_id}
        if thread_id is not None:
            params["thread_id"] = thread_id

        result = await self._db.execute(
            text(
                f"""
                SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                       COALESCE(a.name, de.author_id) AS author_name,
                       de.entry_type, de.content, de.content_embedding,
                       de.reply_to, de.mention_agents, de.is_visible,
                       de.deleted_at, de.last_cited_round, de.created_at,
                       COALESCE(cc.cnt, 0) AS citation_count
                FROM draft_entries de
                LEFT JOIN agents a ON a.id = de.author_id
                LEFT JOIN (
                    SELECT cited_entry_id, COUNT(*) AS cnt
                    FROM   citations
                    WHERE  run_id = :run_id1
                    GROUP  BY cited_entry_id
                ) cc ON cc.cited_entry_id = de.id
                WHERE de.run_id = :run_id2 AND de.is_visible = true
                {thread_clause}
                """
            ),
            params,
        )
        rows = result.mappings().fetchall()

        query_vecs = await embed_texts([query])
        query_vec: list[float] | None = query_vecs[0] if query_vecs else None

        scored: list[tuple[float, DraftEntrySchema]] = []
        for row in rows:
            d = dict(row)
            raw_embedding = d.pop("content_embedding", None)
            citation_count = d["citation_count"]
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            entry = DraftEntrySchema(**d)

            weight = math.log(1.0 + citation_count)
            if query_vec and raw_embedding:
                try:
                    entry_vec: list[float] = json.loads(raw_embedding)
                    sim = cosine(query_vec, entry_vec)
                except Exception:
                    sim = 0.0
                score = sim * weight
            else:
                score = weight  # embedding unavailable — rank by citation weight only

            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:k]]

    async def read(
        self,
        *,
        run_id: str,
        query: str,
        thread_id: str | None,
        k: int = 10,
        agent_id: str | None = None,
    ) -> list[DraftEntrySchema]:
        """Return top-k entries via top_k_visible, with mention pinning applied.

        Mentioned entries are fetched via a separate query so they surface at
        position 0 regardless of their attention score — even if they would
        otherwise fall outside the top-k window.
        """
        if not agent_id:
            return await self.top_k_visible(query=query, thread_id=thread_id, run_id=run_id, k=k)

        # Fetch all entries that mention this agent (independent of score).
        thread_clause = "AND thread_id = :thread_id" if thread_id is not None else ""
        params: dict[str, Any] = {"run_id": run_id, "agent_id": f'%"{agent_id}"%'}
        if thread_id is not None:
            params["thread_id"] = thread_id

        result = await self._db.execute(
            text(
                f"""
                SELECT de.id, de.run_id, de.thread_id, de.round, de.author_id,
                       COALESCE(a.name, de.author_id) AS author_name,
                       de.entry_type, de.content,
                       de.reply_to, de.mention_agents, de.is_visible,
                       de.deleted_at, de.last_cited_round, de.created_at,
                       COALESCE(cc.cnt, 0) AS citation_count
                FROM draft_entries de
                LEFT JOIN agents a ON a.id = de.author_id
                LEFT JOIN (
                    SELECT cited_entry_id, COUNT(*) AS cnt
                    FROM   citations
                    WHERE  run_id = :run_id
                    GROUP  BY cited_entry_id
                ) cc ON cc.cited_entry_id = de.id
                WHERE de.run_id = :run_id AND de.is_visible = true
                  AND de.mention_agents LIKE :agent_id
                {thread_clause}
                """
            ),
            params,
        )
        rows = result.mappings().fetchall()
        pinned: list[DraftEntrySchema] = []
        for row in rows:
            d = dict(row)
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            entry = DraftEntrySchema(**d)
            if agent_id in entry.mention_agents:
                pinned.append(entry)

        if not pinned:
            return await self.top_k_visible(query=query, thread_id=thread_id, run_id=run_id, k=k)

        # Fill remaining slots with scored results, excluding already-pinned IDs.
        pinned_ids = {e.id for e in pinned}
        remaining = k - len(pinned)
        if remaining > 0:
            scored = await self.top_k_visible(
                query=query, thread_id=thread_id, run_id=run_id, k=k + len(pinned)
            )
            rest = [e for e in scored if e.id not in pinned_ids]
            return (pinned + rest)[:k]

        return pinned[:k]

    async def post_anchor(
        self,
        *,
        run_id: str,
        thread_id: str,
        content: str,
        round_confirmed: int = 0,
    ) -> str:
        """Insert a permanent anchor entry into confirmed_entries. Returns anchor_id."""
        anchor_id = str(uuid.uuid4())
        await self._db.execute(
            text(
                """
                INSERT INTO confirmed_entries
                    (id, run_id, thread_id, content, entry_type, citation_count, round_confirmed)
                VALUES (:id, :run_id, :thread_id, :content, 'anchor', 0, :round_confirmed)
                """
            ),
            {
                "id": anchor_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "content": content,
                "round_confirmed": round_confirmed,
            },
        )
        await self._db.commit()
        return anchor_id

    # ── Task 5 methods ────────────────────────────────────────────────────

    async def cite(
        self,
        *,
        run_id: str,
        citing_agent_id: str,
        entry_ids: list[str],
        round: int,
        citing_entry_id: str | None = None,
    ) -> dict[str, int]:
        """Record citation endorsements. Skips self-citations server-side."""
        cited = 0
        skipped_self = 0
        # De-duplicate while preserving order: an agent citing the same entry twice
        # in one call would otherwise trip the UNIQUE(agent, entry, round) constraint.
        for entry_id in dict.fromkeys(entry_ids):
            result = await self._db.execute(
                text("SELECT author_id FROM draft_entries WHERE id = :id"),
                {"id": entry_id},
            )
            row = result.mappings().fetchone()
            if row is None:
                continue
            if row["author_id"] == citing_agent_id:
                skipped_self += 1
                continue
            try:
                # SAVEPOINT per insert: on PostgreSQL a UNIQUE violation aborts the
                # whole transaction, so a plain try/except would poison every later
                # statement (and the final commit). A nested transaction lets us roll
                # back just this insert and keep the valid citations.
                async with self._db.begin_nested():
                    await self._db.execute(
                        text(
                            """
                            INSERT INTO citations
                                (id, run_id, citing_agent_id, cited_entry_id,
                                 citing_entry_id, round)
                            VALUES (:id, :run_id, :citing_agent_id, :cited_entry_id,
                                    :citing_entry_id, :round)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "run_id": run_id,
                            "citing_agent_id": citing_agent_id,
                            "cited_entry_id": entry_id,
                            "citing_entry_id": citing_entry_id,
                            "round": round,
                        },
                    )
                    await self._db.execute(
                        text("UPDATE draft_entries SET last_cited_round = :round WHERE id = :id"),
                        {"round": round, "id": entry_id},
                    )
                cited += 1
            except IntegrityError:
                # UNIQUE constraint: agent already cited this entry this round
                continue
        await self._db.commit()
        return {"cited": cited, "skipped_self": skipped_self}

    async def vote(
        self,
        *,
        run_id: str,
        voter_id: str,
        entry_id: str,
        thread_id: str,
    ) -> dict[str, bool]:
        """Record a cold-start vote. One vote per agent per entry (UNIQUE)."""
        try:
            await self._db.execute(
                text(
                    """
                    INSERT INTO votes
                        (id, run_id, voter_agent_id, voted_entry_id, thread_id, round)
                    VALUES (:id, :run_id, :voter_id, :entry_id, :thread_id, 1)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "voter_id": voter_id,
                    "entry_id": entry_id,
                    "thread_id": thread_id,
                },
            )
            await self._db.commit()
            return {"ok": True}
        except IntegrityError:
            # UNIQUE constraint: agent already voted for this entry
            return {"ok": False}

    async def get_confirmed(
        self,
        *,
        run_id: str,
        thread_id: str | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Return confirmed entries (anchors + promoted findings)."""
        thread_clause = "AND thread_id = :thread_id" if thread_id is not None else ""
        params: dict[str, Any] = {"run_id": run_id}
        if thread_id is not None:
            params["thread_id"] = thread_id

        result = await self._db.execute(
            text(
                f"""
                SELECT id, run_id, thread_id, source_draft_id, content,
                       entry_type, citation_count, round_confirmed, created_at
                FROM confirmed_entries
                WHERE run_id = :run_id {thread_clause}
                ORDER BY round_confirmed ASC, created_at ASC
                """
            ),
            params,
        )
        rows = result.mappings().fetchall()
        return [ConfirmedEntrySchema(**dict(row)) for row in rows]

    # ── Task 6 methods ────────────────────────────────────────────────────

    async def check_promotions(
        self,
        *,
        run_id: str,
        current_round: int,
        participants_by_thread: dict[str, int] | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Promote draft entries that have reached the citation threshold M.

        M = max(1, n_takers // 3 + 1) per thread, where n_takers is provided
        by the caller (auction.self_select result) rather than inferred from
        poster count. Already-promoted entries are skipped.
        Returns the list of newly promoted ConfirmedEntry objects.
        """
        result = await self._db.execute(
            text(
                "SELECT source_draft_id FROM confirmed_entries "
                "WHERE run_id = :run_id AND source_draft_id IS NOT NULL"
            ),
            {"run_id": run_id},
        )
        already_promoted = {row[0] for row in result.fetchall()}

        result = await self._db.execute(
            text(
                """
                SELECT de.id, de.thread_id, de.author_id, de.content,
                       de.entry_type, de.round, de.created_at,
                       COUNT(DISTINCT c.citing_agent_id) AS distinct_citers
                FROM draft_entries de
                JOIN citations c
                    ON c.cited_entry_id = de.id
                   AND c.citing_agent_id != de.author_id
                   AND c.run_id = de.run_id
                WHERE de.run_id = :run_id AND de.is_visible = true
                GROUP BY de.id
                """
            ),
            {"run_id": run_id},
        )
        rows = result.mappings().fetchall()

        newly_promoted: list[ConfirmedEntrySchema] = []
        for row in rows:
            entry_id = row["id"]
            if entry_id in already_promoted:
                continue
            n = (participants_by_thread or {}).get(row["thread_id"], 1)
            threshold = max(1, n // 3 + 1)
            if row["distinct_citers"] >= threshold:
                confirmed_id = str(uuid.uuid4())
                await self._db.execute(
                    text(
                        """
                        INSERT INTO confirmed_entries
                            (id, run_id, thread_id, source_draft_id, content,
                             entry_type, citation_count, round_confirmed)
                        VALUES (:id, :run_id, :thread_id, :source_draft_id, :content,
                                'finding', :citation_count, :round_confirmed)
                        """
                    ),
                    {
                        "id": confirmed_id,
                        "run_id": run_id,
                        "thread_id": row["thread_id"],
                        "source_draft_id": entry_id,
                        "content": row["content"],
                        "citation_count": row["distinct_citers"],
                        "round_confirmed": current_round,
                    },
                )
                confirmed_result = await self._db.execute(
                    text("SELECT * FROM confirmed_entries WHERE id = :id"),
                    {"id": confirmed_id},
                )
                confirmed_row = confirmed_result.mappings().fetchone()
                if confirmed_row is None:
                    continue
                newly_promoted.append(ConfirmedEntrySchema(**dict(confirmed_row)))

        if newly_promoted:
            await self._db.commit()
        return newly_promoted

    async def soft_delete_stale(
        self,
        *,
        run_id: str,
        current_round: int,
        decay_rounds: int = 3,
    ) -> int:
        """Soft-delete entries not cited for decay_rounds consecutive rounds.

        Round-1 entries are exempt when current_round < 2.
        Returns the count of entries deleted.
        """
        exempt_round1 = current_round < 2

        result = await self._db.execute(
            text(
                """
                UPDATE draft_entries
                SET is_visible = false, deleted_at = CURRENT_TIMESTAMP
                WHERE run_id = :run_id
                  AND is_visible = true
                  AND NOT (round = 1 AND :exempt)
                  AND (:current_round - COALESCE(last_cited_round, 0)) >= :decay_rounds
                """
            ),
            {
                "run_id": run_id,
                "exempt": exempt_round1,
                "current_round": current_round,
                "decay_rounds": decay_rounds,
            },
        )
        await self._db.commit()
        return result.rowcount or 0

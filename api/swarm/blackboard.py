"""Blackboard — shared append-only coordination substrate for the ECSAS swarm."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from api.swarm.schemas import (
    ConfirmedEntrySchema,
    DraftEntrySchema,
)

_ZERO_EMBEDDING = json.dumps([0.0] * 1536)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Blackboard:
    """Encapsulates all blackboard read/write operations for one DB connection."""

    def __init__(self, db: aiosqlite.Connection) -> None:
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
    ) -> str:
        """Insert a draft entry. Returns the new entry_id."""
        entry_id = str(uuid.uuid4())
        await self._db.execute(
            """
            INSERT INTO draft_entries
                (id, run_id, thread_id, round, author_id, entry_type,
                 content, content_embedding, reply_to, mention_agents,
                 is_visible, last_cited_round)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                entry_id,
                run_id,
                thread_id,
                round,
                author_id,
                entry_type,
                content,
                _ZERO_EMBEDDING,
                reply_to,
                json.dumps(mention_agents or []),
                round,
            ),
        )
        await self._db.commit()
        return entry_id

    # ── read ──────────────────────────────────────────────────────────────

    async def read(
        self,
        *,
        run_id: str,
        query: str,
        thread_id: str | None,
        k: int = 10,
        agent_id: str | None = None,
    ) -> list[DraftEntrySchema]:
        """Return top-k visible entries, sorted by citation_count DESC.

        Entries that mention agent_id are pinned to position 0.
        When all embeddings are zero (stub mode), ranking is by
        citation_count DESC, created_at ASC.
        """
        thread_clause = "AND de.thread_id = ?" if thread_id is not None else ""
        base_params: list[Any] = [run_id, run_id]
        if thread_id is not None:
            base_params.append(thread_id)

        async with self._db.execute(
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
                WHERE  run_id = ?
                GROUP  BY cited_entry_id
            ) cc ON cc.cited_entry_id = de.id
            WHERE de.run_id = ? AND de.is_visible = 1
            {thread_clause}
            ORDER BY citation_count DESC, de.created_at ASC
            """,
            base_params,
        ) as cur:
            rows = await cur.fetchall()

        entries: list[DraftEntrySchema] = []
        pinned: list[DraftEntrySchema] = []
        for row in rows:
            d = dict(row)
            d["mention_agents"] = json.loads(d["mention_agents"] or "[]")
            d["children"] = []
            entry = DraftEntrySchema(**d)
            if agent_id and agent_id in entry.mention_agents:
                pinned.append(entry)
            else:
                entries.append(entry)

        return (pinned + entries)[:k]

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
        for entry_id in entry_ids:
            async with self._db.execute(
                "SELECT author_id FROM draft_entries WHERE id=?", (entry_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                continue
            if row["author_id"] == citing_agent_id:
                skipped_self += 1
                continue
            try:
                await self._db.execute(
                    """
                    INSERT INTO citations
                        (id, run_id, citing_agent_id, cited_entry_id,
                         citing_entry_id, round)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        run_id,
                        citing_agent_id,
                        entry_id,
                        citing_entry_id,
                        round,
                    ),
                )
                await self._db.execute(
                    "UPDATE draft_entries SET last_cited_round=? WHERE id=?",
                    (round, entry_id),
                )
                cited += 1
            except sqlite3.IntegrityError:
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
                """
                INSERT INTO votes
                    (id, run_id, voter_agent_id, voted_entry_id, thread_id, round)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (str(uuid.uuid4()), run_id, voter_id, entry_id, thread_id),
            )
            await self._db.commit()
            return {"ok": True}
        except Exception:
            return {"ok": False}

    async def get_confirmed(
        self,
        *,
        run_id: str,
        thread_id: str | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Return confirmed entries (anchors + promoted findings)."""
        thread_clause = "AND thread_id = ?" if thread_id is not None else ""
        params: list[Any] = [run_id]
        if thread_id is not None:
            params.append(thread_id)

        async with self._db.execute(
            f"""
            SELECT id, run_id, thread_id, source_draft_id, content,
                   entry_type, citation_count, round_confirmed, created_at
            FROM confirmed_entries
            WHERE run_id = ? {thread_clause}
            ORDER BY round_confirmed ASC, created_at ASC
            """,
            params,
        ) as cur:
            rows = await cur.fetchall()

        return [ConfirmedEntrySchema(**dict(row)) for row in rows]

    # ── Task 6 methods ────────────────────────────────────────────────────

    async def check_promotions(
        self,
        *,
        run_id: str,
        current_round: int,
    ) -> list[ConfirmedEntrySchema]:
        """Promote draft entries that have reached the citation threshold M.

        M = max(1, n_distinct_posting_agents // 3 + 1) per thread.
        Already-promoted entries are skipped.
        Returns the list of newly promoted ConfirmedEntry objects.
        """
        async with self._db.execute(
            "SELECT source_draft_id FROM confirmed_entries "
            "WHERE run_id=? AND source_draft_id IS NOT NULL",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        already_promoted = {row[0] for row in rows}

        async with self._db.execute(
            "SELECT thread_id, COUNT(DISTINCT author_id) AS n "
            "FROM draft_entries WHERE run_id=? GROUP BY thread_id",
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()
        participants_by_thread: dict[str, int] = {row[0]: row[1] for row in rows}

        async with self._db.execute(
            """
            SELECT de.id, de.thread_id, de.author_id, de.content,
                   de.entry_type, de.round, de.created_at,
                   COUNT(DISTINCT c.citing_agent_id) AS distinct_citers
            FROM draft_entries de
            JOIN citations c
                ON c.cited_entry_id = de.id
               AND c.citing_agent_id != de.author_id
               AND c.run_id = de.run_id
            WHERE de.run_id = ? AND de.is_visible = 1
            GROUP BY de.id
            """,
            (run_id,),
        ) as cur:
            rows = await cur.fetchall()

        newly_promoted: list[ConfirmedEntrySchema] = []
        for row in rows:
            entry_id = row["id"]
            if entry_id in already_promoted:
                continue
            n = participants_by_thread.get(row["thread_id"], 1)
            threshold = max(1, n // 3 + 1)
            if row["distinct_citers"] >= threshold:
                confirmed_id = str(uuid.uuid4())
                await self._db.execute(
                    """
                    INSERT INTO confirmed_entries
                        (id, run_id, thread_id, source_draft_id, content,
                         entry_type, citation_count, round_confirmed)
                    VALUES (?, ?, ?, ?, ?, 'finding', ?, ?)
                    """,
                    (
                        confirmed_id,
                        run_id,
                        row["thread_id"],
                        entry_id,
                        row["content"],
                        row["distinct_citers"],
                        current_round,
                    ),
                )
                async with self._db.execute(
                    "SELECT * FROM confirmed_entries WHERE id=?", (confirmed_id,)
                ) as cur2:
                    confirmed_row = await cur2.fetchone()
                if confirmed_row is None:
                    continue  # should never happen: we just inserted this row
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

        await self._db.execute(
            """
            UPDATE draft_entries
            SET is_visible = 0, deleted_at = CURRENT_TIMESTAMP
            WHERE run_id = ?
              AND is_visible = 1
              AND NOT (round = 1 AND ?)
              AND (? - COALESCE(last_cited_round, 0)) >= ?
            """,
            (run_id, 1 if exempt_round1 else 0, current_round, decay_rounds),
        )
        await self._db.commit()
        async with self._db.execute("SELECT changes()") as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

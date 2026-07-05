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

# Promotion-time semantic dedup (contestable consensus): a draft crossing the
# citation threshold that is near-identical to an already-confirmed finding is
# merged into it instead of promoted separately, so the Confirmed layer doesn't
# accumulate paraphrased duplicates of the same point.
DEDUP_EPS = 0.92


def format_entries_digest(entries: list[DraftEntrySchema]) -> str:
    """One consistent rendering for board excerpts.

    Used both by the ``read_blackboard`` tool and by server-side prompt
    injection (rounds RAG context), so agents see the same format regardless of
    how the content reached them.
    """
    if not entries:
        return "No visible entries found."
    lines = [
        f"[{e.id[:8]}] {e.author_name} · Round {e.round} · {e.entry_type}"
        f" · ♡{e.citation_count}\n{e.content[:300]}"
        for e in entries
    ]
    return "\n\n---\n\n".join(lines)


async def carry_forward_findings(
    db: AsyncConnection, *, parent_run_id: str, child_run_id: str
) -> list[ConfirmedEntrySchema]:
    """Copy the parent run's ratified findings into the child run as anchors.

    Findings only (never the parent's anchors — no transitive re-anchoring);
    retracted findings are excluded when the ``status`` column exists
    (feature-detected). Carried anchors keep provenance via ``origin_run_id``
    = the run that ratified them (for a finding that was itself carried and
    re-ratified, that is the parent — provenance chains are walkable run by
    run, by design, not transitively collapsed).

    Carried rows reference the *parent's* ``thread_id`` — that FK is satisfied
    (``threads`` is not run-scoped by constraint) but the row belongs to
    another run; this is acceptable for anchors, which are context rather than
    thread content, and ``get_confirmed(thread_id=None)`` returns them.
    """
    status_filter = ""
    try:
        await db.execute(text("SELECT status FROM confirmed_entries LIMIT 1"))
        status_filter = "AND status = 'confirmed'"
    except Exception:
        await db.rollback()

    rows = (
        (
            await db.execute(
                text(
                    f"""
                SELECT id, thread_id, content, citation_count
                FROM confirmed_entries
                WHERE run_id = :parent AND entry_type = 'finding' {status_filter}
                ORDER BY citation_count DESC, round_confirmed ASC
                """
                ),
                {"parent": parent_run_id},
            )
        )
        .mappings()
        .all()
    )

    carried: list[ConfirmedEntrySchema] = []
    for row in rows:
        new_id = str(uuid.uuid4())
        await db.execute(
            text(
                """
                INSERT INTO confirmed_entries
                    (id, run_id, thread_id, source_draft_id, content, entry_type,
                     citation_count, round_confirmed, origin_run_id)
                VALUES (:id, :run_id, :thread_id, NULL, :content, 'anchor',
                        :cites, 0, :origin)
                """
            ),
            {
                "id": new_id,
                "run_id": child_run_id,
                "thread_id": row["thread_id"],
                "content": f"[carried] {row['content']}",
                "cites": row["citation_count"],
                "origin": parent_run_id,
            },
        )
        fetched = (
            (
                await db.execute(
                    text("SELECT * FROM confirmed_entries WHERE id = :id"), {"id": new_id}
                )
            )
            .mappings()
            .fetchone()
        )
        if fetched is None:
            raise RuntimeError(f"carried-forward entry {new_id!r} vanished after insert")
        carried.append(ConfirmedEntrySchema(**dict(fetched)))
    await db.commit()
    return carried


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row(mapping: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row to a plain dict."""
    return dict(mapping._mapping)


class Blackboard:
    """Encapsulates all blackboard read/write operations for one DB connection."""

    def __init__(self, db: AsyncConnection) -> None:
        self._db = db

    async def _resolve_entry_id(self, run_id: str, candidate: str | None) -> str | None:
        """Map a possibly-truncated id to a real ``draft_entries`` id in this run.

        ``read_blackboard`` renders ids as an 8-char prefix, so the LLM copies
        that prefix back into ``reply_to`` / ``cite``. Resolve an exact id first,
        then a *unique* prefix; return ``None`` when nothing matches uniquely so
        the caller can drop the reply linkage / skip the citation instead of
        letting a bad id raise a foreign-key violation (which aborts the whole
        transaction on PostgreSQL).
        """
        if not candidate:
            return None
        candidate = candidate.strip()
        if not candidate:
            return None

        exact = (
            (
                await self._db.execute(
                    text("SELECT id FROM draft_entries WHERE run_id = :run_id AND id = :id"),
                    {"run_id": run_id, "id": candidate},
                )
            )
            .mappings()
            .fetchone()
        )
        if exact is not None:
            return str(exact["id"])

        # Unique-prefix match handles the 8-char display truncation. Skip if the
        # candidate carries SQL LIKE wildcards (our ids never do) or is too short
        # to be discriminating.
        if len(candidate) < 4 or "%" in candidate or "_" in candidate:
            return None
        rows = (
            (
                await self._db.execute(
                    text("SELECT id FROM draft_entries WHERE run_id = :run_id AND id LIKE :prefix"),
                    {"run_id": run_id, "prefix": f"{candidate}%"},
                )
            )
            .mappings()
            .fetchall()
        )
        return str(rows[0]["id"]) if len(rows) == 1 else None

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
        claim: str | None = None,
        stance: str | None = None,
        stance_target: str | None = None,
        evidence: list[str] | None = None,
    ) -> str:
        """Insert a draft entry. Returns the new entry_id.

        When mention_agents is non-empty a companion system entry is also
        inserted so the mention is visible as a card on the blackboard.

        ``claim``/``stance``/``stance_target``/``evidence`` are the structured-
        contributions fields (all optional — a post with none of them behaves
        exactly as before). When ``claim`` is set, the embedding is computed
        from ``claim + content`` so retrieval favors the stated thesis.
        """
        # The LLM copies the 8-char display id back into reply_to; resolve it to
        # a real id (or drop the linkage) so a stale/truncated id can't FK-violate.
        reply_to = await self._resolve_entry_id(run_id, reply_to)
        entry_id = str(uuid.uuid4())
        embed_input = f"{claim}\n{content}" if claim else content
        vecs = await embed_texts([embed_input])
        embedding = json.dumps(vecs[0]) if vecs else _ZERO_EMBEDDING
        # Snapshot the author's display name at write time so the board stays
        # readable after the agent is deleted (the run outlives the canvas).
        author_name = (
            await self._db.execute(
                text("SELECT name FROM agents WHERE id = :id"), {"id": author_id}
            )
        ).scalar_one_or_none()
        await self._db.execute(
            text(
                """
                INSERT INTO draft_entries
                    (id, run_id, thread_id, round, author_id, author_name, entry_type,
                     content, content_embedding, reply_to, mention_agents,
                     is_visible, last_cited_round, claim, stance, stance_target,
                     evidence)
                VALUES (:id, :run_id, :thread_id, :round, :author_id, :author_name,
                        :entry_type, :content, :embedding, :reply_to, :mention_agents,
                        :is_visible, :round, :claim, :stance, :stance_target,
                        :evidence)
                """
            ),
            {
                "id": entry_id,
                "run_id": run_id,
                "thread_id": thread_id,
                "round": round,
                "author_id": author_id,
                "author_name": author_name,
                "entry_type": entry_type,
                "content": content,
                "embedding": embedding,
                "reply_to": reply_to,
                "mention_agents": json.dumps(mention_agents or []),
                "is_visible": True,
                "claim": claim,
                "stance": stance,
                "stance_target": stance_target,
                "evidence": json.dumps(evidence or []),
            },
        )
        if mention_agents:
            mention_list = ", ".join(f"@{aid[:8]}" for aid in mention_agents)
            await self._db.execute(
                text(
                    """
                    INSERT INTO draft_entries
                        (id, run_id, thread_id, round, author_id, author_name, entry_type,
                         content, content_embedding, reply_to, mention_agents,
                         is_visible, last_cited_round)
                    VALUES (:id, :run_id, :thread_id, :round, :author_id, :author_name,
                            'system', :content, :embedding, :reply_to, :mention_agents,
                            :is_visible, :round)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "round": round,
                    "author_id": author_id,
                    "author_name": author_name,
                    "content": f"mentioned: {mention_list}",
                    "embedding": _ZERO_EMBEDDING,
                    "reply_to": entry_id,
                    "mention_agents": json.dumps(mention_agents),
                    "is_visible": True,
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
                       COALESCE(de.author_name, a.name, de.author_id) AS author_name,
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
                       COALESCE(de.author_name, a.name, de.author_id) AS author_name,
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
        reasons: list[str] | None = None,
    ) -> dict[str, int]:
        """Record citation endorsements. Skips self-citations server-side.

        ``reasons`` (contestable consensus, P-02/P-03 accountability) is parallel
        to ``entry_ids``; when provided each citation row stores the caller's
        justification. Optional so existing callers keep working unchanged.
        """
        cited = 0
        skipped_self = 0
        reasons = reasons or []
        # Pair ids with reasons before de-duplicating — a plain dict.fromkeys on
        # entry_ids alone would discard which reason belongs to which id.
        paired: dict[str, str | None] = {}
        for i, raw_id in enumerate(entry_ids):
            if raw_id not in paired:
                paired[raw_id] = reasons[i] if i < len(reasons) else None
        for raw_id, reason in paired.items():
            # The LLM cites the 8-char display id; resolve it so a valid endorsement
            # is not silently dropped (and a stale id is skipped, not FK-violated).
            entry_id = await self._resolve_entry_id(run_id, raw_id)
            if entry_id is None:
                continue
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
                                 citing_entry_id, round, reason)
                            VALUES (:id, :run_id, :citing_agent_id, :cited_entry_id,
                                    :citing_entry_id, :round, :reason)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "run_id": run_id,
                            "citing_agent_id": citing_agent_id,
                            "cited_entry_id": entry_id,
                            "citing_entry_id": citing_entry_id,
                            "round": round,
                            "reason": reason,
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
            # UNIQUE (already voted) or FK (bad entry_id). On PostgreSQL the failed
            # statement aborts the whole transaction, so roll back before returning —
            # otherwise every later statement on this connection is rejected.
            await self._db.rollback()
            return {"ok": False}

    async def get_confirmed(
        self,
        *,
        run_id: str,
        thread_id: str | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Return confirmed entries (anchors + promoted findings).

        Includes contested/retracted rows too (auditability by construction —
        the client decides how to render each status); callers that need only
        the currently-live layer filter on ``status == "confirmed"``.
        """
        thread_clause = "AND thread_id = :thread_id" if thread_id is not None else ""
        params: dict[str, Any] = {"run_id": run_id}
        if thread_id is not None:
            params["thread_id"] = thread_id

        result = await self._db.execute(
            text(
                f"""
                SELECT id, run_id, thread_id, source_draft_id, content,
                       entry_type, citation_count, round_confirmed, created_at, status,
                       origin_run_id
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

    async def _find_dedup_target(
        self, *, run_id: str, thread_id: str, candidate_embedding: str | None
    ) -> str | None:
        """Return an existing non-retracted confirmed entry's id in this thread
        whose source draft embedding is >= DEDUP_EPS cosine-similar to the
        candidate, or None (no match, or embeddings unavailable — dedup is
        skipped entirely rather than ever blocking promotion)."""
        if not candidate_embedding:
            return None
        try:
            cand_vec = json.loads(candidate_embedding)
        except (json.JSONDecodeError, TypeError):
            return None
        if not cand_vec or not any(cand_vec):
            return None

        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT ce.id AS id, de.content_embedding AS content_embedding
                        FROM confirmed_entries ce
                        JOIN draft_entries de ON de.id = ce.source_draft_id
                        WHERE ce.run_id = :run_id AND ce.thread_id = :thread_id
                          AND ce.status != 'retracted'
                        """
                    ),
                    {"run_id": run_id, "thread_id": thread_id},
                )
            )
            .mappings()
            .fetchall()
        )
        for row in rows:
            raw = row["content_embedding"]
            if not raw:
                continue
            try:
                existing_vec = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if not existing_vec or not any(existing_vec):
                continue
            if cosine(cand_vec, existing_vec) >= DEDUP_EPS:
                return str(row["id"])
        return None

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

        Promotion-time semantic dedup (contestable consensus): a candidate
        whose embedding is near-identical (cosine >= DEDUP_EPS) to an already-
        confirmed, non-retracted entry in the same thread is merged into it
        instead of promoted separately — its citers reinforce the existing
        finding's ``citation_count`` and ``draft_entries.merged_into`` records
        the merge. Offline/missing embeddings skip the dedup check (never a
        promotion blocker).

        Returns the list of newly promoted (non-merged) ConfirmedEntry objects.
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
                       de.content_embedding, de.entry_type, de.round, de.created_at,
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
            if row["distinct_citers"] < threshold:
                continue

            merge_target = await self._find_dedup_target(
                run_id=run_id,
                thread_id=row["thread_id"],
                candidate_embedding=row["content_embedding"],
            )
            if merge_target is not None:
                await self._db.execute(
                    text("UPDATE draft_entries SET merged_into = :cid WHERE id = :eid"),
                    {"cid": merge_target, "eid": entry_id},
                )
                await self._db.execute(
                    text(
                        "UPDATE confirmed_entries SET citation_count = citation_count + :extra "
                        "WHERE id = :cid"
                    ),
                    {"extra": row["distinct_citers"], "cid": merge_target},
                )
                await self._db.execute(
                    text(
                        """
                        INSERT INTO draft_entries
                            (id, run_id, thread_id, round, author_id, entry_type,
                             content, content_embedding, is_visible, last_cited_round)
                        VALUES (:id, :run_id, :thread_id, :round, :author_id, 'system',
                                :content, :embedding, :is_visible, :round)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "thread_id": row["thread_id"],
                        "round": current_round,
                        "author_id": row["author_id"],
                        "content": "merged into an existing confirmed finding — reinforcing it",
                        "embedding": _ZERO_EMBEDDING,
                        "is_visible": True,
                    },
                )
                await self._db.commit()
                continue

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

    # ── Contestable consensus: dispute / contest / re-affirm ───────────────

    async def dispute(
        self,
        *,
        run_id: str,
        disputing_agent_id: str,
        confirmed_entry_id: str,
        reason: str,
        round: int,
    ) -> dict[str, Any]:
        """Record a mechanical challenge against a CONFIRMED entry.

        Rejects: a target that does not exist or is not currently 'confirmed'
        (``{"ok": False, "why": "not disputable"}``), self-dispute (the
        confirmed entry's source draft was authored by the disputer), and a
        second dispute from the same agent on the same entry (UNIQUE). Crossing
        the democratic threshold is decided separately by ``contest_check`` at
        end-of-round — this method only records the challenge.
        """
        row = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT ce.status AS status, de.author_id AS author_id
                        FROM confirmed_entries ce
                        LEFT JOIN draft_entries de ON de.id = ce.source_draft_id
                        WHERE ce.id = :id AND ce.run_id = :run_id
                        """
                    ),
                    {"id": confirmed_entry_id, "run_id": run_id},
                )
            )
            .mappings()
            .fetchone()
        )
        if row is None or row["status"] != "confirmed":
            return {"ok": False, "why": "not disputable"}
        if row["author_id"] is not None and row["author_id"] == disputing_agent_id:
            return {"ok": False, "why": "cannot dispute your own confirmed finding"}
        try:
            async with self._db.begin_nested():
                await self._db.execute(
                    text(
                        """
                        INSERT INTO disputes
                            (id, run_id, disputing_agent_id, confirmed_entry_id, reason, round)
                        VALUES
                            (:id, :run_id, :disputing_agent_id, :confirmed_entry_id,
                             :reason, :round)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "disputing_agent_id": disputing_agent_id,
                        "confirmed_entry_id": confirmed_entry_id,
                        "reason": reason,
                        "round": round,
                    },
                )
            await self._db.commit()
            return {"ok": True}
        except IntegrityError:
            await self._db.rollback()
            return {"ok": False, "why": "already disputed"}

    async def contest_check(
        self,
        *,
        run_id: str,
        current_round: int,
        participants_by_thread: dict[str, int] | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Flip over-threshold disputed CONFIRMED entries to 'contested'.

        Threshold M mirrors promotion: ``max(1, n_thread_participants // 3 + 1)``
        distinct disputers. Each flip also posts a system note on the board (the
        status column alone would be invisible to the agents) and is returned
        so the caller can emit a ``bb-contest`` step and count it toward
        equilibrium activity (a contest forces at least one more round).
        """
        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT id, thread_id FROM confirmed_entries
                        WHERE run_id = :run_id AND status = 'confirmed'
                        """
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .fetchall()
        )

        flipped: list[ConfirmedEntrySchema] = []
        for row in rows:
            entry_id = row["id"]
            thread_id = row["thread_id"]
            dispute_rows = (
                (
                    await self._db.execute(
                        text(
                            "SELECT DISTINCT disputing_agent_id, reason FROM disputes "
                            "WHERE confirmed_entry_id = :id"
                        ),
                        {"id": entry_id},
                    )
                )
                .mappings()
                .fetchall()
            )
            distinct_disputers = {d["disputing_agent_id"] for d in dispute_rows}
            if not distinct_disputers:
                continue
            n = (participants_by_thread or {}).get(thread_id, 1)
            threshold = max(1, n // 3 + 1)
            if len(distinct_disputers) < threshold:
                continue

            await self._db.execute(
                text("UPDATE confirmed_entries SET status = 'contested' WHERE id = :id"),
                {"id": entry_id},
            )
            reasons_excerpt = "; ".join(d["reason"][:80] for d in dispute_rows[:3])
            await self._db.execute(
                text(
                    """
                    INSERT INTO draft_entries
                        (id, run_id, thread_id, round, author_id, entry_type,
                         content, content_embedding, is_visible, last_cited_round)
                    VALUES (:id, :run_id, :thread_id, :round, :author_id, 'system',
                            :content, :embedding, :is_visible, :round)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "round": current_round,
                    "author_id": next(iter(distinct_disputers)),
                    "content": f"⚠ finding contested: {reasons_excerpt}",
                    "embedding": _ZERO_EMBEDDING,
                    "is_visible": True,
                },
            )
            refreshed = (
                (
                    await self._db.execute(
                        text("SELECT * FROM confirmed_entries WHERE id = :id"), {"id": entry_id}
                    )
                )
                .mappings()
                .fetchone()
            )
            if refreshed is not None:
                flipped.append(ConfirmedEntrySchema(**dict(refreshed)))

        if flipped:
            await self._db.commit()
        return flipped

    async def reaffirm_check(
        self,
        *,
        run_id: str,
        participants_by_thread: dict[str, int] | None = None,
    ) -> list[ConfirmedEntrySchema]:
        """Flip 'contested' entries back to 'confirmed' via new citations.

        A contested entry returns to confirmed once its source draft gains
        ``>= M`` distinct *new* citers (``citations.round`` after the round it
        was contested in) — the same democratic threshold that promoted and
        then contested it, so no single actor decides the outcome either way.
        """
        rows = (
            (
                await self._db.execute(
                    text(
                        """
                        SELECT id, thread_id, source_draft_id
                        FROM confirmed_entries
                        WHERE run_id = :run_id AND status = 'contested'
                          AND source_draft_id IS NOT NULL
                        """
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .fetchall()
        )

        reaffirmed: list[ConfirmedEntrySchema] = []
        for row in rows:
            entry_id = row["id"]
            thread_id = row["thread_id"]
            source_draft_id = row["source_draft_id"]
            contest_round_raw = (
                await self._db.execute(
                    text("SELECT MAX(round) FROM disputes WHERE confirmed_entry_id = :id"),
                    {"id": entry_id},
                )
            ).scalar()
            contest_round = int(contest_round_raw) if contest_round_raw is not None else 0

            new_citers = (
                await self._db.execute(
                    text(
                        """
                        SELECT COUNT(DISTINCT citing_agent_id) FROM citations
                        WHERE cited_entry_id = :source_draft_id AND round > :contest_round
                        """
                    ),
                    {"source_draft_id": source_draft_id, "contest_round": contest_round},
                )
            ).scalar_one()
            n = (participants_by_thread or {}).get(thread_id, 1)
            threshold = max(1, n // 3 + 1)
            if int(new_citers) < threshold:
                continue

            await self._db.execute(
                text("UPDATE confirmed_entries SET status = 'confirmed' WHERE id = :id"),
                {"id": entry_id},
            )
            author_id = (
                await self._db.execute(
                    text("SELECT author_id FROM draft_entries WHERE id = :id"),
                    {"id": source_draft_id},
                )
            ).scalar()
            if author_id is not None:
                await self._db.execute(
                    text(
                        """
                        INSERT INTO draft_entries
                            (id, run_id, thread_id, round, author_id, entry_type,
                             content, content_embedding, is_visible, last_cited_round)
                        VALUES (:id, :run_id, :thread_id, :round, :author_id, 'system',
                                :content, :embedding, :is_visible, :round)
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "round": contest_round + 1,
                        "author_id": author_id,
                        "content": "✓ contested finding re-affirmed by new citations",
                        "embedding": _ZERO_EMBEDDING,
                        "is_visible": True,
                    },
                )
            refreshed = (
                (
                    await self._db.execute(
                        text("SELECT * FROM confirmed_entries WHERE id = :id"), {"id": entry_id}
                    )
                )
                .mappings()
                .fetchone()
            )
            if refreshed is not None:
                reaffirmed.append(ConfirmedEntrySchema(**dict(refreshed)))

        if reaffirmed:
            await self._db.commit()
        return reaffirmed

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

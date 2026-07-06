"""ECSAS blackboard tools — registered alongside existing tools in the registry."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import text

from server.llm.embeddings import cosine, embed_texts
from server.market_hive.auction import AuctionEngine
from server.market_hive.blackboard import DEDUP_EPS, Blackboard, format_entries_digest
from server.tools.base import Tool

# Citation accountability (contestable consensus): reasons are required and
# capped per round so endorsement stays a deliberate, bounded act.
MAX_CITES_PER_ROUND = 3

# Posts are capped to keep the board terse. A round-1 proposal may run longer
# than a discussion reply, which should be a delta (a new point, disagreement,
# or new evidence) — not a restatement of the whole analysis.
MAX_PROPOSAL_CHARS = 3000
MAX_REPLY_CHARS = 1500

# Replies per taker per thread per round. A discussion turn is one delta, not
# an essay serialized across a dozen posts — without this cap a single agent
# can loop the tool-call machinery (up to max_iterations round-trips, see
# BaseLLMProvider) into a dozen-post turn on its own, which is exactly what
# stretched a real run to ~25 minutes despite only 4 takers and 9 rounds: one
# agent posted as many as 12 replies in a single round. Two is enough for the
# legitimate "reply to two different points" case the old unbounded design
# was protecting.
MAX_REPLIES_PER_ROUND = 2

# ── Input models ─────────────────────────────────────────────────────────────


class ReadBlackboardInput(BaseModel):
    query: str = Field(description="Natural language search query.")
    thread_id: str | None = Field(
        default=None,
        description="Thread to search. None searches across all threads.",
    )
    k: int = Field(default=10, ge=1, le=30, description="Max entries to return.")


class PostToBlackboardInput(BaseModel):
    content: str = Field(description="Full text of the post.")
    entry_type: Literal["proposal", "reply"] = Field(
        description="'proposal' for round-1 initial answers; 'reply' for later rounds."
    )
    thread_id: str = Field(description="Thread this post belongs to.")
    reply_to: str | None = Field(
        default=None, description="entry_id of parent post (null for top-level)."
    )
    mention_agents: list[str] = Field(
        default_factory=list,
        description="Agent IDs to notify. They see this entry pinned at position 0.",
    )
    claim: str | None = Field(
        default=None,
        description="One-sentence thesis of this post (<=200 chars). Strongly recommended.",
    )
    stance: Literal["new", "supports", "refutes", "refines"] | None = Field(
        default=None,
        description=(
            "Your position relative to an existing entry. Use stance_target for "
            "any value except 'new'."
        ),
    )
    stance_target: str | None = Field(default=None, description="entry_id the stance refers to.")
    evidence: list[str] = Field(
        default_factory=list,
        description="File names (from your attached files) backing the claim.",
    )


class CiteInput(BaseModel):
    entry_ids: list[str] = Field(description="IDs of entries you are building on or agreeing with.")
    reasons: list[str] = Field(
        description="One short justification per entry_id — why you endorse it. Required."
    )


class DisputeInput(BaseModel):
    entry_id: str = Field(description="ID of a CONFIRMED entry you can show is wrong.")
    reason: str = Field(description="Why this confirmed finding should be contested.")


class VoteInput(BaseModel):
    entry_id: str = Field(description="ID of a round-1 proposal to endorse.")


class GetConfirmedInput(BaseModel):
    thread_id: str | None = Field(
        default=None,
        description="Filter confirmed entries by thread. None returns all threads.",
    )


class ApproveSynthesisInput(BaseModel):
    pass


class ReviseSynthesisInput(BaseModel):
    reason: str = Field(description="What the draft answer misses or misrepresents.")


# ── Tool classes ──────────────────────────────────────────────────────────────


class ReadBlackboardTool(Tool):
    name = "read_blackboard"
    description = (
        "Query the blackboard for relevant entries. "
        "Returns top-k entries sorted by relevance and citation count. "
        "Entries mentioning you are always at position 0."
    )
    input_model = ReadBlackboardInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, ReadBlackboardInput):
            raise TypeError(f"Expected ReadBlackboardInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        agent_id: str | None = ctx.get("agent_id")

        bb = Blackboard(db)
        entries = await bb.read(
            run_id=run_id,
            query=validated_input.query,
            thread_id=validated_input.thread_id,
            k=validated_input.k,
            agent_id=agent_id,
        )
        return str(format_entries_digest(entries))


class PostToBlackboardTool(Tool):
    name = "post_to_blackboard"
    description = (
        "Write a proposal (round 1) or reply (rounds 2+) to the blackboard. "
        f"Replies are capped at {MAX_REPLIES_PER_ROUND} per taker per thread per round, and "
        "are rejected if near-identical to one of your own earlier posts in this thread — "
        "each one must be a single delta, never a restatement. "
        "Returns the new entry ID."
    )
    input_model = PostToBlackboardInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, PostToBlackboardInput):
            raise TypeError(f"Expected PostToBlackboardInput, got {type(validated_input).__name__}")

        # Length guard (terse board): reject before any DB work so the agent can
        # retry with a shorter delta or call stand_down. Replies are held to a
        # tighter ceiling than opening proposals.
        cap = (
            MAX_PROPOSAL_CHARS
            if validated_input.entry_type == "proposal"
            else MAX_REPLY_CHARS
        )
        if len(validated_input.content) > cap:
            return (
                f'{{"error": "post too long ({len(validated_input.content)} chars > '
                f'{cap} limit) — shorten to a single delta (one new point, '
                f'disagreement, or new evidence), or call stand_down if you have '
                f'nothing material to add."}}'
            )

        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        author_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 1)
        # The orchestrator assigns the thread for this turn; trust it over the LLM's
        # argument, which may be a mangled/hallucinated id and would FK-violate.
        thread_id: str = ctx.get("thread_id") or validated_input.thread_id

        # A "reply" with no reply_to has nothing to thread under — the Draft
        # board's nesting and the graph view's reply edges both key off this,
        # so a missing one silently orphans the post instead of failing loudly.
        # Returned as a tool result (not raised) so the agent can see it and
        # retry with reply_to set, same as FilesTool's not-found message.
        if validated_input.entry_type == "reply" and not validated_input.reply_to:
            return (
                '{"error": "reply_to is required when entry_type is \'reply\' — '
                'specify the entry_id you are responding to."}'
            )

        # Stance sanity (structured contributions): anything but "new" must
        # point at a real entry, and refuting/refining yourself is meaningless.
        # Rejected as a tool-result error (the reply_to pattern) so the agent
        # can see it and retry — never a hard gate that blocks posting outright.
        stance = validated_input.stance
        stance_target: str | None = validated_input.stance_target
        if stance and stance != "new":
            if not stance_target:
                return '{"error": "stance requires stance_target (the entry_id it refers to)."}'
            # The LLM copies the 8-char id shown in read_blackboard's digest
            # ("[{id[:8]}] ..."), not the full UUID — resolve it the same way
            # reply_to and cite() already do, or every stance post gets rejected.
            resolved_target = await Blackboard(db).resolve_entry_id(run_id, stance_target)
            if resolved_target is None:
                return '{"error": "stance_target does not match any entry id."}'
            stance_target = resolved_target
            target_author = (
                await db.execute(
                    text("SELECT author_id FROM draft_entries WHERE id = :id"),
                    {"id": stance_target},
                )
            ).scalar()
            if target_author is None:
                return '{"error": "stance_target does not match any entry id."}'
            if stance in ("refutes", "refines") and target_author == author_id:
                return f'{{"error": "you cannot {stance} your own entry."}}'
        else:
            stance_target = None

        # Evidence: keep only refs that exist in the agent's attached files
        # (base name before any #anchor); unknown refs are dropped with a
        # warning, not rejected — agents may also cite general knowledge.
        files: dict[str, str] = ctx.get("files") or {}
        kept: list[str] = []
        dropped: list[str] = []
        for ref in validated_input.evidence:
            (kept if ref.split("#", 1)[0] in files else dropped).append(ref)

        claim = validated_input.claim[:200] if validated_input.claim else None

        # One opening stake per taker per thread, ever (PRD §9.3): 'proposal' is
        # conceptually round-1-only ("'proposal' for round-1 initial answers;
        # 'reply' for later rounds" — see the field's own description above),
        # so scoping this to the CURRENT round only blocked the case where an
        # agent calls post_to_blackboard(entry_type='proposal') twice in the
        # same turn (the tool-call loop allows up to 20 iterations) — it did
        # nothing to stop the same agent choosing 'proposal' again in round 2,
        # 3, etc., which is just as much a duplicate opening stake, not a reply.
        # 'reply' used to be uncapped by count (only by length) on the theory that
        # a single turn legitimately replying to two different points isn't the
        # proposal-spam bug above. In practice, nothing stopped the same taker
        # from looping post_to_blackboard many times in one turn — one agent hit
        # 12 replies in a single round in a real run, turning a 4-taker/9-round
        # run into a ~25 minute one. MAX_REPLIES_PER_ROUND bounds that per
        # taker/thread/round; two is still enough for the legitimate two-points
        # case.
        if validated_input.entry_type == "proposal":
            existing = (
                await db.execute(
                    text(
                        "SELECT id FROM draft_entries WHERE run_id = :run_id "
                        "AND thread_id = :thread_id AND author_id = :author_id "
                        "AND entry_type = 'proposal' LIMIT 1"
                    ),
                    {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "author_id": author_id,
                    },
                )
            ).scalar()
            if existing is not None:
                return (
                    '{"error": "You already posted your opening proposal for this thread — '
                    "do not post another. Use cite(...) on others' proposals, or post a "
                    'reply (entry_type=\\"reply\\") if you have something new to add."}'
                )
        elif validated_input.entry_type == "reply":
            reply_count = (
                await db.execute(
                    text(
                        "SELECT COUNT(*) FROM draft_entries WHERE run_id = :run_id "
                        "AND thread_id = :thread_id AND author_id = :author_id "
                        "AND entry_type = 'reply' AND round = :round"
                    ),
                    {
                        "run_id": run_id,
                        "thread_id": thread_id,
                        "author_id": author_id,
                        "round": round_,
                    },
                )
            ).scalar_one()
            if reply_count >= MAX_REPLIES_PER_ROUND:
                return (
                    f'{{"error": "you already posted {reply_count} replies on this thread '
                    f'this round (cap: {MAX_REPLIES_PER_ROUND}) — that is enough for one round. '
                    'Call stand_down(reason) if you have nothing further, or cite(...) an '
                    'existing point instead of posting again."}'
                )

            # Semantic self-dedup: the count cap above stops a *volume* blowout
            # in one round, but not a taker re-litigating the same clause round
            # after round in slightly different words (the chronic pattern that
            # keeps a thread from ever going quiet for check_equilibrium).
            # Scoped to this taker's OWN prior posts in this thread only — two
            # different agents independently landing on the same point is the
            # citation/promotion signal working as intended, not something to
            # suppress. Reuses DEDUP_EPS, the same cosine threshold the
            # confirmed-entry clustering already uses for "same finding,
            # different phrasing" (see blackboard.py's _find_dedup_target).
            # Fails open (embeddings unavailable ⇒ no check) like every other
            # embedding consumer in this codebase — never blocks a post just
            # because the embedding API had a bad moment.
            embed_input = (
                f"{validated_input.claim}\n{validated_input.content}"
                if validated_input.claim
                else validated_input.content
            )
            candidate_vecs = await embed_texts([embed_input])
            candidate_vec = candidate_vecs[0] if candidate_vecs else None
            if candidate_vec and any(candidate_vec):
                prior_embeddings = (
                    await db.execute(
                        text(
                            "SELECT content_embedding FROM draft_entries WHERE run_id = :run_id "
                            "AND thread_id = :thread_id AND author_id = :author_id "
                            "AND entry_type = 'reply'"
                        ),
                        {
                            "run_id": run_id,
                            "thread_id": thread_id,
                            "author_id": author_id,
                        },
                    )
                ).scalars().all()
                for raw in prior_embeddings:
                    if not raw:
                        continue
                    try:
                        prior_vec = json.loads(raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if (
                        prior_vec
                        and any(prior_vec)
                        and cosine(candidate_vec, prior_vec) >= DEDUP_EPS
                    ):
                        return (
                            '{"error": "this reply is near-identical (semantic similarity check) '
                            "to one of your own earlier posts on this thread — you are restating, "
                            "not adding a delta. Call cite(...) on your earlier point if you still "
                            'endorse it, or stand_down(reason) if you have nothing further."}'
                        )

        bb = Blackboard(db)
        entry_id = await bb.post(
            run_id=run_id,
            thread_id=thread_id,
            author_id=author_id,
            content=validated_input.content,
            entry_type=validated_input.entry_type,
            round=round_,
            reply_to=validated_input.reply_to,
            mention_agents=validated_input.mention_agents,
            claim=claim,
            stance=stance,
            stance_target=stance_target,
            evidence=kept,
        )
        if dropped:
            return (
                f'{{"entry_id": "{entry_id}", "warning": "unknown evidence refs '
                f'dropped: {", ".join(dropped)}"}}'
            )
        return f'{{"entry_id": "{entry_id}"}}'


class CiteTool(Tool):
    name = "cite"
    description = (
        "Endorse entries you are building on or agree with. "
        "ONLY call for entries you genuinely support — "
        "express disagreement through reply content, not citation. "
        f"Capped at {MAX_CITES_PER_ROUND} per round; each entry_id needs its own reason."
    )
    input_model = CiteInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, CiteInput):
            raise TypeError(f"Expected CiteInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        citing_agent_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 2)
        citing_entry_id: str | None = ctx.get("citing_entry_id")

        ids = validated_input.entry_ids
        reasons = [r.strip() for r in validated_input.reasons]
        if len(reasons) != len(ids) or any(not r for r in reasons):
            return (
                '{"error": "provide one non-empty reason per entry_id — '
                'citations must be justified."}'
            )

        # The cap is per agent per round across however many cite() calls that
        # round makes, not just this list — count what already landed first so
        # a second call in the same turn cannot bypass it.
        already = (
            await db.execute(
                text(
                    "SELECT COUNT(*) FROM citations "
                    "WHERE run_id = :rid AND citing_agent_id = :aid AND round = :rnd"
                ),
                {"rid": run_id, "aid": citing_agent_id, "rnd": round_},
            )
        ).scalar_one()
        remaining = max(0, MAX_CITES_PER_ROUND - already)
        capped = len(ids) > remaining
        ids, reasons = ids[:remaining], reasons[:remaining]

        bb = Blackboard(db)
        result = await bb.cite(
            run_id=run_id,
            citing_agent_id=citing_agent_id,
            entry_ids=ids,
            round=round_,
            citing_entry_id=citing_entry_id,
            reasons=reasons,
        )
        note = ', "note": "cap of 3 reached — extra ids skipped"' if capped else ""
        return f'{{"cited": {result["cited"]}, "skipped_self": {result["skipped_self"]}{note}}}'


class VoteTool(Tool):
    name = "vote"
    description = (
        "Endorse a round-1 proposal during the cold-start vote sub-round. "
        "Use only between rounds 1 and 2. "
        "Votes initialize confidence scores — they are NOT promotion signals."
    )
    input_model = VoteInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, VoteInput):
            raise TypeError(f"Expected VoteInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        voter_id: str = ctx["agent_id"]
        thread_id: str = ctx["thread_id"]

        bb = Blackboard(db)
        result = await bb.vote(
            run_id=run_id,
            voter_id=voter_id,
            entry_id=validated_input.entry_id,
            thread_id=thread_id,
        )
        return f'{{"ok": {str(result["ok"]).lower()}}}'


class DisputeTool(Tool):
    name = "dispute"
    description = (
        "Mechanically challenge a CONFIRMED finding you can show is wrong. "
        "Only confirmed entries are disputable — this is not for prose "
        "disagreement (use reply content for that). One dispute per agent per "
        "entry; it takes the same threshold M as promotion to contest a finding."
    )
    input_model = DisputeInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, DisputeInput):
            raise TypeError(f"Expected DisputeInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        disputing_agent_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 2)

        bb = Blackboard(db)
        result = await bb.dispute(
            run_id=run_id,
            disputing_agent_id=disputing_agent_id,
            confirmed_entry_id=validated_input.entry_id,
            reason=validated_input.reason,
            round=round_,
        )
        if result["ok"]:
            return '{"ok": true}'
        return f'{{"ok": false, "why": "{result.get("why", "rejected")}"}}'


class GetConfirmedTool(Tool):
    name = "get_confirmed"
    description = (
        "Retrieve the Confirmed layer: permanent anchors and promoted findings. "
        "Use at the start of each round to orient yourself on ratified knowledge."
    )
    input_model = GetConfirmedInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, GetConfirmedInput):
            raise TypeError(f"Expected GetConfirmedInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]

        bb = Blackboard(db)
        entries = await bb.get_confirmed(run_id=run_id, thread_id=validated_input.thread_id)
        if not entries:
            return "No confirmed entries yet."

        lines = []
        for e in entries:
            badge = "📌" if e.entry_type == "anchor" else "✅"
            lines.append(
                f"{badge} [{e.id[:8]}] Round {e.round_confirmed} · ♡{e.citation_count}"
                f"\n{e.content[:300]}"
            )
        return "\n\n---\n\n".join(lines)


class ApproveSynthesisTool(Tool):
    name = "approve_synthesis"
    description = "Approve the draft final answer as a faithful summary of the confirmed findings."
    input_model = ApproveSynthesisInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        ctx = context or {}
        ctx["ratification_votes"][ctx["agent_id"]] = None
        return '{"ok": true}'


class ReviseSynthesisTool(Tool):
    name = "revise_synthesis"
    description = (
        "Reject the draft final answer, stating specifically what is missing or "
        "misrepresented relative to the confirmed findings."
    )
    input_model = ReviseSynthesisInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, ReviseSynthesisInput):
            raise TypeError(f"Expected ReviseSynthesisInput, got {type(validated_input).__name__}")
        ctx = context or {}
        ctx["ratification_votes"][ctx["agent_id"]] = validated_input.reason
        return '{"ok": true}'


# ── Auction tools (record bids/abstentions via the AuctionEngine) ────────────


class RequestExpertiseInput(BaseModel):
    domain: str = Field(description="Expertise the contract lacks, e.g. 'financial_modeling'.")
    reason: str = Field(description="Why this expertise gap matters for the thread.")
    thread_id: str = Field(description="The thread that needs the expertise.")


class RequestExpertiseTool(Tool):
    name = "request_expertise"
    description = (
        "Propose that the contract needs additional expertise the current team "
        "cannot provide. Opens a majority vote among takers + the Market Maker; "
        "if approved, a new thread is created and agents are recruited for it. "
        "Bounded by max_amendments per run — use only for genuine gaps."
    )
    input_model = RequestExpertiseInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, RequestExpertiseInput):
            raise TypeError(f"Expected RequestExpertiseInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        proposing_agent_id: str = ctx["agent_id"]
        current_round: int = ctx.get("round", 1)
        max_amendments: int = ctx.get("max_amendments", 2)

        from server.market_hive.amendment import AmendmentEngine

        engine = AmendmentEngine(db)
        result = await engine.propose(
            run_id=run_id,
            proposing_agent_id=proposing_agent_id,
            thread_id=validated_input.thread_id,
            domain=validated_input.domain,
            reason=validated_input.reason,
            current_round=current_round,
            max_amendments=max_amendments,
        )
        return f'{{"amendment_id": "{result["amendment_id"]}", "status": "{result["status"]}"}}'


class SubmitBidInput(BaseModel):
    justification: str = Field(description="Your reasoning for participating.")
    thread_id: str | None = Field(
        default=None,
        description=(
            "The thread's bracketed id, e.g. \"3f9a...\" — never its title. "
            "None for a contract-level bid."
        ),
    )


class AbstainInput(BaseModel):
    reason: str = Field(description="Why you are opting out.")
    thread_id: str | None = Field(
        default=None,
        description=(
            "The thread's bracketed id, e.g. \"3f9a...\" — never its title. "
            "None for full contract abstention."
        ),
    )


class StandDownInput(BaseModel):
    reason: str = Field(
        description="Why you have nothing material left to add on this thread."
    )
    thread_id: str | None = Field(
        default=None,
        description="The thread you are standing down from. Defaults to your current thread.",
    )


class SubmitBidTool(Tool):
    name = "submit_bid"
    description = "Commit to taking a contract or thread. Call during the auction phase."
    input_model = SubmitBidInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, SubmitBidInput):
            raise TypeError(f"Expected SubmitBidInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        agent_id: str = ctx["agent_id"]
        contract_id: str | None = ctx.get("contract_id")
        # The orchestrator passes the invitation's preliminary_score for this agent.
        preliminary_score: float = ctx.get("preliminary_score", 0.0)

        engine = AuctionEngine(db)
        thread_id = await engine.resolve_thread_id(
            contract_id=contract_id, thread_id=validated_input.thread_id
        )
        await engine.record_bid(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=thread_id,
            justification=validated_input.justification,
            preliminary_score=preliminary_score,
        )
        return f'{{"ok": true, "preliminary_score": {preliminary_score}}}'


class AbstainTool(Tool):
    name = "abstain"
    description = "Opt out of a contract or thread. Call during the auction phase."
    input_model = AbstainInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, AbstainInput):
            raise TypeError(f"Expected AbstainInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        agent_id: str = ctx["agent_id"]
        contract_id: str | None = ctx.get("contract_id")

        engine = AuctionEngine(db)
        thread_id = await engine.resolve_thread_id(
            contract_id=contract_id, thread_id=validated_input.thread_id
        )
        await engine.record_abstention(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=thread_id,
            reason=validated_input.reason,
        )
        return '{"ok": true}'


class StandDownTool(Tool):
    name = "stand_down"
    description = (
        "Declare you have NOTHING MATERIAL left to add on this thread — no new "
        "point, disagreement, or evidence. You will be skipped in later rounds of "
        "this thread. When every taker has stood down (or gone silent), the run "
        "ends. Use this instead of restating points already made."
    )
    input_model = StandDownInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, StandDownInput):
            raise TypeError(f"Expected StandDownInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        agent_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 1)
        # Trust the orchestrator-assigned thread over the LLM's arg (same rule as
        # post_to_blackboard), falling back to the tool arg only if unset.
        thread_id: str | None = ctx.get("thread_id") or validated_input.thread_id
        if not thread_id:
            return '{"error": "stand_down needs a thread_id."}'

        from server.market_hive.stand_down import record_stand_down

        await record_stand_down(
            db,
            run_id=run_id,
            agent_id=agent_id,
            thread_id=thread_id,
            round=round_,
            reason=validated_input.reason,
        )
        return '{"ok": true}'


# ── self-registration ─────────────────────────────────────────────────────────
# The engine registers its own tools with the shared registry. Importing this
# module (via ``server.market_hive`` at app startup) is enough to make the
# blackboard/auction tools available; the shared registry never imports the engine.
def _register() -> None:
    from server.tools.registry import register

    for tool in (
        ReadBlackboardTool(),
        PostToBlackboardTool(),
        CiteTool(),
        VoteTool(),
        DisputeTool(),
        GetConfirmedTool(),
        ApproveSynthesisTool(),
        ReviseSynthesisTool(),
        RequestExpertiseTool(),
        SubmitBidTool(),
        AbstainTool(),
        StandDownTool(),
    ):
        register(tool)


_register()

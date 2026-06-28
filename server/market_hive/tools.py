"""ECSAS blackboard tools — registered alongside existing tools in the registry."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from server.market_hive.auction import AuctionEngine
from server.market_hive.blackboard import Blackboard
from server.tools.base import Tool

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


class CiteInput(BaseModel):
    entry_ids: list[str] = Field(description="IDs of entries you are building on or agreeing with.")


class VoteInput(BaseModel):
    entry_id: str = Field(description="ID of a round-1 proposal to endorse.")


class GetConfirmedInput(BaseModel):
    thread_id: str | None = Field(
        default=None,
        description="Filter confirmed entries by thread. None returns all threads.",
    )


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
        if not entries:
            return "No visible entries found."

        lines = []
        for e in entries:
            lines.append(
                f"[{e.id[:8]}] {e.author_name} · Round {e.round} · {e.entry_type}"
                f" · ♡{e.citation_count}\n{e.content[:300]}"
            )
        return "\n\n---\n\n".join(lines)


class PostToBlackboardTool(Tool):
    name = "post_to_blackboard"
    description = (
        "Write a proposal (round 1) or reply (rounds 2+) to the blackboard. "
        "Returns the new entry ID."
    )
    input_model = PostToBlackboardInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, PostToBlackboardInput):
            raise TypeError(f"Expected PostToBlackboardInput, got {type(validated_input).__name__}")
        ctx = context or {}
        db = ctx["db"]
        run_id: str = ctx["run_id"]
        author_id: str = ctx["agent_id"]
        round_: int = ctx.get("round", 1)
        # The orchestrator assigns the thread for this turn; trust it over the LLM's
        # argument, which may be a mangled/hallucinated id and would FK-violate.
        thread_id: str = ctx.get("thread_id") or validated_input.thread_id

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
        )
        return f'{{"entry_id": "{entry_id}"}}'


class CiteTool(Tool):
    name = "cite"
    description = (
        "Endorse entries you are building on or agree with. "
        "ONLY call for entries you genuinely support — "
        "express disagreement through reply content, not citation."
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

        bb = Blackboard(db)
        result = await bb.cite(
            run_id=run_id,
            citing_agent_id=citing_agent_id,
            entry_ids=validated_input.entry_ids,
            round=round_,
            citing_entry_id=citing_entry_id,
        )
        return f'{{"cited": {result["cited"]}, "skipped_self": {result["skipped_self"]}}}'


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
        description="Thread to bid on. None for contract-level bid.",
    )


class AbstainInput(BaseModel):
    reason: str = Field(description="Why you are opting out.")
    thread_id: str | None = Field(
        default=None,
        description="Thread to abstain from. None for full contract abstention.",
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
        await engine.record_bid(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=validated_input.thread_id,
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
        await engine.record_abstention(
            run_id=run_id,
            agent_id=agent_id,
            contract_id=contract_id,
            thread_id=validated_input.thread_id,
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
        GetConfirmedTool(),
        RequestExpertiseTool(),
        SubmitBidTool(),
        AbstainTool(),
    ):
        register(tool)


_register()

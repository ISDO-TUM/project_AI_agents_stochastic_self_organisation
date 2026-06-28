"""Per-phase agent prompts for the swarm (PRD §9).

Each phase contributes a system suffix (appended to the agent's own system
prompt) and a user message built from the live contract/thread state. Keeping
them here keeps the orchestrator focused on sequencing.

Note: the Confirmed layer starts empty (no contract/thread anchors), so the
contract is delivered *inline* in every prompt rather than read from the
blackboard. ``read_blackboard`` is for seeing other agents' live posts only.
"""

from __future__ import annotations

from server.market_hive.auction import Invitation
from server.market_hive.schemas import ContractSchema, ThreadSchema

# ── Auction phase (§9.1) ───────────────────────────────────────────────────────

AUCTION_SYSTEM_SUFFIX = (
    "You are being invited to bid on a contract in a multi-agent collaborative "
    "system. The contract is a HIGH-LEVEL DECISION QUESTION (a brief), not a full "
    "document to review clause-by-clause — do not expect attached contract text, "
    "section numbers, or clauses at this stage. Decide ONE thing: is this question "
    "within your professional field?\n"
    "- If yes, call submit_bid(justification). You will answer from your expertise "
    "and professional judgement; detailed analysis and any source materials come in "
    "the later discussion rounds, not now.\n"
    "- Call abstain(reason) ONLY if the topic is genuinely outside your domain.\n"
    "Do NOT abstain on the grounds that the brief is short, high-level, or lacks an "
    "attached document — that is expected. A plausibly-relevant specialist should "
    "bid; the team needs your perspective."
)


def auction_user_prompt(contract: ContractSchema, invitation: Invitation) -> str:
    """The CONTRACT INVITATION message shown to one invited agent."""
    expertise = ", ".join(contract.required_expertise) or "open to all relevant expertise"
    return (
        "CONTRACT INVITATION\n"
        f"Task type: {contract.task_type}\n"
        f"Task nature: {contract.task_nature}\n"
        f"Required expertise: {expertise}\n"
        f"Complexity: {contract.complexity}\n\n"
        "QUESTION TO DECIDE ON (this is the whole brief — no document is attached):\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR PRELIMINARY MATCH SCORE: {invitation.preliminary_score:.3f}\n"
        f"YOUR TRUST SCORE (this domain): {invitation.trust_score:.3f}\n\n"
        "If this question is within your professional field, call "
        "submit_bid(justification) — you will analyse it in depth in later rounds. "
        "Call abstain(reason) only if it is genuinely outside your expertise."
    )


# ── Round 1 — opening proposals (§9.3) ─────────────────────────────────────────


def round_one_system_suffix(temperature_instruction: str) -> str:
    """System suffix for the opening-proposal round."""
    return (
        "You are participating in a collaborative multi-agent blackboard that works "
        "like a Reddit thread: agents post proposals, reply to each other, cite posts "
        "they agree with, and @mention agents they need.\n\n"
        "RULES:\n"
        "- The contract and your thread are in the message below — that is your input.\n"
        "- Use post_to_blackboard(entry_type='proposal', thread_id=...) to post.\n"
        "- You may call read_blackboard() to see others' posts (likely empty this early).\n\n"
        "ROUND 1 INSTRUCTION: Write your opening proposal for this thread. Include "
        "(1) why you are qualified, (2) your initial analysis and answer, and (3) the "
        "key clauses or evidence you rely on. This is your stake in the ground — make "
        "it thorough and specific.\n\n"
        f"{temperature_instruction}"
    )


def round_one_user_prompt(
    contract: ContractSchema, thread: ThreadSchema, *, max_rounds: int, coworkers: list[str]
) -> str:
    """The opening-proposal user message for one taker on one thread."""
    people = ", ".join(coworkers) or "(none)"
    return (
        "CONTRACT:\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}\n"
        f"ROUND: 1 of {max_rounds}\n"
        f"CO-WORKERS ON THIS THREAD: {people}\n\n"
        "Write your Round 1 proposal now with "
        f'post_to_blackboard(entry_type="proposal", thread_id="{thread.id}").'
    )


# ── Vote sub-round (§9.4) ──────────────────────────────────────────────────────

VOTE_SYSTEM_SUFFIX = (
    "You are in the cold-start voting phase. Review the Round 1 proposals from your "
    "co-workers (listed below) and call vote(entry_id) for each proposal you find "
    "valid and would build on. You may vote on multiple proposals. This is NOT about "
    "selecting a winner — it establishes initial confidence scores."
)


def vote_user_prompt(thread: ThreadSchema, proposals: list[tuple[str, str, str]]) -> str:
    """List the round-1 proposals an agent should consider voting on.

    ``proposals`` is ``[(entry_id, author_name, content)]``.
    """
    listing = (
        "\n\n".join(f"[{pid}] {name}: {content[:400]}" for pid, name, content in proposals)
        or "(no proposals)"
    )
    return (
        f"ROUND 1 PROPOSALS IN YOUR THREAD [{thread.title}]:\n{listing}\n\n"
        "Call vote(entry_id) for each proposal you find valid, passing the full id "
        "shown in brackets."
    )


# ── Discussion rounds 2+ (§9.5) ────────────────────────────────────────────────


def rounds_system_suffix(temperature_instruction: str) -> str:
    """System suffix for a discussion round, carrying the conceding temperature."""
    return (
        "You are in a collaborative multi-agent discussion. The blackboard is a "
        "Reddit-like thread: read posts, reply, cite what you agree with, and @mention "
        "agents whose help you need.\n\n"
        "RULES:\n"
        "- The contract and your thread are in the message below.\n"
        "- Use read_blackboard() to see what your co-workers have posted this run.\n"
        "- Use post_to_blackboard(reply_to=..., thread_id=...) to respond to a post.\n"
        "- Use cite(entry_ids=[...]) ONLY for entries you build on or agree with — "
        "express disagreement in your reply content, not by citing.\n\n"
        f"{temperature_instruction}"
    )


def rounds_user_prompt(
    contract: ContractSchema, thread: ThreadSchema, *, round: int, max_rounds: int
) -> str:
    """The discussion user message for one taker on one thread in round ``round``."""
    return (
        "CONTRACT:\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR THREAD: [{thread.id}] {thread.title}\n"
        f"ROUND: {round} of {max_rounds}\n\n"
        f'Use read_blackboard(thread_id="{thread.id}") to review the discussion, then '
        "post_to_blackboard(reply_to=...) with your analysis and cite(entry_ids=[...]) "
        "the entries you build on."
    )

"""Per-phase agent prompts for the swarm (PRD §9).

Each phase contributes a system suffix (appended to the agent's own system
prompt) and a user message built from the live contract/thread state. Keeping
them here keeps the orchestrator focused on sequencing.
"""

from __future__ import annotations

from server.market_hive.auction import Invitation
from server.market_hive.schemas import ContractSchema, ThreadSchema

# ── Auction phase (§9.1) ───────────────────────────────────────────────────────

AUCTION_SYSTEM_SUFFIX = (
    "You are being invited to bid on a contract in a multi-agent collaborative "
    "system. Review the contract carefully. Use read_blackboard() to read the "
    "contract and thread details. Then call submit_bid(justification) if you can "
    "contribute, or abstain(reason) if you cannot. Only bid if you genuinely have "
    "relevant expertise — compute efficiency is precious."
)


def auction_user_prompt(contract: ContractSchema, invitation: Invitation) -> str:
    """The CONTRACT INVITATION message shown to one invited agent."""
    expertise = ", ".join(contract.required_expertise) or "unspecified"
    return (
        "CONTRACT INVITATION\n"
        f"Task type: {contract.task_type}\n"
        f"Task nature: {contract.task_nature}\n"
        f"Original prompt: {contract.original_prompt}\n"
        f"Required expertise: {expertise}\n"
        f"Complexity: {contract.complexity}\n"
        f"Market Maker confidence: {contract.confidence:.2f}\n\n"
        f"YOUR PRELIMINARY MATCH SCORE: {invitation.preliminary_score:.3f}\n"
        f"YOUR TRUST SCORE (this domain): {invitation.trust_score:.3f}\n\n"
        "Review the full contract by calling read_blackboard().\n"
        "Then call submit_bid(justification) or abstain(reason)."
    )


# ── Round 1 — opening proposals (§9.3) ─────────────────────────────────────────


def round_one_system_suffix(temperature_instruction: str) -> str:
    """System suffix for the opening-proposal round."""
    return (
        "You are participating in a collaborative multi-agent blackboard system that "
        "works like a Reddit thread: you read posts, write replies, cite posts you "
        "agree with, and mention agents you need.\n\n"
        "RULES:\n"
        "- Use read_blackboard() to orient yourself before posting.\n"
        "- Use get_confirmed() to review the ratified anchors.\n"
        "- Use post_to_blackboard(entry_type='proposal') to write your contribution.\n\n"
        "ROUND 1 INSTRUCTION: Write your opening proposal for this thread. Include "
        "(1) why you are qualified, (2) your initial analysis and answer, and "
        "(3) what tools or sources you used. This is your stake in the ground — make "
        "it thorough.\n\n"
        f"{temperature_instruction}"
    )


def round_one_user_prompt(
    contract: ContractSchema, thread: ThreadSchema, *, max_rounds: int, coworkers: list[str]
) -> str:
    """The opening-proposal user message for one taker on one thread."""
    people = ", ".join(coworkers) or "(none)"
    return (
        f"CONTRACT: {contract.original_prompt}\n"
        f"YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}\n"
        f"ROUND: 1 of {max_rounds}\n"
        f"CO-WORKERS ON THIS THREAD: {people}\n\n"
        f'Use read_blackboard(thread_id="{thread.id}") to see the full context, then '
        'use post_to_blackboard(entry_type="proposal") to write your Round 1 proposal.'
    )


# ── Vote sub-round (§9.4) ──────────────────────────────────────────────────────

VOTE_SYSTEM_SUFFIX = (
    "You are in the cold-start voting phase. Review all Round 1 proposals from your "
    "co-workers and call vote(entry_id) for each proposal you find valid and would "
    "build on. You may vote on multiple proposals. This is NOT about selecting a "
    "winner — it establishes initial confidence scores."
)


def vote_user_prompt(thread: ThreadSchema, proposals: list[tuple[str, str, str]]) -> str:
    """List the round-1 proposals an agent should consider voting on.

    ``proposals`` is ``[(entry_id, author_name, content)]``.
    """
    listing = (
        "\n\n".join(f"[{pid}] {name}: {content[:300]}" for pid, name, content in proposals)
        or "(no proposals)"
    )
    return (
        f"ROUND 1 PROPOSALS IN YOUR THREAD [{thread.title}]:\n{listing}\n\n"
        "Call vote(entry_id) for each proposal you find valid. Call read_blackboard() "
        "if you need to review any entry in detail."
    )


# ── Discussion rounds 2+ (§9.5) ────────────────────────────────────────────────


def rounds_system_suffix(temperature_instruction: str) -> str:
    """System suffix for a discussion round, carrying the conceding temperature."""
    return (
        "You are in a collaborative multi-agent discussion. The blackboard is a "
        "Reddit-like thread: read posts, write replies, cite what you agree with, and "
        "@mention agents whose help you need.\n\n"
        "RULES:\n"
        "- Use read_blackboard() to explore the discussion in depth.\n"
        "- Use get_confirmed() to see the ratified findings.\n"
        "- Use post_to_blackboard(reply_to=...) to respond to specific posts.\n"
        "- Use cite(entry_ids=[...]) ONLY for entries you are building on or agree with — "
        "express disagreement in your reply content, not by citing.\n\n"
        f"{temperature_instruction}"
    )


def rounds_user_prompt(
    contract: ContractSchema, thread: ThreadSchema, *, round: int, max_rounds: int
) -> str:
    """The discussion user message for one taker on one thread in round ``round``."""
    return (
        f"CONTRACT: {contract.original_prompt}\n"
        f"YOUR THREAD: [{thread.id}] {thread.title}\n"
        f"ROUND: {round} of {max_rounds}\n\n"
        f'Use read_blackboard(thread_id="{thread.id}") to explore the discussion, then '
        "post_to_blackboard(reply_to=...) with your analysis and cite(entry_ids=[...]) the "
        "entries you build on."
    )

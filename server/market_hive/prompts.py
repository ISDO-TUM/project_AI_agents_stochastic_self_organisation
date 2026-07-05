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


def _thread_listing(contract: ContractSchema) -> str:
    """A compact bullet list of the contract's planned threads (multi-step only)."""
    if len(contract.threads) <= 1:
        return ""
    lines = []
    for t in contract.threads:
        expertise = ", ".join(t.required_expertise) or "any relevant expertise"
        lines.append(f'- [{t.id}] {t.title} [{expertise}]: {t.description}')
    return (
        "PLANNED WORK THREADS (you will be matched to the one(s) fitting you):\n"
        + "\n".join(lines)
        + "\n\nWhen bidding or abstaining on a specific thread, pass its bracketed "
        "id verbatim as thread_id (e.g. thread_id=\"" + contract.threads[0].id + "\") — "
        "never the thread's title."
    )


def auction_user_prompt(contract: ContractSchema, invitation: Invitation) -> str:
    """The CONTRACT INVITATION message shown to one invited agent."""
    expertise = ", ".join(contract.required_expertise) or "open to all relevant expertise"
    threads_block = _thread_listing(contract)
    return (
        "CONTRACT INVITATION\n"
        f"Task type: {contract.task_type}\n"
        f"Task nature: {contract.task_nature}\n"
        f"Required expertise: {expertise}\n"
        f"Complexity: {contract.complexity}\n\n"
        "QUESTION TO DECIDE ON (this is the whole brief — no document is attached):\n"
        f"{contract.original_prompt}\n\n"
        + (f"{threads_block}\n\n" if threads_block else "")
        + f"YOUR PRELIMINARY MATCH SCORE: {invitation.preliminary_score:.3f}\n"
        f"YOUR TRUST SCORE (this domain): {invitation.trust_score:.3f}\n\n"
        "If this question — or any of its threads — is within your professional "
        "field, call submit_bid(justification); you will analyse it in depth in "
        "later rounds. Call abstain(reason) only if it is genuinely outside your "
        "expertise."
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
        "- You may call read_blackboard() to see others' posts (likely empty this early).\n"
        "- A proposal is a scarce, deliberate act, not a default — post one only when "
        "you have something to say that genuinely needs its own opening stake. If your "
        "own system prompt says to abstain when your expertise doesn't apply to this "
        "contract, honor that here: simply make no tool call this turn rather than "
        "forcing a low-value contribution.\n\n"
        "ROUND 1 INSTRUCTION: Write your opening proposal for this thread — but only "
        "the part of the analysis that genuinely calls for YOUR specific expertise; "
        "do not re-cover ground better owned by a co-worker's specialty just to be "
        "thorough. Be concise: lead with your one-sentence claim, then only the "
        "points that need your expertise.\n"
        "FORMAT: write clean GitHub-flavored Markdown — use `###` sub-headers, "
        "`**bold**` labels, and `-` bullet lists (not run-on paragraphs). State your "
        "qualification in ONE short sentence, not a paragraph.\n"
        "Fill the claim field with your one-sentence thesis, evidence with the file "
        "names you relied on, and stance ('new' for an opening proposal).\n\n"
        f"{temperature_instruction}"
    )


def _scope_note(contract: ContractSchema) -> str:
    """For multi-thread contracts: keep each taker inside its assigned slice."""
    if contract.task_nature != "multi":
        return ""
    return (
        "This contract is split into several threads; other threads cover the "
        "rest of the request. Stay within YOUR thread's scope.\n"
    )


def round_one_user_prompt(
    contract: ContractSchema, thread: ThreadSchema, *, max_rounds: int, coworkers: list[str]
) -> str:
    """The opening-proposal user message for one taker on one thread."""
    people = ", ".join(coworkers) or "(none)"
    expertise = ", ".join(thread.required_expertise) or "any relevant expertise"
    return (
        "CONTRACT:\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}\n"
        f"THREAD EXPERTISE: {expertise}\n"
        f"{_scope_note(contract)}"
        f"ROUND: 1 of {max_rounds}\n"
        f"CO-WORKERS ON THIS THREAD: {people}\n\n"
        "If this thread is genuinely within your expertise, write your Round 1 "
        "proposal now with "
        f'post_to_blackboard(entry_type="proposal", thread_id="{thread.id}"). '
        "If it is not — nothing here calls for your specific specialty — make no "
        "tool call; a co-worker better suited to this thread will cover it."
    )


def round_one_wave2_user_prompt(
    contract: ContractSchema,
    thread: ThreadSchema,
    *,
    proposals: list[tuple[str, str, str]],
    max_rounds: int,
    coworkers: list[str],
) -> str:
    """Second-wave opening prompt: earlier proposals shown, restating forbidden.

    ``proposals`` is ``[(entry_id, author_name, content)]`` (the
    ``_round1_proposals`` shape).
    """
    people = ", ".join(coworkers) or "(none)"
    listing = (
        "\n\n".join(f"[{pid}] {name}: {content[:400]}" for pid, name, content in proposals)
        or "(none yet)"
    )
    return (
        "CONTRACT:\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}\n"
        f"ROUND: 1 (second wave) of {max_rounds}\n"
        f"CO-WORKERS ON THIS THREAD: {people}\n\n"
        "PROPOSALS ALREADY POSTED BY YOUR CO-WORKERS:\n"
        f"{listing}\n\n"
        "Check them point by point before writing anything. If a clause, risk, or "
        "conclusion you'd raise is already covered above — even by a co-worker with "
        "a different specialty — do NOT re-cover it; you will endorse it in the "
        "vote sub-round that follows instead (citing isn't available until the "
        "discussion rounds). Post an opening proposal ONLY for what is genuinely "
        "not covered above: a different clause, a different risk, a disagreement, "
        "or new evidence. A proposal that mostly repeats what's already posted, "
        "reworded, is not a new proposal. If nothing is left to add, make no tool "
        "call. Keep it concise and in Markdown. To post, call "
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
        "- read_blackboard() is available if you need more than the retrieved excerpts "
        "in the message below.\n"
        '- Use post_to_blackboard(entry_type="reply", reply_to=..., thread_id=...) to '
        "respond to a post — entry_type is always \"reply\" here, never "
        '"proposal" (that was round 1 only; posting another proposal will be '
        "rejected).\n"
        "- Set claim (one-sentence thesis), stance ('supports'/'refutes'/'refines' + "
        "stance_target) and evidence on every post.\n"
        "- When you post a reply that supports, refines, or builds on another "
        "entry, you MUST also cite(entry_ids=[...]) that same entry in this turn — "
        "replying to a point and endorsing it are complementary, not alternatives. "
        "Citation is how consensus forms: an entry that enough distinct teammates "
        "cite is promoted to a confirmed finding, and without citations nothing your "
        "team agrees on is ever confirmed. Cite ONLY entries you genuinely agree "
        "with; express disagreement in your reply content, never by citing.\n"
        "- Use dispute(entry_id, reason) ONLY against a CONFIRMED finding you can show "
        "is wrong — it takes M agents to contest, exactly like promotion.\n"
        "- If the work is blocked by an expertise NOBODY on the team has, you may "
        "call request_expertise(domain, reason, thread_id) to propose recruiting "
        "it — this triggers a team vote and is capped per run, so use it only for "
        "a genuine, blocking gap, not for topics the team can reasonably cover.\n"
        "- BREVITY: a reply must be a DELTA — exactly one new point, one "
        "disagreement, or one piece of new evidence. Do NOT restate or reword "
        "analysis already on the board; rewording is noise and over-long posts are "
        "rejected. Do NOT re-state your qualifications — that was round 1.\n"
        "- If you have nothing material to add on this thread, call "
        "stand_down(reason) instead of posting. When every taker has stood down, "
        "the run ends — this is how the team finishes instead of repeating itself.\n"
        "- FORMAT every post as clean GitHub-flavored Markdown: `**bold**` labels, "
        "`-` bullet lists, short paragraphs.\n\n"
        f"{temperature_instruction}"
    )


def rounds_user_prompt(
    contract: ContractSchema,
    thread: ThreadSchema,
    *,
    round: int,
    max_rounds: int,
    relevant_posts: str | None = None,
) -> str:
    """The discussion user message for one taker on one thread in round ``round``.

    ``relevant_posts`` is a pre-retrieved board digest (server-side RAG); when
    present it is injected with an explicit cite-don't-restate instruction so
    an agent cannot duplicate a point it was never forced to look at.
    """
    injected = (
        "RELEVANT EXISTING POSTS (retrieved for you — most relevant to your "
        "expertise):\n"
        f"{relevant_posts}\n\n"
        "If a point you agree with is already made above, cite(entry_ids=[...]) it — "
        "that endorsement is what promotes it to a confirmed finding. If you also "
        "have something new to add — a different angle, a disagreement, or new "
        "evidence — post a reply for that; and when your reply supports or refines "
        "one of the posts above, cite that post in the same turn. Do not merely "
        "restate a point already made: rewording someone else's post is noise, but "
        "citing it is real reinforcement.\n\n"
        if relevant_posts
        else ""
    )
    return (
        "CONTRACT:\n"
        f"{contract.original_prompt}\n\n"
        f"YOUR THREAD: [{thread.id}] {thread.title} — {thread.description}\n"
        f"{_scope_note(contract)}"
        f"ROUND: {round} of {max_rounds}\n\n"
        f"{injected}"
        f'You may call read_blackboard(thread_id="{thread.id}") to browse beyond '
        "the excerpts above, then "
        f'post_to_blackboard(entry_type="reply", reply_to=..., thread_id="{thread.id}") '
        "with your analysis, and cite(entry_ids=[...]) every entry your reply "
        "supports or builds on — that is what lets the team's agreement be confirmed.\n\n"
        "If nothing above needs a new point, disagreement, or fresh evidence from "
        "you, call stand_down(reason) rather than restating. Keep any reply short "
        "and in Markdown."
    )


# ── Ratification sub-round (post-synthesis) ────────────────────────────────

RATIFY_SYSTEM_SUFFIX = (
    "The run is closing. A draft of the final answer has been synthesised from the "
    "run's confirmed findings, listed below — not just the ones you personally "
    "authored. Review it against THOSE findings. Call approve_synthesis() if it is "
    "faithful to them, or revise_synthesis(reason) stating specifically what is "
    "missing or misrepresented. Do not object that nothing was confirmed unless the "
    "list below is genuinely empty. Do not relitigate the findings."
)


def ratify_user_prompt(candidate: str, findings: list[tuple[str, str]]) -> str:
    """``findings``: (confirmed_entry_id, content) for every live confirmed finding
    this run — the same list for every rater, not just what this taker authored."""
    listed = "\n".join(f"- [{fid[:8]}] {c[:200]}" for fid, c in findings) or "(none)"
    return (
        "DRAFT FINAL ANSWER:\n"
        f"{candidate}\n\n"
        "THIS RUN'S CONFIRMED FINDINGS:\n"
        f"{listed}\n\n"
        "Approve, or request one specific revision."
    )

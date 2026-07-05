"""Market Maker — prompt → typed Contract + Threads (PRD §6.1).

The Market Maker is the man in the middle between the user and the swarm: **one
structured LLM call** turns a raw user prompt into a *scoped, typed* contract —
``task_type``, ``task_nature``, ``required_expertise``, ``complexity``, a brief
and a ``confidence``. For multi-step prompts it decomposes the work into 2-4
threads, each with its own title, scoped description, expertise list, complexity
and embedding, so the auction's cosine matching invites the *right* specialists
per thread (a one-line prompt alone matches role descriptions poorly).

The MM is advisory, not authoritative (PRD P-04): agents can contest its scoping
via ``request_expertise`` amendments, and :meth:`MarketMaker.cast_amendment_vote`
is its ONE democratic vote — equal weight to every taker — on those proposals.

Robustness: it implements the same ``ContractSource`` protocol as
:class:`~server.market_hive.contract_source.FallbackContractSource` and falls
back to that no-LLM source on any error (missing key, timeout, unparseable
JSON), so the Market Maker can never block a run. The LLM's decomposition is
never trusted blindly — every field is coerced/clamped, and an inconsistent
``task_nature``/``threads`` pair is reconciled server-side (a "multi" with fewer
than two usable threads collapses to single; thread count is capped).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm import call_agent
from server.market_hive.contract_source import (
    FallbackContractSource,
    ThreadSpec,
    persist_contract,
)
from server.market_hive.schemas import AmendmentSchema, ContractSchema, ThreadSchema

logger = logging.getLogger(__name__)

# Hard cap on threads per contract: bounds per-round cost (each thread runs its
# own discussion) and keeps the LLM from inventing steps to look thorough.
_MAX_THREADS = 4

_SYSTEM_PROMPT = (
    "You are the Market Maker in a multi-agent collaboration system. Given a "
    "user's request, produce a structured 'contract' describing the work so that "
    "specialist agents can decide whether to bid on it. When — and only when — "
    "the request contains genuinely separable sub-problems, decompose it into "
    "parallel work threads.\n\n"
    "Respond with ONLY a single JSON object (no prose, no markdown fences) with "
    "exactly these keys:\n"
    '- "task_type": short snake_case label for the domain of work '
    '(e.g. "energy_contract_review", "market_analysis", "legal_review").\n'
    '- "task_nature": "single" or "multi". Use "multi" ONLY when the request '
    "contains distinct sub-problems that can be worked in parallel, each needing "
    "a different expertise mix and yielding its own findings (multi-part "
    "questions, compare-then-recommend tasks, reviews spanning several domains). "
    'A single focused question — even a hard one — is "single". Never invent '
    "sub-steps to look thorough.\n"
    '- "required_expertise": array of 2-6 short expertise domains the work needs '
    'overall (e.g. ["contract law", "energy pricing", "financial risk"]). Name '
    "the disciplines a qualified team would have.\n"
    '- "complexity": one of "low", "medium", "high".\n'
    '- "brief": 2-4 neutral sentences describing what the request is about and '
    "what analysis it calls for, naming the relevant domains explicitly.\n"
    '- "confidence": float 0.0-1.0 — your confidence in this scoping and '
    "decomposition.\n"
    '- "threads": for "multi" an array of 2-4 thread objects, for "single" an '
    "empty array. Each thread object has:\n"
    '  - "title": short title for the sub-problem (3-6 words).\n'
    '  - "description": 2-3 sentences scoping this sub-problem so a specialist '
    "can work it WITHOUT reading the other threads: state the question this "
    "thread answers and what its deliverable is.\n"
    '  - "required_expertise": 1-4 expertise domains for THIS thread.\n'
    '  - "complexity": "low", "medium" or "high" for this thread.\n\n'
    "Decomposition rules for multi:\n"
    "- Threads must not overlap: each claims a distinct slice of the request.\n"
    "- Together the threads must cover everything the user asked for — every "
    "explicit sub-question maps to a thread; nothing is dropped.\n"
    "- Split by expertise/deliverable, not by workflow stage (no "
    "'gather info' / 'write summary' threads).\n\n"
    "Output strictly valid JSON and nothing else."
)

_AMENDMENT_VOTE_SYSTEM_PROMPT = (
    "You are the Market Maker in a multi-agent swarm. You scoped the original "
    "contract. A taker now proposes adding expertise the team may be missing, "
    "which would spawn a new thread and recruit more agents. You hold ONE vote, "
    "equal to every taker — you are not a judge. Approve only if the gap is real "
    "and worth a new thread; otherwise reject. Reply with a single word: "
    "APPROVE or REJECT."
)


# ── field coercers (shared by contract + thread analysis) ─────────────────────
# The LLM's JSON is never trusted: strings may arrive as null/numbers, lists as
# strings, enums in the wrong case. Coerce everything to a safe value instead of
# failing validation — a fallback contract is a worse outcome than a lax field.


def _as_str(v: object) -> object:
    return v if isinstance(v, str) else ("" if v is None else str(v))


def _as_str_list(v: object) -> object:
    if isinstance(v, str):
        return [v]
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _as_complexity(v: object) -> object:
    s = str(v).strip().lower() if v is not None else "medium"
    return s if s in {"low", "medium", "high"} else "medium"


class _ThreadPlan(BaseModel):
    """One planned thread from the Market Maker's decomposition."""

    title: str = ""
    description: str = ""
    required_expertise: list[str] = Field(default_factory=list)
    complexity: Literal["low", "medium", "high"] = "medium"

    _coerce_str = field_validator("title", "description", mode="before")(_as_str)
    _coerce_list = field_validator("required_expertise", mode="before")(_as_str_list)
    _coerce_cx = field_validator("complexity", mode="before")(_as_complexity)


class _ContractAnalysis(BaseModel):
    """The structured decomposition the Market Maker's LLM call must return."""

    task_type: str = "analysis"
    task_nature: Literal["single", "multi"] = "single"
    required_expertise: list[str] = Field(default_factory=list)
    complexity: Literal["low", "medium", "high"] = "medium"
    brief: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    threads: list[_ThreadPlan] = Field(default_factory=list)

    _coerce_str = field_validator("task_type", "brief", mode="before")(_as_str)
    _coerce_list = field_validator("required_expertise", mode="before")(_as_str_list)
    _coerce_cx = field_validator("complexity", mode="before")(_as_complexity)

    @field_validator("task_nature", mode="before")
    @classmethod
    def _coerce_nature(cls, v: object) -> object:
        s = str(v).strip().lower() if v is not None else "single"
        return s if s in {"single", "multi"} else "single"

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: object) -> object:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5
        return min(1.0, max(0.0, f))

    @field_validator("threads", mode="before")
    @classmethod
    def _coerce_threads(cls, v: object) -> object:
        # Keep only dict items so one junk element can't fail the whole analysis.
        return [t for t in v if isinstance(t, dict)] if isinstance(v, list) else []


def _extract_json(text: str) -> dict[str, object] | None:
    """Pull the first top-level JSON object out of an LLM response.

    Tolerant of stray prose or ```json fences: slices from the first ``{`` to the
    last ``}``. Returns ``None`` if nothing parseable is found.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _usable_threads(analysis: _ContractAnalysis) -> list[_ThreadPlan]:
    """Reconcile ``task_nature`` with the planned threads (server-side, not LLM).

    Returns the threads to persist for a multi contract, or ``[]`` meaning the
    contract is effectively single-step. A thread with no usable text is dropped;
    a "multi" that ends up with fewer than two usable threads collapses to single
    (one thread is just the contract itself); anything past ``_MAX_THREADS`` is
    truncated to bound per-round cost.
    """
    if analysis.task_nature != "multi":
        return []
    usable: list[_ThreadPlan] = []
    for plan in analysis.threads:
        title = plan.title.strip()
        description = plan.description.strip()
        if not title and not description:
            continue
        usable.append(
            plan.model_copy(
                update={
                    "title": title or f"Sub-task {len(usable) + 1}",
                    "description": description or title,
                }
            )
        )
    if len(usable) < 2:
        return []
    return usable[:_MAX_THREADS]


def _embedding_text(body: str, expertise: list[str]) -> str:
    """Body + named expertise, so the embedding sits close to matching agent roles."""
    line = ", ".join(expertise)
    return f"{body}\nRelevant expertise: {line}" if line else body


class MarketMaker:
    """LLM-backed contract source: prompt → typed contract + threads + MM vote."""

    def __init__(
        self,
        *,
        provider: str = "openai",
        model: str = "gpt-4o",
        timeout: float = 30.0,
        fallback: FallbackContractSource | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._timeout = timeout
        self._fallback = fallback or FallbackContractSource()

    async def make_contract(
        self,
        prompt: str,
        run_id: str,
        db: AsyncConnection,
        *,
        session_context: str | None = None,
    ) -> tuple[ContractSchema, list[ThreadSchema]]:
        """Decompose ``prompt`` into a typed contract, or fall back on failure.

        ``session_context`` (multi-turn contract sessions): a digest of the
        prior run's ratified findings, when this is a follow-up run. Folded
        into the analysis prompt so the Market Maker scopes only the delta,
        and into the embedding text so the auction's cosine matching reflects
        the session too.
        """
        analysis = await self._analyse(prompt, session_context)
        if analysis is None:
            logger.info("MarketMaker analysis unavailable; using fallback contract source.")
            contract, threads = await self._fallback.make_contract(
                prompt, run_id, db, session_context=session_context
            )
            return contract, threads

        brief = analysis.brief.strip() or prompt

        def _with_session(text: str) -> str:
            # Multi-turn contract sessions: fold the prior run's ratified
            # findings into every embedding so cosine matching (and re-scoping)
            # reflects the session, not just this turn's prompt.
            return f"{text}\n{session_context}" if session_context else text

        brief_embedding_text = _with_session(_embedding_text(brief, analysis.required_expertise))

        plans = _usable_threads(analysis)
        if plans:
            specs = [
                ThreadSpec(
                    title=plan.title,
                    description=plan.description,
                    embedding_text=_with_session(
                        _embedding_text(
                            f"{plan.title}\n{plan.description}", plan.required_expertise
                        )
                    ),
                    required_expertise=plan.required_expertise,
                    complexity=plan.complexity,
                )
                for plan in plans
            ]
        else:
            specs = [
                ThreadSpec(
                    title="Main Thread",
                    description=brief,
                    embedding_text=brief_embedding_text,
                    required_expertise=analysis.required_expertise,
                    complexity=analysis.complexity,
                )
            ]

        contract, threads = await persist_contract(
            db,
            run_id=run_id,
            prompt=prompt,
            task_type=analysis.task_type or "analysis",
            required_expertise=analysis.required_expertise,
            complexity=analysis.complexity,
            confidence=analysis.confidence,
            embedding_text=brief_embedding_text,
            threads=specs,
        )
        return contract, threads

    async def cast_amendment_vote(self, amendment: AmendmentSchema) -> Literal["approve", "reject"]:
        """The Market Maker's ONE equal vote on a contract amendment (PRD §6.1/§6.5).

        Bounded by the same timeout as contract drafting. Any failure — timeout,
        missing key, garbled reply — counts as REJECT: silence is not approval,
        and a broken MM must not be able to wave amendments through.
        """
        user_prompt = (
            f"Proposed expertise: {amendment.requested_domain}\n"
            f"Reason given: {amendment.reason}\n\n"
            "Should a new thread be created for this expertise? Reply APPROVE or REJECT."
        )
        try:
            response, _ = await asyncio.wait_for(
                call_agent(
                    user_prompt,
                    provider=self._provider,
                    model=self._model,
                    system_prompt=_AMENDMENT_VOTE_SYSTEM_PROMPT,
                ),
                timeout=self._timeout,
            )
        except Exception:
            logger.exception("MarketMaker amendment vote failed; counting as reject.")
            return "reject"
        return "approve" if "approve" in response.strip().lower() else "reject"

    async def _analyse(
        self, prompt: str, session_context: str | None = None
    ) -> _ContractAnalysis | None:
        """One LLM call → validated analysis. Returns ``None`` on any failure.

        Bounded by ``timeout`` so a slow/hung provider can never stall the run's
        first frame — on timeout we fall back to the instant no-LLM source.
        """
        user_prompt = f"{prompt}\n\n{session_context}" if session_context else prompt
        try:
            response, _ = await asyncio.wait_for(
                call_agent(
                    user_prompt,
                    provider=self._provider,
                    model=self._model,
                    system_prompt=_SYSTEM_PROMPT,
                ),
                timeout=self._timeout,
            )
        except TimeoutError:
            logger.warning(
                "MarketMaker LLM call timed out after %.0fs; using fallback.", self._timeout
            )
            return None
        except Exception:
            logger.exception("MarketMaker LLM call failed.")
            return None

        raw = _extract_json(response)
        if raw is None:
            logger.warning("MarketMaker returned no parseable JSON: %r", response[:200])
            return None
        try:
            return _ContractAnalysis.model_validate(raw)
        except Exception:
            logger.exception("MarketMaker JSON failed validation: %r", raw)
            return None

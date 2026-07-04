"""Market Maker — prompt → typed Contract + Thread (PRD §6.1).

The minimal real Market Maker: **one structured LLM call** turns a raw user
prompt into a *scoped, typed* contract — ``task_type``, ``required_expertise``,
``complexity``, a 2-3 sentence ``brief`` and a ``confidence``. The brief plus the
required-expertise list is what gets embedded, so the auction's cosine matching
invites the *right* specialists (a one-line prompt alone matches role
descriptions poorly).

Scope (v1): single-thread only — no multi-thread decomposition, no confidence
calibration, no amendment voting yet. It implements the same ``ContractSource``
protocol as :class:`~server.market_hive.contract_source.FallbackContractSource`,
so it drops into the orchestrator with no change to the run loop, and it falls
back to that no-LLM source on any error so a missing key or bad response never
blocks a run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncConnection

from server.llm import call_agent
from server.market_hive.contract_source import FallbackContractSource, persist_contract
from server.market_hive.schemas import ContractSchema, ThreadSchema

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are the Market Maker in a multi-agent collaboration system. Given a "
    "user's request, produce a structured 'contract' describing the work so that "
    "specialist agents can decide whether to bid on it.\n\n"
    "Respond with ONLY a single JSON object (no prose, no markdown fences) with "
    "exactly these keys:\n"
    '- "task_type": short snake_case label for the domain of work '
    '(e.g. "energy_contract_review", "market_analysis", "legal_review").\n'
    '- "required_expertise": array of 2-6 short expertise domains the work needs '
    '(e.g. ["contract law", "energy pricing", "financial risk", '
    '"regulatory compliance"]). Name the disciplines a qualified team would have.\n'
    '- "complexity": one of "low", "medium", "high".\n'
    '- "brief": 2-3 neutral sentences describing what the contract is about and '
    "what analysis it calls for, naming the relevant domains explicitly.\n"
    '- "confidence": float 0.0-1.0 — your confidence in this decomposition.\n\n'
    "Output strictly valid JSON and nothing else."
)


class _ContractAnalysis(BaseModel):
    """The structured decomposition the Market Maker's LLM call must return."""

    task_type: str = "analysis"
    required_expertise: list[str] = Field(default_factory=list)
    complexity: Literal["low", "medium", "high"] = "medium"
    brief: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("task_type", "brief", mode="before")
    @classmethod
    def _coerce_str(cls, v: object) -> object:
        return v if isinstance(v, str) else ("" if v is None else str(v))

    @field_validator("required_expertise", mode="before")
    @classmethod
    def _coerce_expertise(cls, v: object) -> object:
        if isinstance(v, str):
            return [v]
        if isinstance(v, list):
            return [str(x).strip() for x in v if str(x).strip()]
        return []

    @field_validator("complexity", mode="before")
    @classmethod
    def _coerce_complexity(cls, v: object) -> object:
        s = str(v).strip().lower() if v is not None else "medium"
        return s if s in {"low", "medium", "high"} else "medium"

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: object) -> object:
        try:
            f = float(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.5
        return min(1.0, max(0.0, f))


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


class MarketMaker:
    """LLM-backed contract source: prompt → typed contract + single thread."""

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
        # Embed the brief together with the named expertise so the contract
        # embedding sits close to the matching agents' role descriptions.
        expertise_line = ", ".join(analysis.required_expertise)
        embedding_text = (
            f"{brief}\nRelevant expertise: {expertise_line}" if expertise_line else brief
        )
        if session_context:
            embedding_text = f"{embedding_text}\n{session_context}"

        contract, threads = await persist_contract(
            db,
            run_id=run_id,
            prompt=prompt,
            task_type=analysis.task_type or "analysis",
            required_expertise=analysis.required_expertise,
            complexity=analysis.complexity,
            confidence=analysis.confidence,
            description=brief,
            embedding_text=embedding_text,
        )
        return contract, threads

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

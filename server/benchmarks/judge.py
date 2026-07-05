"""Blind, severity-weighted rubric judge.

The judge never sees which mode produced an answer — it receives only the
answer text, the task's prompt, source documents, and gold rubric. Blindness
is structural (the function signature carries no mode parameter), not a
prompt instruction that could be ignored.

Judging never crashes a suite run: malformed judge output triggers one
re-ask, and a still-malformed response degrades to a "missed everything"
score flagged ``metadata["judge_parse_failed"] = True`` rather than raising.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from server.benchmarks.tasks import BenchmarkTask
from server.llm import call_agent
from server.schemas import ToolCall

_SEVERITY_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_COVERAGE_VALUE = {"covered": 1.0, "partial": 0.5, "missed": 0.0}

_JUDGE_SYSTEM_PROMPT = (
    "You are a rigorous, impartial evaluator scoring an answer against a gold "
    "rubric. You do not know and must not speculate about how the answer was "
    "produced — judge only its content against the rubric and source documents."
)


class FindingJudgment(BaseModel):
    finding_id: str
    coverage: Literal["covered", "partial", "missed"]
    grounded: bool  # cites the right section and it supports the claim
    rationale: str


class AnswerScore(BaseModel):
    rubric: list[FindingJudgment]
    contradictions: int
    coverage_score: float  # covered=1, partial=0.5, missed=0 → weighted by severity
    judge_model: str
    metadata: dict[str, Any] = {}


class Judge(Protocol):
    async def __call__(
        self,
        prompt: str,
        provider: str,
        model: str,
        system_prompt: str | None = None,
    ) -> tuple[str, list[ToolCall]]:
        pass


def _build_judge_prompt(answer: str, task: BenchmarkTask) -> str:
    rubric_block = "\n".join(
        f"- [{f.id}] {f.description} (must cite {f.must_cite}, severity={f.severity})"
        for f in task.rubric
    )
    sources_block = "\n\n".join(f"[{s['name']}]\n{s['content']}" for s in task.sources)
    return (
        f"TASK PROMPT:\n{task.prompt}\n\n"
        f"SOURCE DOCUMENTS (for grounding verification):\n{sources_block}\n\n"
        f"GOLD RUBRIC:\n{rubric_block}\n\n"
        f"ANSWER TO JUDGE:\n{answer}\n\n"
        "For each rubric finding, judge whether the answer covers it "
        '("covered", "partial", or "missed") and whether it is grounded (cites '
        "the right section and the citation genuinely supports the claim). "
        "Also count factual contradictions between the answer and the source "
        "documents. Respond with ONLY a JSON object, no prose, no markdown "
        'fences: {"rubric": [{"finding_id": "...", "coverage": "...", '
        '"grounded": true/false, "rationale": "..."}, ...], "contradictions": 0}.'
    )


def _parse_judgment(raw: str) -> dict[str, Any] | None:
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rubric"), list):
        return None
    return parsed


def _weighted_coverage(judgments: list[FindingJudgment], task: BenchmarkTask) -> float:
    weight_by_id = {f.id: _SEVERITY_WEIGHT[f.severity] for f in task.rubric}
    num = 0.0
    den = 0.0
    for j in judgments:
        w = weight_by_id.get(j.finding_id, 1)
        num += w * _COVERAGE_VALUE[j.coverage]
        den += w
    return (num / den) if den else 0.0


def _missed_everything(task: BenchmarkTask, model: str) -> AnswerScore:
    rubric = [
        FindingJudgment(
            finding_id=f.id,
            coverage="missed",
            grounded=False,
            rationale="judge output could not be parsed after a re-ask",
        )
        for f in task.rubric
    ]
    return AnswerScore(
        rubric=rubric,
        contradictions=0,
        coverage_score=0.0,
        judge_model=model,
        metadata={"judge_parse_failed": True},
    )


async def judge_answer(
    answer: str, task: BenchmarkTask, *, judge: Judge = call_agent, model: str = "gpt-4o"
) -> AnswerScore:
    """Blind severity-weighted judgment. ``judge`` defaults to the real
    ``call_agent`` seam; tests inject a fake with the same signature."""
    prompt = _build_judge_prompt(answer, task)

    raw, _ = await judge(prompt, provider="openai", model=model, system_prompt=_JUDGE_SYSTEM_PROMPT)
    parsed = _parse_judgment(raw)
    if parsed is None:
        raw, _ = await judge(
            prompt, provider="openai", model=model, system_prompt=_JUDGE_SYSTEM_PROMPT
        )
        parsed = _parse_judgment(raw)
    if parsed is None:
        return _missed_everything(task, model)

    judgments = [FindingJudgment.model_validate(j) for j in parsed["rubric"]]
    return AnswerScore(
        rubric=judgments,
        contradictions=int(parsed.get("contradictions", 0)),
        coverage_score=_weighted_coverage(judgments, task),
        judge_model=model,
    )

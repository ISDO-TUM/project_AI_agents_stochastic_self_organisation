"""Rules registry — predefined reasoning principles users can toggle on per run.

Each enabled rule is rendered as a bullet point and prepended to every agent's
system prompt as a shared ruleset during a simulation. New rules can be added by
appending to ``_RULES`` below — no other changes required.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

rules_router = APIRouter(prefix="/api/rules", tags=["Rules"])


class Rule(BaseModel):
    """A single named reasoning principle agents can be asked to abide by."""

    id: str = Field(description="Stable identifier, used in import/export.")
    label: str = Field(description="Short display label shown in the UI.")
    instruction: str = Field(description="The exact text appended (as a bullet) to the ruleset.")
    default: bool = Field(
        default=False,
        description="If true, the rule is pre-selected when the UI first loads.",
    )


_RULES: list[Rule] = [
    Rule(
        id="temporal",
        label="Temporal Reasoning",
        instruction=(
            "When agents hold conflicting information, treat document recency as a proxy "
            "for credibility. A claim from a newer source supersedes the same claim from "
            "an older source."
        ),
        default=True,
    ),
    Rule(
        id="combine_information",
        label="Combine Information",
        instruction=(
            "An agent can improve or propose a new vote by combining their "
            "information with that of another agent. "
            "For example: 'I see that Agent X has information Y which conflicts "
            "with mine, but if I combine it with my information Z I can conclude "
            "W, which resolves the conflict and is supported by both our sources.'"
        ),
        default=False,
    ),
    Rule(
        id="propose_partial",
        label="Propose Partial Answers",
        instruction=(
            "If you think you only have partial information to answer the "
            "question, you can propose a partial answer so other agents can "
            "build on it."
        ),
        default=False,
    ),
    Rule(
        id="concise_answers",
        label="Provide Concise Answers",
        instruction=(
            "When responding to questions, aim to be as concise as possible while still "
            "providing all necessary information."
        ),
        default=False,
    ),
]


@rules_router.get(
    "",
    response_model=list[Rule],
    summary="List available reasoning rules",
    description=(
        "Returns the catalogue of reasoning principles the user can toggle on per "
        "simulation. The frontend renders these as checkboxes; checked rules are joined "
        "as bullet points and propagated to every agent as a shared ruleset."
    ),
)
async def list_rules() -> list[Rule]:
    return _RULES

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
        label="Prefer Recent Sources",
        instruction=(
            "When two sources conflict on the same claim, prefer the newer source unless "
            "there is a clear reason not to."
        ),
        default=True,
    ),
    Rule(
        id="combine_information",
        label="Synthesize Evidence",
        instruction=(
            "Combine your evidence with other agents' evidence to propose a better answer, "
            "especially when pieces from multiple sources resolve a conflict."
        ),
        default=True,
    ),
    Rule(
        id="propose_partial",
        label="Share Partial Findings",
        instruction=(
            "If your information is incomplete, share a partial finding so other agents can "
            "build on it and refine the final answer."
        ),
        default=True,
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

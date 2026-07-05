"""Pydantic schemas for the ECSAS swarm system."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SwarmRunConfig(BaseModel):
    prompt: str
    mode: Literal["swarm", "topology"] = "swarm"
    # Shared-history linkage (set by the run endpoint): the trials row mirroring
    # this run and the experiment grouping it on the statistics page. The trial
    # id doubles as the Langfuse session id for the run's LLM calls.
    trial_id: str | None = None
    experiment_id: str | None = None
    # Anonymous owner of the run (X-User-Id header); None = legacy/shared.
    user_id: str | None = None
    min_takers: int = Field(default=2, ge=1, le=10)
    max_takers: int = Field(default=5, ge=1, le=20)
    min_rounds: int = Field(default=3, ge=1, le=5)
    max_rounds: int = Field(default=5, ge=2, le=20)
    token_budget: int = Field(default=50_000, ge=5_000, le=500_000)
    enable_token_budget: bool = True
    max_amendments: int = Field(default=2, ge=0, le=5)
    decay_rounds: int = Field(default=3, ge=1, le=10)
    invite_floor: float = Field(default=0.3, ge=0.0, le=1.0)
    alpha: float = Field(default=0.5)
    beta: float = Field(default=0.4)
    gamma: float = Field(default=0.1)
    k_attention: int = Field(default=10, ge=3, le=30)
    k_consecutive: int = Field(default=2, ge=1, le=5)
    epsilon_entropy: int = Field(default=0, ge=0)
    t_initial: float = Field(default=0.0)
    delta_t: float = Field(default=0.1)


class ThreadSchema(BaseModel):
    id: str
    contract_id: str
    run_id: str
    title: str
    description: str
    required_expertise: list[str] = []
    complexity: Literal["low", "medium", "high"] = "medium"
    thread_embedding: list[float] | None = None
    created_at: datetime

    @field_validator("required_expertise", "thread_embedding", mode="before")
    @classmethod
    def _parse_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v


class ContractSchema(BaseModel):
    id: str
    run_id: str
    original_prompt: str
    task_type: str
    task_nature: Literal["single", "multi"] = "single"
    required_expertise: list[str] = []
    complexity: Literal["low", "medium", "high"] = "medium"
    confidence: float = 0.0
    contract_embedding: list[float] | None = None
    threads: list[ThreadSchema] = []
    created_at: datetime

    @field_validator("required_expertise", "contract_embedding", mode="before")
    @classmethod
    def _parse_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v)
        return v


class DraftEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    round: int
    author_id: str
    author_name: str = ""
    entry_type: Literal["proposal", "reply", "vote", "system"]
    content: str
    reply_to: str | None = None
    mention_agents: list[str] = []
    documents_used: list[str] = []
    is_visible: bool = True
    deleted_at: datetime | None = None
    last_cited_round: int = 0
    citation_count: int = 0
    created_at: datetime
    children: list[DraftEntrySchema] = []
    # Structured contributions (2026-07-03): optional machine-readable fields.
    # Never a hard gate on posting — absent on any entry predating this feature.
    claim: str | None = None
    stance: Literal["new", "supports", "refutes", "refines"] | None = None
    stance_target: str | None = None
    evidence: list[str] = []
    # Contestable-consensus dedup: set when this draft was merged into an
    # existing confirmed entry instead of being promoted separately.
    merged_into: str | None = None

    @field_validator("evidence", mode="before")
    @classmethod
    def _parse_evidence(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v or "[]")
        return v


DraftEntrySchema.model_rebuild()


class ConfirmedEntrySchema(BaseModel):
    id: str
    run_id: str
    thread_id: str
    source_draft_id: str | None = None
    content: str
    entry_type: Literal["anchor", "finding", "system"] = "finding"
    citation_count: int = 0
    round_confirmed: int
    created_at: datetime
    # Contestable-consensus: a confirmed entry may be contested (over-threshold
    # dispute), re-affirmed back to confirmed, or retracted at termination. The
    # row is never deleted — status is the only thing that changes (P-03).
    status: Literal["confirmed", "contested", "retracted"] = "confirmed"
    # Multi-turn contract sessions: set to the run that originally ratified this
    # finding when it was carried forward as an anchor into a follow-up run.
    origin_run_id: str | None = None


class BidSchema(BaseModel):
    id: str
    run_id: str
    contract_id: str | None = None
    thread_id: str | None = None
    agent_id: str
    justification: str = ""
    preliminary_score: float = 0.0
    is_taker: bool = False
    is_observer: bool = False
    abstained: bool = False
    created_at: datetime


class ReputationSchema(BaseModel):
    run_id: str
    agent_id: str
    domain: str
    score: float = 0.5
    updated_at: datetime


class AgentTrustSchema(BaseModel):
    agent_id: str
    domain: str
    trust_score: float = 0.5
    runs_participated: int = 0
    updated_at: datetime


class AmendmentSchema(BaseModel):
    id: str
    run_id: str
    proposing_agent_id: str
    thread_id: str | None = None
    requested_domain: str
    reason: str
    status: Literal["pending", "approved", "rejected"] = "pending"
    approve_votes: int = 0
    total_voters: int = 0
    created_at: datetime


class CitationSchema(BaseModel):
    id: str
    run_id: str
    citing_agent_id: str
    cited_entry_id: str
    citing_entry_id: str | None = None
    round: int
    # Contestable-consensus: citations require a short justification (P-02/P-03
    # accountability). Optional on the schema only so pre-existing rows (created
    # before this column existed) still deserialise.
    reason: str | None = None
    created_at: datetime


class DisputeSchema(BaseModel):
    """A taker's mechanical challenge of a CONFIRMED entry (contestable consensus).

    Mirrors citations: one per agent per entry, crossing the same democratic
    threshold M flips the target's ``ConfirmedEntrySchema.status`` to contested.
    """

    id: str
    run_id: str
    disputing_agent_id: str
    confirmed_entry_id: str
    reason: str
    round: int
    created_at: datetime


class VoteSchema(BaseModel):
    id: str
    run_id: str
    voter_agent_id: str
    voted_entry_id: str
    thread_id: str
    round: int = 1
    created_at: datetime


class SwarmRunSchema(BaseModel):
    id: str
    status: str = "running"
    mode: str = "swarm"
    termination_reason: str | None = None
    termination_round: int | None = None
    amendment_count: int = 0
    token_usage: dict[str, Any] = {}
    final_answer: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    # Resilient runs: recorded position, so an orphaned run can resume from here.
    phase: str | None = None
    current_round: int | None = None
    heartbeat_at: datetime | None = None
    # The original SwarmRunConfig, persisted so resume uses the same knobs.
    config: dict[str, Any] | None = None
    # Ratified synthesis: the takers' vote on the synthesised final answer.
    ratification: dict[str, Any] | None = None
    # Multi-turn contract sessions: the first run in a session mints
    # session_id = its own id; follow-ups inherit it. parent_run_id is set only
    # on a follow-up run, pointing at the run it carried findings forward from.
    session_id: str | None = None
    parent_run_id: str | None = None

    @field_validator("token_usage", mode="before")
    @classmethod
    def _parse_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v or "{}")
        return v

    @field_validator("config", "ratification", mode="before")
    @classmethod
    def _parse_optional_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v) if v else None
        return v


class SwarmFinalOutput(BaseModel):
    run_id: str
    answers: dict[str, ConfirmedEntrySchema]
    confirmed_layer: list[ConfirmedEntrySchema]
    # A single brief answer to the original prompt, synthesised from the confirmed
    # findings. ``None`` only on legacy runs persisted before synthesis existed.
    final_answer: str | None = None
    termination_round: int
    termination_reason: Literal["equilibrium", "max_rounds", "budget", "quiescence"]
    metadata: dict[str, Any] = {}
    # Ratified synthesis: takers' approve/revise vote on ``final_answer``. None
    # on runs predating the feature (or when ratification was skipped).
    ratification: dict[str, Any] | None = None


# ── SSE stream (swarm run) ────────────────────────────────────────────────────
# The swarm orchestrator yields these as Server-Sent Events (PRD §7.2 / §11.1).
# The blackboard *board* is still read via REST polling (GET …/blackboard); this
# stream carries the live activity log + canvas animation triggers.
SwarmSimStepType = Literal[
    "system",
    "agent-thinking",
    "bid",
    "abstain",
    "bb-post",
    "bb-cite",
    "bb-vote",
    "bb-promote",
    "bb-recite",
    "bb-delete",
    "bb-mention",
    "bb-dispute",
    "bb-contest",
    "amendment",
    "amendment-approved",
    "amendment-rejected",
    "convergence",
]


class SimulationStep(BaseModel):
    """One Server-Sent Event emitted during a swarm run."""

    type: SwarmSimStepType
    msg: str
    node_id: str | None = None  # agent id, for canvas node highlight
    thread_id: str | None = None
    entry_id: str | None = None
    data: dict[str, Any] | None = None  # structured payload (e.g. final output)


class BlackboardResponse(BaseModel):
    threads: list[ThreadSchema]
    confirmed: list[ConfirmedEntrySchema]
    draft: list[DraftEntrySchema]


class AuditResponse(BaseModel):
    """Full audit trail for a run — every table scoped to the run_id.

    Soft-deleted draft entries are included (auditability by construction).
    ``final_output`` stays ``None`` until the termination engine (Phase 2) lands.
    """

    run: SwarmRunSchema
    contract: ContractSchema | None = None
    threads: list[ThreadSchema] = []
    bids: list[BidSchema] = []
    draft_entries: list[DraftEntrySchema] = []
    citations: list[CitationSchema] = []
    votes: list[VoteSchema] = []
    confirmed_entries: list[ConfirmedEntrySchema] = []
    disputes: list[DisputeSchema] = []
    amendments: list[AmendmentSchema] = []
    reputation: list[ReputationSchema] = []
    final_output: SwarmFinalOutput | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    current_round: int
    termination_reason: str | None = None
    termination_round: int | None = None
    token_usage: dict[str, Any] = {}


class AgentTrustEntry(BaseModel):
    domain: str
    trust_score: float
    runs_participated: int
    updated_at: datetime


class SeedRequest(BaseModel):
    prompt: str = "Test prompt for blackboard seeding"
    agent_ids: list[str] = []


class SeedResponse(BaseModel):
    run_id: str
    thread_id: str


class SeedRichResponse(BaseModel):
    run_id: str
    thread_ids: list[str]
    agent_ids: list[str]

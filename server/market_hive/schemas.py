"""Pydantic schemas for the ECSAS swarm system."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SwarmRunConfig(BaseModel):
    prompt: str
    mode: Literal["swarm", "topology"] = "swarm"
    min_takers: int = Field(default=2, ge=1, le=10)
    max_takers: int = Field(default=5, ge=1, le=20)
    min_rounds: int = Field(default=2, ge=1, le=5)
    max_rounds: int = Field(default=10, ge=2, le=20)
    token_budget: int = Field(default=50_000, ge=5_000, le=500_000)
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
    is_visible: bool = True
    deleted_at: datetime | None = None
    last_cited_round: int = 0
    citation_count: int = 0
    created_at: datetime
    children: list[DraftEntrySchema] = []


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
    created_at: datetime
    completed_at: datetime | None = None

    @field_validator("token_usage", mode="before")
    @classmethod
    def _parse_json(cls, v: object) -> object:
        if isinstance(v, str):
            return json.loads(v or "{}")
        return v


class SwarmFinalOutput(BaseModel):
    run_id: str
    answers: dict[str, ConfirmedEntrySchema]
    confirmed_layer: list[ConfirmedEntrySchema]
    termination_round: int
    termination_reason: Literal["equilibrium", "max_rounds", "budget"]
    metadata: dict[str, Any] = {}


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
    amendments: list[AmendmentSchema] = []
    reputation: list[ReputationSchema] = []
    final_output: SwarmFinalOutput | None = None


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    current_round: int
    termination_reason: str | None = None
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

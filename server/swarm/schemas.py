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


class AuditCitation(BaseModel):
    id: str
    run_id: str
    citing_agent_id: str
    cited_entry_id: str
    citing_entry_id: str | None = None
    round: int
    created_at: datetime


class AuditVote(BaseModel):
    id: str
    run_id: str
    voter_agent_id: str
    voted_entry_id: str
    thread_id: str
    round: int
    created_at: datetime


class AuditResponse(BaseModel):
    run_id: str
    all_draft_entries: list[DraftEntrySchema]
    citations: list[AuditCitation]
    votes: list[AuditVote]
    confirmed_entries: list[ConfirmedEntrySchema]

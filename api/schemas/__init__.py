"""Pydantic request/response schemas for the Agents API. Used for validation in the API routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentBase(BaseModel):
    """Shared agent fields used by create and response schemas."""

    name: str
    description: str = Field(description="Role description, e.g. 'Sales agent'.")
    system_prompt: str = Field(description="System prompt prepended to every LLM call.")
    provider: Literal["openai", "anthropic", "groq"]
    model: str = Field(description="Model identifier, e.g. 'gpt-4o'.")
    tools: list[str] = Field(
        default_factory=list, description="Tool names available to this agent."
    )
    connections: list[str] = Field(
        default_factory=list,
        description="UUIDs of agents this agent may delegate work to.",
    )


class AgentCreate(AgentBase):
    """Request body for creating or fully replacing an agent."""


class AgentUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    provider: Literal["openai", "anthropic", "groq"] | None = None
    model: str | None = None
    tools: list[str] | None = None
    connections: list[str] | None = None


class AgentResponse(AgentBase):
    """Agent representation returned by the API, including its generated id."""

    id: str


class AgentRunRequest(BaseModel):
    """Request body for running an agent."""

    prompt: str = Field(description="The user message to send to the agent.")


class ToolCall(BaseModel):
    """Record of a single tool invocation during an agent run."""

    name: str
    input: dict[str, Any]
    output: str


class AgentRunResponse(BaseModel):
    """Response from an agent run."""

    agent_id: str
    response: str
    tools_used: list[ToolCall] = Field(
        default_factory=list, description="Tool calls made during this run, in order."
    )


class KnowledgeFileBase(BaseModel):
    """Shared knowledge-file fields used by create and response schemas."""

    name: str = Field(description="Human-readable filename.")
    content: str = Field(description="Full text content of the file.")


class KnowledgeFileCreate(KnowledgeFileBase):
    """Request body for creating a knowledge file."""

    id: str | None = None


class KnowledgeFileUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = None
    content: str | None = None


class KnowledgeFileResponse(KnowledgeFileBase):
    """Knowledge-file representation returned by the API, including its generated id."""

    id: str


_OPENAI_DEFAULT_MODEL = "gpt-4.1-nano"
_ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class OpenAIPromptRequest(BaseModel):
    """Request body for testing OpenAI connectivity."""

    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(_OPENAI_DEFAULT_MODEL, examples=[_OPENAI_DEFAULT_MODEL])


class AnthropicPromptRequest(BaseModel):
    """Request body for testing Anthropic connectivity."""

    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(_ANTHROPIC_DEFAULT_MODEL, examples=[_ANTHROPIC_DEFAULT_MODEL])


class GroqPromptRequest(BaseModel):
    """Request body for testing Groq connectivity."""

    prompt: str = Field(..., examples=["Hello"])
    model: str = Field(_GROQ_DEFAULT_MODEL, examples=[_GROQ_DEFAULT_MODEL])


class PromptResponse(BaseModel):
    """Response from a provider connectivity test."""

    response: str


class ToolInfo(BaseModel):
    """Schema for a single tool entry returned by the tool registry."""

    name: str
    description: str
    parameters: dict[str, Any]


class FilesToolRequest(BaseModel):
    """Request body for directly invoking the files tool handler."""

    action: str = Field(..., description="'list' or 'read'.")
    file_name: str | None = Field(None, description="Required when action is 'read'.")
    files: dict[str, str] = Field(..., description="Mock file store: name -> content.")


class FilesToolResponse(BaseModel):
    """Response from the files tool handler."""

    result: str


# ── Simulation ────────────────────────────────────────────────────────────────

_SimStepType = Literal[
    # V0 (unchanged)
    "system", "agent-to-agent", "tool", "agent-to-source",
    # ECSAS
    "bid", "abstain", "bb-post", "bb-cite", "bb-vote",
    "bb-promote", "bb-delete", "bb-mention",
    "amendment", "amendment-approved", "amendment-rejected",
    "convergence",
]


class SimulationStep(BaseModel):
    """A single event in the simulation log, mirroring the frontend SimStep type."""

    id: str
    ts: str
    label: str
    msg: str
    type: _SimStepType
    target: str | None = None
    node_id: str | None = None
    from_id: str | None = None
    to_id: str | None = None


class SimulationRunRequest(BaseModel):
    """Request body for running a topology simulation."""

    prompt: str = Field(description="The prompt broadcast to all agents.")
    rounds: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Discussion rounds after the initial broadcast.",
    )


class SimulationRunResponse(BaseModel):
    """Ordered list of simulation steps returned after the run completes."""

    steps: list[SimulationStep]

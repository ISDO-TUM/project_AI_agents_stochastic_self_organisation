"""Pydantic request/response schemas for the Agents API. Used for validation in the API routes."""

from __future__ import annotations

import re
import uuid as _uuid_module
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.llm.model_catalogue import ALLOWED_MODEL_IDS

# ---------------------------------------------------------------------------
# Field-length constants (defence against token-exhaustion / DoS)
# ---------------------------------------------------------------------------

_MAX_NAME_LEN = 200
_MAX_DESCRIPTION_LEN = 1_000
_MAX_SYSTEM_PROMPT_LEN = 8_000
_MAX_PROMPT_LEN = 4_000
_MAX_FILE_NAME_LEN = 255
_MAX_FILE_CONTENT_LEN = 500_000  # 500 KB plain-text ceiling
_MAX_RULESET_LEN = 4_000
_MAX_TOOLS_COUNT = 20
_MAX_CONNECTIONS_COUNT = 50
_MAX_AGENT_CONTEXT_VALUE_LEN = 8_000
_MAX_AGENT_CONTEXT_ENTRIES = 100

# Expose as ALLOWED_MODELS for backwards compatibility with tests
ALLOWED_MODELS: frozenset[str] = ALLOWED_MODEL_IDS

# ---------------------------------------------------------------------------
# UUID validator helper
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _validate_uuid(v: str | None, field_name: str = "id") -> str | None:
    """Reject non-UUID strings when an id is explicitly supplied."""
    if v is None:
        return v
    if not _UUID_RE.match(v):
        raise ValueError(
            f"{field_name} must be a valid UUID (e.g. '550e8400-e29b-41d4-a716-446655440000')."
        )
    return v

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

ProviderType = Literal["openai", "anthropic", "groq", "gemini"]
ModelType = Literal["chat", "embedding"]


class Model(BaseModel):
    """Available LLM model metadata."""

    id: str = Field(description="Model identifier, e.g. 'gpt-4o'.")
    name: str = Field(description="Display name, e.g. 'GPT-4o'.")
    provider: ProviderType
    type: ModelType


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentBase(BaseModel):
    """Shared agent fields used by create and response schemas."""

    name: str = Field(max_length=_MAX_NAME_LEN)
    description: str = Field(
        description="Role description, e.g. 'Sales agent'.",
        max_length=_MAX_DESCRIPTION_LEN,
    )
    system_prompt: str = Field(
        description="System prompt prepended to every LLM call.",
        max_length=_MAX_SYSTEM_PROMPT_LEN,
    )
    provider: ProviderType
    model: str = Field(description="Model identifier, e.g. 'gpt-4o'.")
    tools: list[str] = Field(
        default_factory=list,
        description="Tool names available to this agent.",
        max_length=_MAX_TOOLS_COUNT,
    )
    connections: list[str] = Field(
        default_factory=list,
        description="UUIDs of agents this agent may delegate work to.",
        max_length=_MAX_CONNECTIONS_COUNT,
    )

    @field_validator("model")
    @classmethod
    def model_must_be_allowlisted(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(
                f"Model '{v}' is not in the allowed model list. "
                f"Choose from: {sorted(ALLOWED_MODELS)}"
            )
        return v


class AgentCreate(AgentBase):
    """Request body for creating or fully replacing an agent."""

    id: str | None = Field(
        default=None,
        description=(
            "Optional caller-supplied UUID. When omitted the server generates one. "
            "Useful for canvas imports that need to preserve cross-references."
        ),
    )

    @field_validator("id")
    @classmethod
    def id_must_be_uuid(cls, v: str | None) -> str | None:
        return _validate_uuid(v, "id")


class AgentUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = Field(default=None, max_length=_MAX_NAME_LEN)
    description: str | None = Field(default=None, max_length=_MAX_DESCRIPTION_LEN)
    system_prompt: str | None = Field(default=None, max_length=_MAX_SYSTEM_PROMPT_LEN)
    provider: ProviderType | None = None
    model: str | None = None
    tools: list[str] | None = Field(default=None, max_length=_MAX_TOOLS_COUNT)
    connections: list[str] | None = Field(default=None, max_length=_MAX_CONNECTIONS_COUNT)

    @field_validator("model")
    @classmethod
    def model_must_be_allowlisted(cls, v: str | None) -> str | None:
        if v is not None and v not in ALLOWED_MODELS:
            raise ValueError(
                f"Model '{v}' is not in the allowed model list. "
                f"Choose from: {sorted(ALLOWED_MODELS)}"
            )
        return v


class AgentResponse(AgentBase):
    """Agent representation returned by the API, including its generated id."""

    id: str


class AgentRunRequest(BaseModel):
    """Request body for running an agent."""

    prompt: str = Field(
        description="The user message to send to the agent.",
        min_length=1,
        max_length=_MAX_PROMPT_LEN,
    )


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


# ---------------------------------------------------------------------------
# Trials
# ---------------------------------------------------------------------------


class TrialCreate(BaseModel):
    """Request body for starting a new trial.

    A trial represents a single end-to-end forward pass of the MAS:
    from an initial user prompt through all communication rounds to a
    final answer or consensus.
    """

    user_prompt: str = Field(description="The initial user prompt that drives the trial.")
    description: str = Field(
        description="Short human-readable label for the trial, e.g. 'Run 3 - math task'."
    )


class TrialResponse(BaseModel):
    """Trial representation returned by the API."""

    id: str
    user_prompt: str
    description: str
    mode: str | None = None
    status: str
    created_at: str
    completed_at: str | None = None


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


class RoundResponse(BaseModel):
    """Round representation returned by the API.

    Rounds are created in sequence within a trial.  Their auto-incremented
    ``id`` serves as an implicit ordering — lower id means earlier round.
    """

    id: int
    trial_id: str
    round_index: int
    phase: str
    created_at: str


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------


class ConnectionCreate(BaseModel):
    """Request body for creating a directed connection between two agents.

    Connections are scoped to a single round so that the topology can change
    across rounds (e.g. pruning) while the full history is preserved.
    """

    from_agent_id: str = Field(description="ID of the agent sending information.")
    to_agent_id: str = Field(description="ID of the agent receiving information.")


class ConnectionResponse(BaseModel):
    """Connection representation returned by the API."""

    id: int
    round_id: int
    from_agent_id: str | None
    to_agent_id: str | None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class MessageCreate(BaseModel):
    """Request body for adding a message to a connection.

    A message stores the payload transmitted along a connection — this may be
    tool output, a reasoning summary, a vote, or any other agent-produced data.
    """

    message: str | None = Field(
        default=None, description="Message content (tool output, vote, etc.)."
    )


class MessageResponse(BaseModel):
    """Message representation returned by the API."""

    id: int
    connection_id: int
    round_id: int
    from_agent_id: str | None
    to_agent_id: str | None
    message_type: str
    message: str | None
    created_at: str


class MessageTraceResponse(BaseModel):
    """Joined message trace row returned by history query endpoints."""

    id: int
    trial_id: str
    trial_description: str
    round_id: int
    round_index: int
    phase: str
    connection_id: int
    from_agent_id: str | None
    from_agent_name: str
    to_agent_id: str | None
    to_agent_name: str
    message_type: str
    message: str | None
    created_at: str


# ---------------------------------------------------------------------------
# Knowledge files
# ---------------------------------------------------------------------------


class KnowledgeFileBase(BaseModel):
    """Shared knowledge-file fields used by create and response schemas."""

    name: str = Field(
        description="Human-readable filename.",
        max_length=_MAX_FILE_NAME_LEN,
    )
    content: str = Field(
        description="Full text content of the file.",
        max_length=_MAX_FILE_CONTENT_LEN,
    )


class KnowledgeFileCreate(KnowledgeFileBase):
    """Request body for creating a knowledge file."""

    id: str | None = None

    @field_validator("id")
    @classmethod
    def id_must_be_uuid(cls, v: str | None) -> str | None:
        return _validate_uuid(v, "id")


class KnowledgeFileUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = Field(default=None, max_length=_MAX_NAME_LEN)
    content: str | None = Field(default=None, max_length=_MAX_FILE_CONTENT_LEN)


class KnowledgeFileResponse(KnowledgeFileBase):
    """Knowledge-file representation returned by the API, including its generated id."""

    id: str


_OPENAI_DEFAULT_MODEL = "gpt-4.1-nano"
_ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_GROQ_DEFAULT_MODEL = "llama-3.3-70b-versatile"


class OpenAIPromptRequest(BaseModel):
    """Request body for testing OpenAI connectivity."""

    prompt: str = Field(..., examples=["Hello"], min_length=1, max_length=_MAX_PROMPT_LEN)
    model: str = Field(_OPENAI_DEFAULT_MODEL, examples=[_OPENAI_DEFAULT_MODEL])

    @field_validator("model")
    @classmethod
    def model_must_be_allowlisted(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(f"Model '{v}' is not in the allowed model list.")
        return v


class AnthropicPromptRequest(BaseModel):
    """Request body for testing Anthropic connectivity."""

    prompt: str = Field(..., examples=["Hello"], min_length=1, max_length=_MAX_PROMPT_LEN)
    model: str = Field(_ANTHROPIC_DEFAULT_MODEL, examples=[_ANTHROPIC_DEFAULT_MODEL])

    @field_validator("model")
    @classmethod
    def model_must_be_allowlisted(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(f"Model '{v}' is not in the allowed model list.")
        return v


class GroqPromptRequest(BaseModel):
    """Request body for testing Groq connectivity."""

    prompt: str = Field(..., examples=["Hello"], min_length=1, max_length=_MAX_PROMPT_LEN)
    model: str = Field(_GROQ_DEFAULT_MODEL, examples=[_GROQ_DEFAULT_MODEL])

    @field_validator("model")
    @classmethod
    def model_must_be_allowlisted(cls, v: str) -> str:
        if v not in ALLOWED_MODELS:
            raise ValueError(f"Model '{v}' is not in the allowed model list.")
        return v


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
    files: dict[str, str] = Field(
        ...,
        description="Mock file store: name -> content.",
        max_length=_MAX_TOOLS_COUNT,
    )


class FilesToolResponse(BaseModel):
    """Response from the files tool handler."""

    result: str


class CreateBenchmarkRequest(BaseModel):
    """Request body for creating a needle-in-a-haystack benchmark."""

    num_agents: int = Field(..., ge=2, le=50)
    sentences_per_agent: int = Field(6, ge=5, le=50)
    include_answer: bool = False


class CreateBenchmarkResponse(BaseModel):
    """Response body for a created majority-vote benchmark."""

    benchmark_id: str
    question: str
    chunks: dict[str, str]
    answer: str | None
    correct_agents: list[str] | None = Field(
        default=None,
        description="Synthetic agent keys (agent_1, …) seeded with the correct answer.",
    )
    correct_agent_count: int = Field(
        description="How many agents (out of num_agents) hold the correct answer."
    )


class EvaluateBenchmarkRequest(BaseModel):
    """Request body for evaluating a generated benchmark answer."""

    benchmark_id: str
    generated_answer: str


class EvaluateBenchmarkResponse(BaseModel):
    """Response body for a majority-vote benchmark evaluation."""

    answer_correct: bool
    correct_answer: str
    generated_answer: str
    normalized_correct_answer: str
    normalized_generated_answer: str
    correct_agents: list[str]


class BenchmarkRecord(BaseModel):
    """Server-side record for a created majority-vote benchmark."""

    question: str
    answer: str
    needle: str
    correct_agents: list[str]
    chunks: dict[str, str]


class CreateDemoBenchmarkRequest(BaseModel):
    """Request body for creating a fixed three-agent importable demo canvas."""

    num_needles: int = Field(1, ge=1, le=25)
    sentences_per_needle: int = Field(5, ge=5, le=50)


class CanvasPosition(BaseModel):
    """Frontend canvas coordinates."""

    x: int
    y: int


class DemoCanvasAgent(BaseModel):
    """Agent object in the importable frontend canvas JSON format."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    system_prompt: str = Field(alias="systemPrompt")
    provider: ProviderType
    model: str
    tools: list[str]
    connections: list[str]
    position: CanvasPosition


class DemoCanvasSource(BaseModel):
    """Source object in the importable frontend canvas JSON format."""

    id: str
    name: str
    type: Literal["text", "document"]
    content: str
    position: CanvasPosition


class DemoCanvasEdge(BaseModel):
    """Edge object in the importable frontend canvas JSON format."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_id: str = Field(alias="from")
    to: str


class DemoCanvas(BaseModel):
    """Importable frontend canvas JSON."""

    agents: list[DemoCanvasAgent]
    sources: list[DemoCanvasSource]
    edges: list[DemoCanvasEdge]


class DemoNeedleRecord(BaseModel):
    """Metadata for one generated needle inside a demo benchmark."""

    question: str
    answer: str
    needle: str
    agent_key: str
    agent_id: str
    source_id: str


class CreateDemoBenchmarkResponse(BaseModel):
    """Response body for an importable three-agent benchmark demo."""

    benchmark_id: str
    agents: list[DemoCanvasAgent]
    sources: list[DemoCanvasSource]
    edges: list[DemoCanvasEdge]
    needles: list[DemoNeedleRecord]


# ── Simulation ────────────────────────────────────────────────────────────────


_ConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
]


class SimulationRunRequest(BaseModel):
    """Request body for running a topology simulation."""

    prompt: str = Field(
        description="The prompt broadcast to all agents.",
        min_length=1,
        max_length=_MAX_PROMPT_LEN,
    )
    rounds: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Discussion rounds after the initial broadcast.",
    )
    mode: _ConsensusMode = Field(
        default="broadcast_no_consensus",
        description=(
            "Consensus algorithm. 'broadcast_no_consensus' = discussion without "
            "a final consensus operator. 'weighted_opinion_pooling' = per-agent "
            "trust vector over neighbours. 'plurality_voting' = global plurality "
            "voting via a coordinator function."
        ),
    )
    agent_context: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional per-agent private context, keyed by agent UUID. When set, "
            "each agent's prompt is prefixed with its private context. Used by "
            "benchmarks (e.g. needle-in-haystack) to seed each agent with a chunk."
        ),
    )

    @field_validator("agent_context")
    @classmethod
    def validate_agent_context(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        if v is None:
            return v
        if len(v) > _MAX_AGENT_CONTEXT_ENTRIES:
            raise ValueError(
                f"agent_context may contain at most {_MAX_AGENT_CONTEXT_ENTRIES} entries, "
                f"got {len(v)}."
            )
        for key, value in v.items():
            if not isinstance(value, str):
                raise ValueError(
                    f"agent_context values must be strings, "
                    f"got {type(value)} for key '{key}'."
                )
            if len(value) > _MAX_AGENT_CONTEXT_VALUE_LEN:
                raise ValueError(
                    f"agent_context['{key}'] exceeds {_MAX_AGENT_CONTEXT_VALUE_LEN} characters."
                )
        return v
    ruleset: str | None = Field(
        default=None,
        max_length=_MAX_RULESET_LEN,
        description=(
            "Optional global ruleset prepended to every agent's system prompt. "
            "Use this to define shared rules that all agents must abide by."
        ),
    )


class SimulationStartResponse(BaseModel):
    """Response returned immediately after a background simulation is scheduled."""

    trial_id: str = Field(description="ID of the trial whose messages can be polled.")
    status: str = Field(default="started", description="Background simulation status.")

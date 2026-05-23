"""Pydantic request/response schemas for the Agents API. Used for validation in the API routes."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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

    name: str
    description: str = Field(description="Role description, e.g. 'Sales agent'.")
    system_prompt: str = Field(description="System prompt prepended to every LLM call.")
    provider: ProviderType
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

    id: str | None = Field(
        default=None,
        description=(
            "Optional caller-supplied UUID. When omitted the server generates one. "
            "Useful for canvas imports that need to preserve cross-references."
        ),
    )


class AgentUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    provider: ProviderType | None = None
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
    from_agent_id: str
    to_agent_id: str


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
    message: str | None


# ---------------------------------------------------------------------------
# Knowledge files
# ---------------------------------------------------------------------------


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


_ConsensusMode = Literal["broadcast", "weighted", "voting"]


class SimulationRunRequest(BaseModel):
    """Request body for running a topology simulation."""

    prompt: str = Field(description="The prompt broadcast to all agents.")
    rounds: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Discussion rounds after the initial broadcast.",
    )
    mode: _ConsensusMode = Field(
        default="broadcast",
        description=(
            "Consensus algorithm. 'broadcast' = current behaviour (no consensus). "
            "'weighted' = per-agent trust vector over neighbours, weighted opinion pooling. "
            "'voting' = global plurality voting via a coordinator function."
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
    ruleset: str | None = Field(
        default=None,
        description=(
            "Optional global ruleset prepended to every agent's system prompt. "
            "Use this to define shared rules that all agents must abide by."
        ),
    )


class SimulationRunResponse(BaseModel):
    """Result of a topology simulation."""

    steps: list[SimulationStep]
    consensus: str | None = Field(
        default=None,
        description="Final consensus answer when a consensus mode was used.",
    )
    consensus_agent_id: str | None = Field(
        default=None,
        description=(
            "Agent whose answer was selected as the consensus, if applicable. "
            "Used by benchmarks to evaluate routing/attribution correctness."
        ),
    )
    converged: bool = Field(
        default=False,
        description="True if the consensus loop met its convergence criterion.",
    )
    rounds_used: int = Field(
        default=0,
        description="Number of discussion rounds actually executed.",
    )

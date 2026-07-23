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
    from_agent_name: str | None = None
    to_agent_name: str | None = None


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
# Statistics (collaboration analytics)
# ---------------------------------------------------------------------------


class TrialStatisticsSummary(BaseModel):
    """High-level KPIs describing one trial's collaboration."""

    trial_id: str
    user_prompt: str
    description: str
    mode: str | None = None
    status: str
    created_at: str
    round_count: int
    agent_count: int
    total_messages: int
    total_edges: int
    message_type_counts: dict[str, int]


class AgentStatistics(BaseModel):
    """Per-agent communication activity within a trial."""

    agent_id: str
    agent_name: str
    messages_sent: int
    messages_received: int
    out_degree: int
    in_degree: int
    tool_invocations: int


class EdgeStatistics(BaseModel):
    """Aggregate message volume along one directed agent->agent edge."""

    from_agent_id: str
    from_agent_name: str
    to_agent_id: str
    to_agent_name: str
    message_count: int


class RoundStatistics(BaseModel):
    """Per-round message and active-edge counts for timeline charts."""

    round_id: int
    round_index: int
    phase: str
    message_count: int
    active_edge_count: int


class LangfuseStatisticsSummary(BaseModel):
    """LLM observability KPIs sourced from Langfuse for one trial."""

    trial_id: str
    trace_count: int
    generation_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost: float
    average_latency_ms: float
    slowest_agent_name: str | None
    slowest_model: str | None


class LangfuseAgentStatistics(BaseModel):
    """Per-agent token, cost, and latency metrics from Langfuse."""

    agent_id: str
    agent_name: str
    generation_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost: float
    average_latency_ms: float


class LangfuseModelStatistics(BaseModel):
    """Per-model token, cost, and latency metrics from Langfuse."""

    model: str
    generation_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost: float
    average_latency_ms: float


class LangfuseRoundStatistics(BaseModel):
    """Per-round cost and token metrics from Langfuse metadata."""

    round_index: int
    phase: str
    generation_count: int
    total_tokens: int
    total_cost: float
    average_latency_ms: float


class LangfuseStatisticsResponse(BaseModel):
    """Complete Langfuse statistics payload for one trial."""

    summary: LangfuseStatisticsSummary
    agents: list[LangfuseAgentStatistics]
    models: list[LangfuseModelStatistics]
    rounds: list[LangfuseRoundStatistics]
    available: bool
    message: str | None = None


# ---------------------------------------------------------------------------
# Experiments (groups of trials with identical setup)
# ---------------------------------------------------------------------------


class ExperimentListItem(BaseModel):
    """Lightweight experiment record for selector lists."""

    id: str
    description: str
    trial_count: int
    created_at: str
    mode: str | None = None
    user_prompt: str | None = None


class ExperimentSummary(BaseModel):
    """Averaged KPIs across all trials in one experiment."""

    experiment_id: str
    description: str
    mode: str | None = None
    user_prompt: str | None = None
    trial_count: int
    trial_ids: list[str]
    avg_round_count: float
    avg_agent_count: float
    avg_total_messages: float
    avg_total_edges: float
    message_type_counts: dict[str, float]


class ExperimentAgentStatistics(BaseModel):
    """Per-agent metrics averaged across all trials in an experiment."""

    agent_id: str
    agent_name: str
    avg_messages_sent: float
    avg_messages_received: float
    avg_out_degree: float
    avg_in_degree: float
    avg_tool_invocations: float


class ExperimentEdgeStatistics(BaseModel):
    """Averaged message volume along one directed agent->agent edge."""

    from_agent_id: str
    from_agent_name: str
    to_agent_id: str
    to_agent_name: str
    avg_message_count: float


class ExperimentRoundStatistics(BaseModel):
    """Per-round-index averages across all trials in an experiment."""

    round_index: int
    phase: str
    avg_message_count: float
    avg_active_edge_count: float


class ExperimentLangfuseSummary(BaseModel):
    """Aggregated Langfuse KPIs across all trials in an experiment."""

    experiment_id: str
    trial_count: int
    trace_count: int
    generation_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost: float
    average_latency_ms: float
    slowest_agent_name: str | None
    slowest_model: str | None


class ExperimentLangfuseResponse(BaseModel):
    """Complete Langfuse payload aggregated for one experiment."""

    summary: ExperimentLangfuseSummary
    agents: list[LangfuseAgentStatistics]
    models: list[LangfuseModelStatistics]
    rounds: list[LangfuseRoundStatistics]
    available: bool
    message: str | None = None


# ---------------------------------------------------------------------------
# Consistency (cross-trial answer similarity within an experiment)
# ---------------------------------------------------------------------------


class PairwiseSimilarity(BaseModel):
    """Cosine similarity between the final answers of two trials."""

    trial_id_a: str
    trial_id_b: str
    cosine_similarity: float


class ConsistencyReport(BaseModel):
    """Answer consistency report for all trials in one experiment."""

    experiment_id: str
    trial_count: int
    trials_with_answers: int
    avg_cosine_similarity: float | None = None
    pairwise_scores: list[PairwiseSimilarity]
    ai_summary: str | None = None
    available: bool
    message: str | None = None


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
    skip_injection_check: bool = Field(
        default=False,
        description="Skip prompt-injection scanning. Set only for trusted document uploads.",
    )

    @field_validator("id")
    @classmethod
    def id_must_be_uuid(cls, v: str | None) -> str | None:
        return _validate_uuid(v, "id")


class KnowledgeFileUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = Field(default=None, max_length=_MAX_NAME_LEN)
    content: str | None = Field(default=None, max_length=_MAX_FILE_CONTENT_LEN)
    skip_injection_check: bool = False


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
    "bidding",
]

_TopologyMode = Literal["static", "dynamic"]


class SimulationRunRequest(BaseModel):
    """Request body for ``POST /api/simulation/run``.

    ``engine`` selects the reasoning engine. ``topology`` (default) runs the V0
    engine as a background task with REST polling for live updates. ``swarm``
    runs the ECSAS engine and streams ``SimulationStep`` events over SSE
    (groundwork; the concrete pipeline lands in a later PR).
    """

    engine: Literal["topology", "swarm"] = Field(
        default="topology",
        description="Reasoning engine: 'topology' (V0, background+poll) or 'swarm' (ECSAS, SSE).",
    )
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
            "voting via a coordinator function. 'bidding' = bidding-based "
            "consensus (not yet implemented)."
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
                    f"agent_context values must be strings, got {type(value)} for key '{key}'."
                )
            if len(value) > _MAX_AGENT_CONTEXT_VALUE_LEN:
                raise ValueError(
                    f"agent_context['{key}'] exceeds {_MAX_AGENT_CONTEXT_VALUE_LEN} characters."
                )
        return v

    # ── Swarm-engine overrides (ignored for engine="topology") ──────────────
    swarm_min_takers: int | None = Field(default=None, ge=1, le=20)
    swarm_max_takers: int | None = Field(default=None, ge=1, le=20)
    swarm_min_rounds: int | None = Field(default=None, ge=1, le=5)
    swarm_invite_floor: float | None = Field(default=None, ge=0.0, le=1.0)
    swarm_decay_rounds: int | None = Field(default=None, ge=1, le=10)
    swarm_token_budget: int | None = Field(default=None, ge=5000, le=500000)
    swarm_max_amendments: int | None = Field(default=None, ge=0, le=5)
    swarm_k_attention: int | None = Field(default=None, ge=3, le=30)
    swarm_skip_auction: bool = False

    ruleset: str | None = Field(
        default=None,
        max_length=_MAX_RULESET_LEN,
        description=(
            "Optional global ruleset prepended to every agent's system prompt. "
            "Use this to define shared rules that all agents must abide by."
        ),
    )
    topology: _TopologyMode = Field(
        default="static",
        description=(
            "Graph mode. 'static' = connections fixed at run start (current behaviour). "
            "'dynamic' = agents discover peers via the registry tool and choose who to "
            "hear from each round via a CONNECT: line."
        ),
    )
    fanout: int = Field(
        default=3,
        ge=0,
        le=10,
        description=(
            "Max neighbours an agent may connect to per round in dynamic mode. "
            "0 means unlimited (no cap) — every relevant peer an agent finds is kept."
        ),
    )
    iterations: int = Field(
        default=1,
        ge=1,
        le=10,
        description=(
            "Number of sequential trial runs to execute under the same experiment. "
            "All runs share the same setup hash and feed into the same aggregated statistics."
        ),
    )
    parent_run_id: str | None = Field(
        default=None,
        description=(
            "swarm engine only: a prior swarm run to carry ratified findings forward "
            "from, as a multi-turn contract session. Must be a completed (non-'running') "
            "run — validated before the SSE stream opens."
        ),
    )
    # swarm engine only: optional overrides for SwarmRunConfig. Each defaults to
    # None, meaning "omit -> today's SwarmRunConfig default applies" (bounds
    # copied verbatim from market_hive.schemas.SwarmRunConfig).
    min_takers: int | None = Field(default=None, ge=1, le=10)
    max_takers: int | None = Field(default=None, ge=1, le=20)
    min_rounds: int | None = Field(default=None, ge=1, le=5)
    max_rounds: int | None = Field(default=None, ge=2, le=20)
    token_budget: int | None = Field(default=None, ge=5_000, le=500_000)
    max_amendments: int | None = Field(default=None, ge=0, le=5)
    decay_rounds: int | None = Field(default=None, ge=1, le=10)
    invite_floor: float | None = Field(default=None, ge=0.0, le=1.0)
    demo_mode: bool | None = Field(default=None)


class SimulationStartResponse(BaseModel):
    """Response returned immediately after a background simulation is scheduled."""

    experiment_id: str = Field(description="ID of the experiment that owns the scheduled trials.")
    trial_id: str = Field(description="ID of the first trial (used for live message streaming).")
    trial_ids: list[str] = Field(description="IDs of all scheduled trials.")
    status: str = Field(default="started", description="Background simulation status.")


# ── Topology benchmark suites ────────────────────────────────────────────────


_BenchmarkConsensusMode = Literal[
    "broadcast_no_consensus",
    "weighted_opinion_pooling",
    "plurality_voting",
    "bidding",
]


class BenchmarkDatasetSummary(BaseModel):
    """Built-in benchmark dataset option shown in the topology UI."""

    id: str
    name: str
    description: str
    default_prompt: str
    evaluator_type: Literal["exact_match"]
    metrics: list[str]
    min_agents: int = 2


class BenchmarkMechanismRequest(BaseModel):
    """One consensus mechanism and repetition count inside a benchmark suite."""

    mode: _BenchmarkConsensusMode
    topology: _TopologyMode = "static"
    runs: int = Field(ge=1, le=20)


class BenchmarkSuiteCreateRequest(BaseModel):
    """Request body for creating a topology benchmark suite."""

    prompt: str = Field(min_length=1, max_length=_MAX_PROMPT_LEN)
    dataset_id: str = Field(min_length=1, max_length=120)
    topology: _TopologyMode = "static"
    fanout: int = Field(default=3, ge=0, le=10)
    rounds: int = Field(default=3, ge=1, le=10)
    mechanisms: list[BenchmarkMechanismRequest] = Field(min_length=1, max_length=8)

    @field_validator("mechanisms")
    @classmethod
    def mechanisms_must_be_unique(
        cls, v: list[BenchmarkMechanismRequest]
    ) -> list[BenchmarkMechanismRequest]:
        keys = [(item.topology, item.mode) for item in v]
        if len(keys) != len(set(keys)):
            raise ValueError("Each topology/consensus pair may appear only once.")
        return v


class BenchmarkSuiteStartResponse(BaseModel):
    """Response returned after a benchmark suite has been scheduled."""

    suite_id: str
    planned_trials: int
    experiment_ids: list[str]
    trial_ids: list[str]
    status: str = "started"


class BenchmarkSuiteRunResult(BaseModel):
    """One trial result inside a benchmark suite."""

    id: str
    suite_id: str
    experiment_id: str
    trial_id: str
    consensus_mode: str
    topology: str
    run_index: int
    dataset_variant_id: str | None = None
    status: str
    score: dict[str, Any]
    created_at: str
    completed_at: str | None = None


class BenchmarkSuiteSummary(BaseModel):
    """Benchmark suite row plus aggregate progress."""

    id: str
    name: str
    dataset_id: str
    prompt: str
    topology: str
    fanout: int
    rounds: int
    status: str
    planned_trials: int
    completed_trials: int
    created_at: str
    completed_at: str | None = None


class BenchmarkMechanismAggregate(BaseModel):
    """Aggregate result for one consensus mechanism in a suite."""

    consensus_mode: str
    topology: str
    runs: int
    completed: int
    failed: int
    accuracy: float | None = None
    avg_rounds: float | None = None
    avg_messages: float | None = None
    generation_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_tokens: float | None = None
    avg_cost: float | None = None


class BenchmarkSuiteResultsResponse(BaseModel):
    """Detailed benchmark suite result payload."""

    suite: BenchmarkSuiteSummary
    runs: list[BenchmarkSuiteRunResult]
    aggregates: list[BenchmarkMechanismAggregate]


class BenchmarkCanvasResponse(BaseModel):
    """Importable benchmark canvas plus its prompt."""

    dataset_id: str
    prompt: str
    answer: str
    agents: list[DemoCanvasAgent]
    sources: list[DemoCanvasSource]
    edges: list[DemoCanvasEdge]

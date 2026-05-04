"""Pydantic request/response schemas for the Agents API. Used for validation in the API routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class AgentBase(BaseModel):
    """Shared agent fields used by create and response schemas."""

    name: str
    description: str = Field(description="Role description, e.g. 'Sales agent'.")
    system_prompt: str = Field(description="System prompt prepended to every LLM call.")
    provider: Literal["openai", "anthropic"]
    model: str = Field(description="Model identifier, e.g. 'gpt-4o'.")
    tools: list[str] = Field(
        default_factory=list, description="Tool names available to this agent."
    )


class AgentCreate(AgentBase):
    """Request body for creating or fully replacing an agent."""


class AgentUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    provider: Literal["openai", "anthropic"] | None = None
    model: str | None = None
    tools: list[str] | None = None


class AgentResponse(AgentBase):
    """Agent representation returned by the API, including its generated id."""

    id: str


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


class KnowledgeFileUpdate(BaseModel):
    """Partial update body; only supplied fields are written to the database."""

    name: str | None = None
    content: str | None = None


class KnowledgeFileResponse(KnowledgeFileBase):
    """Knowledge-file representation returned by the API, including its generated id."""

    id: str

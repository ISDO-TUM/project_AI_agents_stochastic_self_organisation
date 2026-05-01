"""Pydantic request/response schemas for the Agents API. Used for validation in the API routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    provider: Literal["openai", "anthropic"] | None = None
    model: str | None = None
    tools: list[str] | None = None
    connections: list[str] | None = None


class AgentResponse(AgentBase):
    """Agent representation returned by the API, including its generated id."""

    id: str

"""Core dataclasses passed between Pool, Topology, and Consensus layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Task:
    """A task posed to the swarm."""

    prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Proposal:
    """One agent's response in one round."""

    agent_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RoundState:
    """Snapshot of one consensus round, used for telemetry and as input to next round."""

    round_index: int
    proposals: dict[str, Proposal]
    scores: dict[str, float]
    aggregate: str
    agreement: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsensusResult:
    """Final output of `ConsensusProtocol.run` — answer plus full per-round telemetry."""

    answer: str
    rounds: list[RoundState]
    stopped_reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

"""Abstract contracts for the consensus loop's four pluggable parts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from api.simulation.pool import Pool
from api.simulation.topology import Topology
from api.simulation.types import ConsensusResult, Proposal, RoundState, Task


@runtime_checkable
class AggregationStrategy(Protocol):
    """Combine per-round proposals + scores into a single candidate answer.

    Returns (answer, agreement) where agreement is in [0, 1].
    """

    def aggregate(
        self,
        proposals: dict[str, Proposal],
        scores: dict[str, float],
    ) -> tuple[str, float]: ...


@runtime_checkable
class ScoringStrategy(Protocol):
    """Compute per-agent weight / contribution for the current round."""

    def score(
        self,
        proposals: dict[str, Proposal],
        task: Task,
        topology: Topology,
        aggregator: AggregationStrategy,
    ) -> dict[str, float]: ...


@runtime_checkable
class MessagePolicy(Protocol):
    """Build per-agent context strings shown to each agent in the next round."""

    def build_contexts(
        self,
        history: list[RoundState],
        topology: Topology,
    ) -> dict[str, str]: ...


@runtime_checkable
class StoppingCriterion(Protocol):
    """Decide whether to halt the consensus loop."""

    def should_stop(self, history: list[RoundState]) -> tuple[bool, str | None]: ...


class ConsensusProtocol(ABC):
    """Top-level entry point: run a consensus over a pool + topology + task."""

    @abstractmethod
    def run(self, pool: Pool, topology: Topology, task: Task) -> ConsensusResult: ...

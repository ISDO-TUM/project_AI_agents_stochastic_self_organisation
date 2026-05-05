"""Concrete strategies that compose into consensus protocols."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from api.simulation.consensus.base import AggregationStrategy
from api.simulation.topology import Topology
from api.simulation.types import Proposal, RoundState, Task


# --- Aggregation -------------------------------------------------------------


class WeightedMajorityAggregation:
    """Pick the proposal text with the highest summed agent score; agreement = its share."""

    def aggregate(
        self,
        proposals: dict[str, Proposal],
        scores: dict[str, float],
    ) -> tuple[str, float]:
        if not proposals:
            return "", 0.0
        bucket: dict[str, float] = {}
        for aid, p in proposals.items():
            bucket[p.content] = bucket.get(p.content, 0.0) + scores.get(aid, 1.0)
        total = sum(bucket.values()) or 1.0
        winner, weight = max(bucket.items(), key=lambda kv: kv[1])
        return winner, weight / total


# --- Scoring -----------------------------------------------------------------


class UniformScoring:
    """Every agent gets equal weight — DyLAN-free baseline for ablations."""

    def score(
        self,
        proposals: dict[str, Proposal],
        task: Task,  # noqa: ARG002
        topology: Topology,  # noqa: ARG002
        aggregator: AggregationStrategy,  # noqa: ARG002
    ) -> dict[str, float]:
        if not proposals:
            return {}
        w = 1.0 / len(proposals)
        return {aid: w for aid in proposals}


# A quality function rates how good a coalition's joint output is, in [0, 1].
# Swap in an LLM-judge once Pair A's judge agent is available.
QualityFn = Callable[[dict[str, Proposal], Task], float]


def cluster_strength_quality(coalition: dict[str, Proposal], task: Task) -> float:  # noqa: ARG001
    """Fraction of the coalition that agrees on its most popular answer.

    Default Shapley value function: cheap (O(|S|), no LLM call), bounded in [0, 1],
    and rewards adding agents that strengthen the majority. Counts exact string
    matches only — for free-form text, supply an embedding- or judge-based
    `quality_fn` instead.
    """
    if not coalition:
        return 0.0
    counts = Counter(p.content for p in coalition.values())
    return max(counts.values()) / len(coalition)


@dataclass
class MonteCarloShapleyScoring:
    """Shapley value via random permutations (SelfOrg-style credit assignment).

    Each agent's score is its expected marginal contribution to coalition quality
    under `samples` random orderings. Final scores are shifted non-negative and
    normalised to sum to 1 so they plug straight into a weighted aggregator.
    """

    samples: int = 32
    quality_fn: QualityFn = field(default=cluster_strength_quality)
    seed: int | None = None

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)  # noqa: S311

    def score(
        self,
        proposals: dict[str, Proposal],
        task: Task,
        topology: Topology,  # noqa: ARG002
        aggregator: AggregationStrategy,  # noqa: ARG002
    ) -> dict[str, float]:
        ids = list(proposals.keys())
        if not ids:
            return {}
        marginals: dict[str, float] = dict.fromkeys(ids, 0.0)
        for _ in range(self.samples):
            perm = ids[:]
            self._rng.shuffle(perm)  # noqa: S311
            coalition: dict[str, Proposal] = {}
            running = self.quality_fn(coalition, task)
            for aid in perm:
                coalition[aid] = proposals[aid]
                value = self.quality_fn(coalition, task)
                marginals[aid] += value - running
                running = value
        for aid in ids:
            marginals[aid] /= self.samples
        shift = min(marginals.values())
        if shift < 0:
            marginals = {k: v - shift for k, v in marginals.items()}
        total = sum(marginals.values())
        if total <= 0:
            w = 1.0 / len(ids)
            return dict.fromkeys(ids, w)
        return {aid: v / total for aid, v in marginals.items()}


# --- Message policy ----------------------------------------------------------


@dataclass
class TopKNeighborMessagePolicy:
    """Each agent sees its K highest-scoring neighbors' proposals (Symphony/AgentNet)."""

    k: int = 3
    include_aggregate: bool = True

    def build_contexts(
        self,
        history: list[RoundState],
        topology: Topology,
    ) -> dict[str, str]:
        if not history:
            return {}
        last = history[-1]
        contexts: dict[str, str] = {}
        for aid in topology.nodes():
            neighbors = topology.neighbors(aid)
            ranked = sorted(neighbors, key=lambda n: last.scores.get(n, 0.0), reverse=True)
            chosen = [n for n in ranked[: self.k] if n in last.proposals]
            lines = [f"- Agent {n}: {last.proposals[n].content}" for n in chosen]
            ctx = "Peer responses from previous round:\n" + (
                "\n".join(lines) if lines else "(none)"
            )
            if self.include_aggregate and last.aggregate:
                ctx += f"\n\nCurrent group consensus draft:\n{last.aggregate}"
            contexts[aid] = ctx
        return contexts


# --- Stopping ----------------------------------------------------------------


@dataclass
class MaxRoundsOrAgreementStop:
    """Stop after `max_rounds`, or once round agreement reaches `agreement_threshold`."""

    max_rounds: int = 4
    agreement_threshold: float = 0.9

    def should_stop(self, history: list[RoundState]) -> tuple[bool, str | None]:
        if not history:
            return False, None
        if history[-1].agreement >= self.agreement_threshold:
            return True, "agreement_threshold_reached"
        if len(history) >= self.max_rounds:
            return True, "max_rounds_reached"
        return False, None

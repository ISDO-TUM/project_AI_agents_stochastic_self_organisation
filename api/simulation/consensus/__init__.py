"""Consensus protocols — pluggable strategies + concrete implementations.

A consensus protocol is an orchestrator over four swappable strategies:

    - AggregationStrategy : per-round proposals + scores  -> (answer, agreement)
    - ScoringStrategy     : per-agent weight / credit for the round
    - MessagePolicy       : what each agent sees in the next round
    - StoppingCriterion   : when to halt the loop

Adding a new approach from a paper
----------------------------------

Most papers change only one or two of the four parts. Three patterns:

1. *Strategy swap* (most common). Identify which part the paper changes,
   write a class in ``strategies.py`` that satisfies the matching Protocol in
   ``base.py`` (no subclassing — duck-typed), then pass it to an existing
   protocol::

       ShapleySwarmConsensus(scoring=LLMJudgeScoring(judge=...))

2. *Ablation bundle*. Group several swaps into a named class for clarity::

       def make_dylan() -> ShapleySwarmConsensus:
           return ShapleySwarmConsensus(
               scoring=LLMJudgeScoring(judge=...),
               aggregation=LLMJudgeAggregation(judge=...),
           )

3. *New orchestration*. If the paper changes the loop itself (async gossip,
   hierarchical voting, role-based phases), subclass ``ConsensusProtocol``
   and implement ``run(pool, topology, task) -> ConsensusResult``. Reuse
   strategy classes wherever possible.

Telemetry — the ``ConsensusResult.rounds`` list — is identical across
protocols, so any two approaches can be compared on the same task.
"""

from api.simulation.consensus.base import (
    AggregationStrategy,
    ConsensusProtocol,
    MessagePolicy,
    ScoringStrategy,
    StoppingCriterion,
)
from api.simulation.consensus.shapley_swarm import ShapleySwarmConsensus
from api.simulation.consensus.simple_majority import SimpleMajorityConsensus
from api.simulation.consensus.strategies import (
    MaxRoundsOrAgreementStop,
    MonteCarloShapleyScoring,
    TopKNeighborMessagePolicy,
    UniformScoring,
    WeightedMajorityAggregation,
    cluster_strength_quality,
)

__all__ = [
    "AggregationStrategy",
    "ConsensusProtocol",
    "MaxRoundsOrAgreementStop",
    "MessagePolicy",
    "MonteCarloShapleyScoring",
    "ScoringStrategy",
    "ShapleySwarmConsensus",
    "SimpleMajorityConsensus",
    "StoppingCriterion",
    "TopKNeighborMessagePolicy",
    "UniformScoring",
    "WeightedMajorityAggregation",
    "cluster_strength_quality",
]

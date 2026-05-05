"""Self-organising agent simulation: Pool (Pair A) → Topology (Pair B) → Consensus (Pair C)."""

from api.simulation.consensus import (
    AggregationStrategy,
    ConsensusProtocol,
    MaxRoundsOrAgreementStop,
    MessagePolicy,
    MonteCarloShapleyScoring,
    ScoringStrategy,
    ShapleySwarmConsensus,
    SimpleMajorityConsensus,
    StoppingCriterion,
    TopKNeighborMessagePolicy,
    UniformScoring,
    WeightedMajorityAggregation,
    cluster_strength_quality,
)
from api.simulation.pool import AgentSpec, InMemoryPool, Pool
from api.simulation.topology import CompleteGraphTopology, Topology
from api.simulation.types import ConsensusResult, Proposal, RoundState, Task

__all__ = [
    "AgentSpec",
    "AggregationStrategy",
    "CompleteGraphTopology",
    "ConsensusProtocol",
    "ConsensusResult",
    "InMemoryPool",
    "MaxRoundsOrAgreementStop",
    "MessagePolicy",
    "MonteCarloShapleyScoring",
    "Pool",
    "Proposal",
    "RoundState",
    "ScoringStrategy",
    "ShapleySwarmConsensus",
    "SimpleMajorityConsensus",
    "StoppingCriterion",
    "Task",
    "TopKNeighborMessagePolicy",
    "Topology",
    "UniformScoring",
    "WeightedMajorityAggregation",
    "cluster_strength_quality",
]

"""ShapleySwarmConsensus — first concrete protocol.

Composes Shapley scoring (SelfOrg) + top-K neighbor messaging (AgentNet/Symphony)
+ weighted majority aggregation + max-rounds-or-agreement stop. Every part is
swappable through the constructor so other papers can be tried with no edits here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from api.simulation.consensus.base import (
    AggregationStrategy,
    ConsensusProtocol,
    MessagePolicy,
    ScoringStrategy,
    StoppingCriterion,
)
from api.simulation.consensus.strategies import (
    MaxRoundsOrAgreementStop,
    MonteCarloShapleyScoring,
    TopKNeighborMessagePolicy,
    WeightedMajorityAggregation,
)
from api.simulation.pool import Pool
from api.simulation.topology import Topology
from api.simulation.types import ConsensusResult, Proposal, RoundState, Task


@dataclass
class ShapleySwarmConsensus(ConsensusProtocol):
    """Decentralised consensus inspired by SelfOrg + AgentNet + Symphony."""

    aggregation: AggregationStrategy = field(default_factory=WeightedMajorityAggregation)
    scoring: ScoringStrategy = field(default_factory=MonteCarloShapleyScoring)
    messaging: MessagePolicy = field(default_factory=TopKNeighborMessagePolicy)
    stopping: StoppingCriterion = field(default_factory=MaxRoundsOrAgreementStop)

    def run(self, pool: Pool, topology: Topology, task: Task) -> ConsensusResult:
        history: list[RoundState] = []
        round_idx = 0
        while True:
            contexts = (
                self.messaging.build_contexts(history, topology)
                if history
                else {aid: "" for aid in topology.nodes()}
            )
            proposals = self._collect_proposals(pool, topology, task, contexts)
            scores = self.scoring.score(proposals, task, topology, self.aggregation)
            answer, agreement = self.aggregation.aggregate(proposals, scores)
            history.append(
                RoundState(
                    round_index=round_idx,
                    proposals=proposals,
                    scores=scores,
                    aggregate=answer,
                    agreement=agreement,
                )
            )
            stop, reason = self.stopping.should_stop(history)
            if stop:
                return ConsensusResult(
                    answer=answer,
                    rounds=history,
                    stopped_reason=reason or "stopped",
                )
            round_idx += 1

    @staticmethod
    def _collect_proposals(
        pool: Pool,
        topology: Topology,
        task: Task,
        contexts: dict[str, str],
    ) -> dict[str, Proposal]:
        proposals: dict[str, Proposal] = {}
        for aid in topology.nodes():
            if aid not in pool:
                continue
            agent = pool.get(aid)
            ctx = contexts.get(aid, "")
            prompt = f"{agent.profile}\n\nTask: {task.prompt}" + (f"\n\n{ctx}" if ctx else "")
            content = agent.llm_call(prompt)
            proposals[aid] = Proposal(agent_id=aid, content=content)
        return proposals

"""SimpleMajorityConsensus — the baseline protocol for the first demo.

Plain-English flow (read this to a colleague):

    Round 1 — every agent answers the task independently. We count votes.
              If they all agree, we stop and return that answer.
    Round 2 — each agent is shown all peer answers from round 1 and may revise.
              We count votes again and return the most-voted answer.

No scoring, no Shapley, no LLM judge. Deterministic given fixed agent outputs
"""

from __future__ import annotations

from collections import Counter

from api.simulation.consensus.base import ConsensusProtocol
from api.simulation.pool import Pool
from api.simulation.topology import Topology
from api.simulation.types import ConsensusResult, Proposal, RoundState, Task


class SimpleMajorityConsensus(ConsensusProtocol):
    """Plain majority voting with at most ``max_rounds`` voting iterations."""

    def __init__(self, max_rounds: int = 2) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be >= 1")
        self.max_rounds = max_rounds

    def run(self, pool: Pool, topology: Topology, task: Task) -> ConsensusResult:
        history: list[RoundState] = []

        for round_idx in range(self.max_rounds):
            contexts = self._build_contexts(history, topology)
            proposals = self._collect_proposals(pool, topology, task, contexts)
            answer, agreement = self._tally(proposals)
            scores = self._uniform_scores(proposals)

            history.append(
                RoundState(
                    round_index=round_idx,
                    proposals=proposals,
                    scores=scores,
                    aggregate=answer,
                    agreement=agreement,
                )
            )

            if agreement >= 1.0:
                return ConsensusResult(
                    answer=answer,
                    rounds=history,
                    stopped_reason="unanimous",
                )

        last = history[-1]
        return ConsensusResult(
            answer=last.aggregate,
            rounds=history,
            stopped_reason="max_rounds_reached",
        )

    # --- helpers, each one obvious in isolation -----------------------------

    @staticmethod
    def _collect_proposals(
        pool: Pool,
        topology: Topology,
        task: Task,
        contexts: dict[str, str],
    ) -> dict[str, Proposal]:
        """Ask every agent for an answer. All agents always vote."""
        proposals: dict[str, Proposal] = {}
        for aid in topology.nodes():
            if aid not in pool:
                continue
            agent = pool.get(aid)
            ctx = contexts.get(aid, "")
            prompt = f"{agent.profile}\n\nTask: {task.prompt}" + (f"\n\n{ctx}" if ctx else "")
            proposals[aid] = Proposal(agent_id=aid, content=agent.llm_call(prompt))
        return proposals

    @staticmethod
    def _tally(proposals: dict[str, Proposal]) -> tuple[str, float]:
        """Count votes; return (most-voted answer, fraction of agents on it).

        Ties are broken by the order Counter first encountered the answer,
        which is the proposals' insertion order — deterministic given a
        stable pool, so reruns converge to the same answer.
        """
        if not proposals:
            return "", 0.0
        counts = Counter(p.content for p in proposals.values())
        answer, votes = counts.most_common(1)[0]
        return answer, votes / len(proposals)

    @staticmethod
    def _uniform_scores(proposals: dict[str, Proposal]) -> dict[str, float]:
        """Every agent counts equally — recorded only for telemetry parity."""
        if not proposals:
            return {}
        w = 1.0 / len(proposals)
        return dict.fromkeys(proposals, w)

    @staticmethod
    def _build_contexts(
        history: list[RoundState],
        topology: Topology,
    ) -> dict[str, str]:
        """Round 1: empty context. Round 2+: show all peer answers from last round."""
        if not history:
            return {aid: "" for aid in topology.nodes()}
        last = history[-1]
        contexts: dict[str, str] = {}
        for aid in topology.nodes():
            peers = [n for n in topology.neighbors(aid) if n in last.proposals]
            lines = [f"- Agent {n}: {last.proposals[n].content}" for n in peers]
            contexts[aid] = (
                f"Peer answers from round {last.round_index}:\n"
                + ("\n".join(lines) if lines else "(none)")
                + f"\n\nCurrent leading answer: {last.aggregate}"
            )
        return contexts

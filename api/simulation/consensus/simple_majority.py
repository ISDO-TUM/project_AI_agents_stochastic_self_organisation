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


class SimpleMajorityConsensus(ConsensusProtocol):  # type: ignore[misc]
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

    _VOTE_INSTRUCTION = (
        "\n\nWrite a brief explanation if helpful, then on a new final line write:\n"
        "VOTE: <your final answer in the most concise canonical form>\n"
        "Only the VOTE line is tallied across agents — keep it short, lowercase if "
        "natural, no LaTeX, no punctuation, no extra commentary."
    )

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
            prompt = (
                f"{agent.profile}\n\nTask: {task.prompt}"
                + (f"\n\n{ctx}" if ctx else "")
                + SimpleMajorityConsensus._VOTE_INSTRUCTION
            )
            proposals[aid] = Proposal(agent_id=aid, content=agent.llm_call(prompt))
        return proposals

    @staticmethod
    def _extract_vote(content: str) -> tuple[str, str]:
        """Return (display, key). `display` is the short answer to show; `key` is its
        normalized form used for vote bucketing.

        Prefers the last `VOTE: ...` line. Falls back to the whole content so that
        legacy callers (and the test suite, which uses fixed-string mocks) still tally."""
        for line in reversed(content.splitlines()):
            stripped = line.strip()
            if stripped[:5].upper() == "VOTE:":
                display = stripped[5:].strip().strip("`*\"'")
                return display, SimpleMajorityConsensus._normalize(display)
        return content, SimpleMajorityConsensus._normalize(content)

    @staticmethod
    def _normalize(s: str) -> str:
        """Lowercase, strip whitespace and common math/LaTeX wrappers, collapse spaces."""
        s = s.strip().lower()
        for token in ("\\(", "\\)", "\\[", "\\]", "$", "*", "`", '"'):
            s = s.replace(token, "")
        s = " ".join(s.split())
        return s.rstrip(".!?,:;")

    @staticmethod
    def _tally(proposals: dict[str, Proposal]) -> tuple[str, float]:
        """Count votes; return (winning display, fraction of agents on it).

        Votes are bucketed by a normalized key so cosmetic differences (LaTeX,
        case, trailing punctuation) don't fragment the count. The displayed
        answer comes from the first proposal in insertion order whose key won —
        deterministic for a stable pool.
        """
        if not proposals:
            return "", 0.0
        extracted = {
            aid: SimpleMajorityConsensus._extract_vote(p.content) for aid, p in proposals.items()
        }
        counts = Counter(key for _, key in extracted.values())
        winning_key, votes = counts.most_common(1)[0]
        display = next(d for d, k in extracted.values() if k == winning_key)
        return display, votes / len(proposals)

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
            return dict.fromkeys(topology.nodes(), "")
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

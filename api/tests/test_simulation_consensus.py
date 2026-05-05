"""Smoke tests for the simulation consensus layer using deterministic mock LLMs."""

from __future__ import annotations

from api.simulation import (
    AgentSpec,
    CompleteGraphTopology,
    InMemoryPool,
    MaxRoundsOrAgreementStop,
    MonteCarloShapleyScoring,
    ShapleySwarmConsensus,
    SimpleMajorityConsensus,
    Task,
    TopKNeighborMessagePolicy,
    WeightedMajorityAggregation,
)


def _fixed(answer: str):
    """Return a callable that ignores the prompt and yields a fixed answer."""
    return lambda _prompt: answer


def test_unanimous_agents_converge_in_one_round() -> None:
    pool = InMemoryPool([AgentSpec(id=str(i), profile="agent", llm_call=_fixed("yes")) for i in range(4)])
    topology = CompleteGraphTopology(pool.ids())
    consensus = ShapleySwarmConsensus(
        scoring=MonteCarloShapleyScoring(samples=8, seed=0),
        stopping=MaxRoundsOrAgreementStop(max_rounds=3, agreement_threshold=0.99),
    )

    result = consensus.run(pool, topology, Task(prompt="vote"))

    assert result.answer == "yes"
    assert result.stopped_reason == "agreement_threshold_reached"
    assert len(result.rounds) == 1
    assert result.rounds[0].agreement == 1.0


def test_majority_wins_under_split_vote() -> None:
    agents = [
        AgentSpec(id="a", profile="", llm_call=_fixed("yes")),
        AgentSpec(id="b", profile="", llm_call=_fixed("yes")),
        AgentSpec(id="c", profile="", llm_call=_fixed("yes")),
        AgentSpec(id="d", profile="", llm_call=_fixed("no")),
    ]
    pool = InMemoryPool(agents)
    topology = CompleteGraphTopology(pool.ids())
    consensus = ShapleySwarmConsensus(
        aggregation=WeightedMajorityAggregation(),
        scoring=MonteCarloShapleyScoring(samples=16, seed=42),
        messaging=TopKNeighborMessagePolicy(k=2),
        stopping=MaxRoundsOrAgreementStop(max_rounds=2, agreement_threshold=1.01),
    )

    result = consensus.run(pool, topology, Task(prompt="vote"))

    assert result.answer == "yes"
    assert result.stopped_reason == "max_rounds_reached"
    assert len(result.rounds) == 2
    assert set(result.rounds[0].scores.keys()) == {"a", "b", "c", "d"}
    assert abs(sum(result.rounds[0].scores.values()) - 1.0) < 1e-6


def test_topk_messaging_feeds_neighbor_responses_into_next_round() -> None:
    seen_prompts: list[str] = []

    def recording_call(prompt: str) -> str:
        seen_prompts.append(prompt)
        return "ok"

    pool = InMemoryPool(
        [AgentSpec(id=str(i), profile="agent", llm_call=recording_call) for i in range(3)]
    )
    topology = CompleteGraphTopology(pool.ids())
    consensus = ShapleySwarmConsensus(
        stopping=MaxRoundsOrAgreementStop(max_rounds=2, agreement_threshold=1.01),
    )

    consensus.run(pool, topology, Task(prompt="q"))

    first_round_prompts = seen_prompts[:3]
    second_round_prompts = seen_prompts[3:6]
    assert all("Peer responses" not in p for p in first_round_prompts)
    assert all("Peer responses" in p for p in second_round_prompts)


# --- SimpleMajorityConsensus baseline (ticket acceptance criteria) ----------


def _make_pool(answers: list[str]) -> InMemoryPool:
    return InMemoryPool(
        [
            AgentSpec(id=str(i), profile="agent", llm_call=_fixed(ans))
            for i, ans in enumerate(answers)
        ]
    )


def test_simple_majority_all_agents_vote_every_round() -> None:
    pool = _make_pool(["yes", "yes", "no", "no", "yes"])
    topology = CompleteGraphTopology(pool.ids())

    result = SimpleMajorityConsensus(max_rounds=2).run(pool, topology, Task(prompt="vote"))

    for round_state in result.rounds:
        assert set(round_state.proposals.keys()) == set(pool.ids())


def test_simple_majority_stops_in_at_most_two_rounds() -> None:
    pool = _make_pool(["a", "b", "c", "a", "b"])
    topology = CompleteGraphTopology(pool.ids())

    result = SimpleMajorityConsensus(max_rounds=2).run(pool, topology, Task(prompt="vote"))

    assert len(result.rounds) <= 2
    assert result.stopped_reason in {"unanimous", "max_rounds_reached"}


def test_simple_majority_unanimous_stops_in_round_one() -> None:
    pool = _make_pool(["yes"] * 4)
    topology = CompleteGraphTopology(pool.ids())

    result = SimpleMajorityConsensus(max_rounds=2).run(pool, topology, Task(prompt="vote"))

    assert result.answer == "yes"
    assert result.stopped_reason == "unanimous"
    assert len(result.rounds) == 1


def test_simple_majority_picks_the_majority_answer() -> None:
    pool = _make_pool(["yes", "yes", "yes", "no"])
    topology = CompleteGraphTopology(pool.ids())

    result = SimpleMajorityConsensus(max_rounds=2).run(pool, topology, Task(prompt="vote"))

    assert result.answer == "yes"
    assert result.rounds[-1].agreement == 0.75


def test_simple_majority_converges_consistently_across_runs() -> None:
    """Acceptance criterion: consistent convergence across repeated tests."""
    answers = ["red", "blue", "red", "red", "blue"]
    expected = "red"

    for _ in range(20):
        pool = _make_pool(answers)
        topology = CompleteGraphTopology(pool.ids())
        result = SimpleMajorityConsensus(max_rounds=2).run(pool, topology, Task(prompt="vote"))
        assert result.answer == expected
        assert len(result.rounds) <= 2

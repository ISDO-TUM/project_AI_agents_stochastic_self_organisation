import pytest
from httpx import AsyncClient

from server.db import get_engine
from server.db.tables import trials
from server.topology.routes import benchmark_suites

_DEMO_AGENT_IDS = [
    "a1111111-1111-4111-8111-111111111111",
    "a2222222-2222-4222-8222-222222222222",
    "a3333333-3333-4333-8333-333333333333",
]
_DEMO_SOURCE_IDS = [
    "f1111111-1111-4111-8111-111111111111",
    "f2222222-2222-4222-8222-222222222222",
    "f3333333-3333-4333-8333-333333333333",
]
_DEMO_EDGE_IDS = ["e-pl-cf", "e-pl-fo", "e-cf-fo", "e-pl-f1", "e-cf-f2", "e-fo-f3"]


async def test_create_and_evaluate_single_benchmark_still_work(
    client: AsyncClient,
) -> None:
    created_response = await client.post(
        "/benchmark/needlehaystack/create",
        json={"num_agents": 3, "sentences_per_agent": 5, "include_answer": True},
    )

    assert created_response.status_code == 201
    created = created_response.json()
    assert created["answer"]
    assert len(created["chunks"]) == 3

    evaluated_response = await client.post(
        "/benchmark/needlehaystack/evaluate",
        json={
            "benchmark_id": created["benchmark_id"],
            "generated_answer": created["answer"],
        },
    )

    assert evaluated_response.status_code == 200
    assert evaluated_response.json()["answer_correct"] is True


async def test_create_demo_benchmark_returns_importable_three_agent_canvas(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/benchmark/needlehaystack/demo",
        json={"num_needles": 3, "sentences_per_needle": 5},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["benchmark_id"]
    assert "demo" not in data

    assert set(data) == {"benchmark_id", "agents", "sources", "edges", "needles"}
    assert len(data["agents"]) == 3
    assert len(data["sources"]) == 3
    assert len(data["edges"]) == 6
    assert len(data["needles"]) == 3

    assert [agent["id"] for agent in data["agents"]] == _DEMO_AGENT_IDS
    assert all(agent["name"] for agent in data["agents"])
    assert [agent["connections"] for agent in data["agents"]] == [
        [_DEMO_AGENT_IDS[1], _DEMO_AGENT_IDS[2]],
        [_DEMO_AGENT_IDS[2]],
        [],
    ]
    assert [source["id"] for source in data["sources"]] == _DEMO_SOURCE_IDS
    assert all(source["name"].endswith(".txt") for source in data["sources"])
    assert [edge["id"] for edge in data["edges"]] == _DEMO_EDGE_IDS

    for agent in data["agents"]:
        assert agent["systemPrompt"]
        assert agent["tools"] == ["files"]
        assert agent["provider"] == "openai"

    source_ids = {source["id"] for source in data["sources"]}
    agent_ids = {agent["id"] for agent in data["agents"]}
    attached_source_edges = [
        edge for edge in data["edges"] if edge["from"] in agent_ids and edge["to"] in source_ids
    ]
    assert len(attached_source_edges) == 3

    for source in data["sources"]:
        assert source["type"] == "text"
        assert source["content"].count("Generated context") == 3


async def test_create_demo_benchmark_returns_top_level_needle_metadata(
    client: AsyncClient,
) -> None:
    created = (
        await client.post(
            "/benchmark/needlehaystack/demo",
            json={"num_needles": 4, "sentences_per_needle": 5},
        )
    ).json()

    assert created["benchmark_id"]
    assert len(created["needles"]) == 4

    demo_agent_ids = {agent["id"] for agent in created["agents"]}
    demo_source_ids = {source["id"] for source in created["sources"]}
    for needle in created["needles"]:
        assert needle["question"].startswith("Which person")
        assert needle["answer"]
        assert needle["answer"] in needle["needle"]
        assert needle["agent_key"] in {"agent_1", "agent_2", "agent_3"}
        assert needle["agent_id"] in demo_agent_ids
        assert needle["source_id"] in demo_source_ids


async def test_demo_benchmark_needles_lookup_endpoint_is_removed(
    client: AsyncClient,
) -> None:
    response = await client.get("/benchmark/needlehaystack/missing/needles")

    assert response.status_code == 404


async def test_benchmark_usage_fetches_langfuse_with_trial_rows(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[list[dict[str, object]]] = []

    async def fake_fetch(rows: list[dict[str, object]]) -> tuple[list[object], None]:
        captured.append(rows)
        return [], None

    monkeypatch.setattr(
        benchmark_suites,
        "_fetch_langfuse_observations_multi",
        fake_fetch,
    )

    async with get_engine().connect() as conn:
        await conn.execute(
            trials.insert().values(
                id="trial-benchmark-usage",
                user_prompt="Who is the approved supplier?",
                description="benchmark run",
                mode="plurality_voting",
                status="completed",
                created_at="2026-01-01T00:00:00+00:00",
                completed_at="2026-01-01T00:01:00+00:00",
            )
        )
        await conn.commit()

        usage = await benchmark_suites._llm_usage_for_trials(
            conn,
            ["trial-benchmark-usage"],
        )

    assert usage["total_tokens"] == 0
    assert captured
    assert captured[0][0]["id"] == "trial-benchmark-usage"
    assert captured[0][0]["created_at"] == "2026-01-01T00:00:00+00:00"

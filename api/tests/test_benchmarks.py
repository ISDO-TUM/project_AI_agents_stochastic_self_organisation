from httpx import AsyncClient

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

    demo = data["demo"]
    assert set(demo) == {"agents", "sources", "edges"}
    assert len(demo["agents"]) == 3
    assert len(demo["sources"]) == 3
    assert len(demo["edges"]) == 6

    assert [agent["id"] for agent in demo["agents"]] == _DEMO_AGENT_IDS
    assert [agent["name"] for agent in demo["agents"]] == [
        "Procurement Lead",
        "Compliance Officer",
        "Field Operations",
    ]
    assert [agent["connections"] for agent in demo["agents"]] == [
        [_DEMO_AGENT_IDS[1], _DEMO_AGENT_IDS[2]],
        [_DEMO_AGENT_IDS[2]],
        [],
    ]
    assert [source["id"] for source in demo["sources"]] == _DEMO_SOURCE_IDS
    assert [source["name"] for source in demo["sources"]] == [
        "2026_supplier_contract.txt",
        "compliance_memo_2026.txt",
        "field_ops_legacy_note.txt",
    ]
    assert [edge["id"] for edge in demo["edges"]] == _DEMO_EDGE_IDS

    for agent in demo["agents"]:
        assert agent["systemPrompt"]
        assert agent["tools"] == ["files"]
        assert agent["provider"] == "openai"

    source_ids = {source["id"] for source in demo["sources"]}
    agent_ids = {agent["id"] for agent in demo["agents"]}
    attached_source_edges = [
        edge for edge in demo["edges"] if edge["from"] in agent_ids and edge["to"] in source_ids
    ]
    assert len(attached_source_edges) == 3

    for source in demo["sources"]:
        assert source["type"] == "text"
        assert source["content"].count("Generated context") == 3


async def test_get_demo_benchmark_needles_returns_metadata_by_benchmark_id(
    client: AsyncClient,
) -> None:
    created = (
        await client.post(
            "/benchmark/needlehaystack/demo",
            json={"num_needles": 4, "sentences_per_needle": 5},
        )
    ).json()

    response = await client.get(f"/benchmark/needlehaystack/{created['benchmark_id']}/needles")

    assert response.status_code == 200
    data = response.json()
    assert data["benchmark_id"] == created["benchmark_id"]
    assert len(data["needles"]) == 4

    demo_agent_ids = {agent["id"] for agent in created["demo"]["agents"]}
    demo_source_ids = {source["id"] for source in created["demo"]["sources"]}
    for needle in data["needles"]:
        assert needle["question"].startswith("Which person")
        assert needle["answer"]
        assert needle["answer"] in needle["needle"]
        assert needle["agent_key"] in {"agent_1", "agent_2", "agent_3"}
        assert needle["agent_id"] in demo_agent_ids
        assert needle["source_id"] in demo_source_ids


async def test_get_demo_benchmark_needles_unknown_id_returns_404(
    client: AsyncClient,
) -> None:
    response = await client.get("/benchmark/needlehaystack/missing/needles")

    assert response.status_code == 404

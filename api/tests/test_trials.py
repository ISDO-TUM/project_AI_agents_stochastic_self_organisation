"""End-to-end tests for the trial run + read routes."""

from __future__ import annotations

from unittest.mock import patch

from httpx import AsyncClient


async def _create_agent(client: AsyncClient, name: str, fixed_answer: str) -> str:
    """Create one agent whose system_prompt encodes the answer the mock will return."""
    response = await client.post(
        "/api/agents/",
        json={
            "name": name,
            "description": "test",
            "system_prompt": fixed_answer,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "tools": [],
            "connections": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _mock_openai_returns_system_prompt(prompt: str, model: str) -> str:  # noqa: ARG001
    """Echo the first line of the prompt — which is the agent's system_prompt.

    `_collect_proposals` builds the prompt as ``f"{agent.profile}\\n\\nTask: ..."``,
    so the first line is the agent's profile, which we set to the desired answer.
    """
    return prompt.split("\n", 1)[0]


async def test_run_trial_persists_full_trace(client: AsyncClient) -> None:
    a1 = await _create_agent(client, "a1", "yes")
    a2 = await _create_agent(client, "a2", "yes")
    a3 = await _create_agent(client, "a3", "no")

    with patch("api.routes.trials.call_openai", side_effect=_mock_openai_returns_system_prompt):
        run_response = await client.post(
            "/api/trials/run",
            json={"task_prompt": "vote", "max_rounds": 2, "agent_ids": [a1, a2, a3]},
        )

    assert run_response.status_code == 201, run_response.text
    body = run_response.json()
    assert body["answer"] == "yes"
    assert body["stopped_reason"] in {"unanimous", "max_rounds_reached"}
    assert body["rounds"] >= 1

    trial_id = body["trial_id"]
    fetch_response = await client.get(f"/api/trials/{trial_id}")
    assert fetch_response.status_code == 200, fetch_response.text
    trial = fetch_response.json()

    assert trial["id"] == trial_id
    assert trial["task_prompt"] == "vote"
    assert trial["protocol_name"] == "SimpleMajorityConsensus"
    assert trial["final_answer"] == "yes"
    assert trial["completed_at"] is not None
    assert len(trial["rounds"]) == body["rounds"]

    first_round = trial["rounds"][0]
    assert first_round["round_index"] == 0
    assert {p["agent_id"] for p in first_round["proposals"]} == {a1, a2, a3}
    assert {p["content"] for p in first_round["proposals"]} == {"yes", "no"}
    assert first_round["edges"] == []

    if len(trial["rounds"]) > 1:
        second_round = trial["rounds"][1]
        assert second_round["round_index"] == 1
        # complete graph over 3 nodes => 6 directed edges
        assert len(second_round["edges"]) == 6


async def test_run_trial_unanimous_stops_in_round_one(client: AsyncClient) -> None:
    ids = [await _create_agent(client, f"a{i}", "ship") for i in range(4)]

    with patch("api.routes.trials.call_openai", side_effect=_mock_openai_returns_system_prompt):
        response = await client.post(
            "/api/trials/run",
            json={"task_prompt": "decision", "max_rounds": 2, "agent_ids": ids},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["answer"] == "ship"
    assert body["stopped_reason"] == "unanimous"
    assert body["rounds"] == 1


async def test_run_trial_with_no_agents_returns_400(client: AsyncClient) -> None:
    response = await client.post("/api/trials/run", json={"task_prompt": "x"})
    assert response.status_code == 400


async def test_get_unknown_trial_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/trials/does-not-exist")
    assert response.status_code == 404

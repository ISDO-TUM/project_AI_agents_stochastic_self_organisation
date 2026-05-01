"""Tests for the agents CRUD endpoints."""

from httpx import AsyncClient

_AGENT_PAYLOAD = {
    "name": "SalesBot",
    "description": "Handles inbound sales queries.",
    "system_prompt": "You are a helpful sales agent.",
    "provider": "openai",
    "model": "gpt-4o",
    "tools": ["crm", "search"],
    "connections": [],
}


async def test_create_agent(client: AsyncClient) -> None:
    response = await client.post("/api/agents/", json=_AGENT_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "SalesBot"
    assert "id" in data
    assert data["tools"] == ["crm", "search"]


async def test_list_agents(client: AsyncClient) -> None:
    await client.post("/api/agents/", json=_AGENT_PAYLOAD)
    await client.post("/api/agents/", json={**_AGENT_PAYLOAD, "name": "SupportBot"})

    response = await client.get("/api/agents/")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_agent(client: AsyncClient) -> None:
    created = (await client.post("/api/agents/", json=_AGENT_PAYLOAD)).json()
    response = await client.get(f"/api/agents/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_agent_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/agents/nonexistent-id")
    assert response.status_code == 404


async def test_replace_agent(client: AsyncClient) -> None:
    created = (await client.post("/api/agents/", json=_AGENT_PAYLOAD)).json()
    updated_payload = {**_AGENT_PAYLOAD, "name": "UpdatedBot", "model": "gpt-4o-mini"}

    response = await client.put(f"/api/agents/{created['id']}", json=updated_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "UpdatedBot"
    assert data["model"] == "gpt-4o-mini"


async def test_replace_agent_not_found(client: AsyncClient) -> None:
    response = await client.put("/api/agents/nonexistent-id", json=_AGENT_PAYLOAD)
    assert response.status_code == 404


async def test_patch_agent(client: AsyncClient) -> None:
    created = (await client.post("/api/agents/", json=_AGENT_PAYLOAD)).json()
    response = await client.patch(
        f"/api/agents/{created['id']}",
        json={"name": "PatchedBot", "tools": ["new-tool"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "PatchedBot"
    assert data["tools"] == ["new-tool"]
    assert data["model"] == _AGENT_PAYLOAD["model"]  # unchanged field preserved


async def test_patch_agent_not_found(client: AsyncClient) -> None:
    response = await client.patch("/api/agents/nonexistent-id", json={"name": "X"})
    assert response.status_code == 404


async def test_delete_agent(client: AsyncClient) -> None:
    created = (await client.post("/api/agents/", json=_AGENT_PAYLOAD)).json()
    response = await client.delete(f"/api/agents/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/agents/{created['id']}")
    assert response.status_code == 404


async def test_delete_agent_not_found(client: AsyncClient) -> None:
    response = await client.delete("/api/agents/nonexistent-id")
    assert response.status_code == 404


async def test_create_agent_invalid_provider(client: AsyncClient) -> None:
    payload = {**_AGENT_PAYLOAD, "provider": "google"}
    response = await client.post("/api/agents/", json=payload)
    assert response.status_code == 422


async def test_connections_link_agents(client: AsyncClient) -> None:
    agent_a = (await client.post("/api/agents/", json=_AGENT_PAYLOAD)).json()
    agent_b_payload = {**_AGENT_PAYLOAD, "name": "RouterBot", "connections": [agent_a["id"]]}
    agent_b = (await client.post("/api/agents/", json=agent_b_payload)).json()

    assert agent_a["id"] in agent_b["connections"]

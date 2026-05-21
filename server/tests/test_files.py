"""Tests for the knowledge-files CRUD endpoints."""

from httpx import AsyncClient

_FILE_PAYLOAD = {
    "name": "company_overview.txt",
    "content": "We are a leading AI company focused on autonomous agents.",
}


async def test_create_knowledge_file(client: AsyncClient) -> None:
    response = await client.post("/api/files/", json=_FILE_PAYLOAD)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == _FILE_PAYLOAD["name"]
    assert data["content"] == _FILE_PAYLOAD["content"]
    assert "id" in data


async def test_list_knowledge_files(client: AsyncClient) -> None:
    await client.post("/api/files/", json=_FILE_PAYLOAD)
    await client.post("/api/files/", json={**_FILE_PAYLOAD, "name": "faq.txt"})

    response = await client.get("/api/files/")
    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_get_knowledge_file(client: AsyncClient) -> None:
    created = (await client.post("/api/files/", json=_FILE_PAYLOAD)).json()
    response = await client.get(f"/api/files/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


async def test_get_knowledge_file_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/files/nonexistent-id")
    assert response.status_code == 404


async def test_replace_knowledge_file(client: AsyncClient) -> None:
    created = (await client.post("/api/files/", json=_FILE_PAYLOAD)).json()
    updated_payload = {"name": "updated.txt", "content": "Updated content."}

    response = await client.put(f"/api/files/{created['id']}", json=updated_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "updated.txt"
    assert data["content"] == "Updated content."
    assert data["id"] == created["id"]


async def test_replace_knowledge_file_not_found(client: AsyncClient) -> None:
    response = await client.put("/api/files/nonexistent-id", json=_FILE_PAYLOAD)
    assert response.status_code == 404


async def test_patch_knowledge_file_name(client: AsyncClient) -> None:
    created = (await client.post("/api/files/", json=_FILE_PAYLOAD)).json()
    response = await client.patch(
        f"/api/files/{created['id']}",
        json={"name": "patched_name.txt"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "patched_name.txt"
    assert data["content"] == _FILE_PAYLOAD["content"]  # unchanged field preserved


async def test_patch_knowledge_file_content(client: AsyncClient) -> None:
    created = (await client.post("/api/files/", json=_FILE_PAYLOAD)).json()
    response = await client.patch(
        f"/api/files/{created['id']}",
        json={"content": "Patched content."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Patched content."
    assert data["name"] == _FILE_PAYLOAD["name"]  # unchanged field preserved


async def test_patch_knowledge_file_not_found(client: AsyncClient) -> None:
    response = await client.patch("/api/files/nonexistent-id", json={"name": "x.txt"})
    assert response.status_code == 404


async def test_delete_knowledge_file(client: AsyncClient) -> None:
    created = (await client.post("/api/files/", json=_FILE_PAYLOAD)).json()
    response = await client.delete(f"/api/files/{created['id']}")
    assert response.status_code == 204

    response = await client.get(f"/api/files/{created['id']}")
    assert response.status_code == 404


async def test_delete_knowledge_file_not_found(client: AsyncClient) -> None:
    response = await client.delete("/api/files/nonexistent-id")
    assert response.status_code == 404


async def test_create_knowledge_file_missing_fields(client: AsyncClient) -> None:
    response = await client.post("/api/files/", json={"name": "incomplete.txt"})
    assert response.status_code == 422

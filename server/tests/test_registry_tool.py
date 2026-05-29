from typing import Any

import pytest

import server.tools.builtin.registry as reg


def _agents() -> list[dict[str, Any]]:
    return [
        {"id": "a1", "name": "Sales", "description": "Sells things"},
        {"id": "a2", "name": "Legal", "description": "Reviews contracts"},
        {"id": "a3", "name": "Ops", "description": "Runs logistics"},
    ]


# ── _agent_text + RegistryIndex.build ───────────────────────────────────────


def test_agent_text_includes_metadata_and_file_excerpts() -> None:
    text = reg._agent_text(
        {"id": "a2", "name": "Legal", "description": "Reviews contracts"},
        {"nda.txt": "This non-disclosure agreement governs..."},
    )
    assert "Legal" in text
    assert "Reviews contracts" in text
    assert "nda.txt" in text
    assert "non-disclosure" in text


@pytest.mark.asyncio
async def test_build_embeds_each_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_embed(
        texts: list[str], model: str = reg.DEFAULT_EMBED_MODEL
    ) -> list[list[float]]:
        return [[float(len(t)), 1.0] for t in texts]

    monkeypatch.setattr(reg, "embed_texts", fake_embed)

    index = await reg.RegistryIndex.build(_agents(), files_by_agent={})
    assert set(index.vectors) == {"a1", "a2", "a3"}
    assert all(len(v) == 2 for v in index.vectors.values())


@pytest.mark.asyncio
async def test_build_falls_back_to_lexical_when_embedding_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(texts: list[str], model: str = reg.DEFAULT_EMBED_MODEL) -> list[list[float]]:
        raise RuntimeError("no embedding backend / key")

    monkeypatch.setattr(reg, "embed_texts", boom)

    index = await reg.RegistryIndex.build(_agents(), files_by_agent={})
    assert index.vectors == {}
    assert set(index.texts) == {"a1", "a2", "a3"}


@pytest.mark.asyncio
async def test_build_falls_back_to_lexical_when_embedding_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def none_embed(texts: list[str], model: str = reg.DEFAULT_EMBED_MODEL) -> None:
        return None  # the embeddings module returns None on any failure

    monkeypatch.setattr(reg, "embed_texts", none_embed)

    index = await reg.RegistryIndex.build(_agents(), files_by_agent={})
    assert index.vectors == {}
    assert set(index.texts) == {"a1", "a2", "a3"}


# ── RegistryIndex.search ranking ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_ranks_by_cosine_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    vectors = {"a1": [0.0, 1.0], "a2": [0.7, 0.7], "a3": [1.0, 0.0]}

    async def fake_embed(
        texts: list[str], model: str = reg.DEFAULT_EMBED_MODEL
    ) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]  # query embeds to (1, 0)

    monkeypatch.setattr(reg, "embed_texts", fake_embed)

    index = RegistryIndex(
        agents=_agents(),
        texts={"a1": "x", "a2": "y", "a3": "z"},
        file_names={"a1": [], "a2": [], "a3": []},
        vectors=vectors,
    )
    ranked = await index.search("anything", k=2, exclude_id=None)
    assert [a["id"] for a, _ in ranked] == ["a3", "a2"]


@pytest.mark.asyncio
async def test_search_excludes_self_and_uses_lexical_without_vectors() -> None:
    index = RegistryIndex(
        agents=_agents(),
        texts={
            "a1": "sells things",
            "a2": "reviews contracts legal",
            "a3": "runs logistics",
        },
        file_names={"a1": [], "a2": [], "a3": []},
        vectors={},
    )
    ranked = await index.search("legal contracts", k=3, exclude_id="a1")
    ids = [a["id"] for a, _ in ranked]
    assert "a1" not in ids
    assert ids[0] == "a2"


# ── RegistryTool (list / search / get) ──────────────────────────────────────


def _ctx(index: RegistryIndex, agent_id: str) -> dict[str, Any]:
    return {"registry": index, "agent_id": agent_id}


@pytest.mark.asyncio
async def test_tool_list_excludes_self() -> None:
    index = RegistryIndex(
        agents=_agents(), texts={}, file_names={"a1": [], "a2": [], "a3": []}, vectors={}
    )
    out = await RegistryTool().safe_execute({"action": "list"}, _ctx(index, "a1"))
    assert "a2" in out and "a3" in out
    assert "a1" not in out


@pytest.mark.asyncio
async def test_tool_search_returns_ranked_ids() -> None:
    index = RegistryIndex(
        agents=_agents(),
        texts={"a1": "sells", "a2": "legal contracts", "a3": "logistics"},
        file_names={"a1": [], "a2": [], "a3": []},
        vectors={},
    )
    out = await RegistryTool().safe_execute(
        {"action": "search", "query": "contract review", "limit": 2}, _ctx(index, "a1")
    )
    assert "a2" in out


@pytest.mark.asyncio
async def test_tool_get_returns_profile_with_files() -> None:
    index = RegistryIndex(
        agents=_agents(),
        texts={"a1": "", "a2": "", "a3": ""},
        file_names={"a1": [], "a2": ["nda.txt"], "a3": []},
        vectors={},
    )
    out = await RegistryTool().safe_execute({"action": "get", "agent_id": "a2"}, _ctx(index, "a1"))
    assert "Legal" in out and "Reviews contracts" in out and "nda.txt" in out


@pytest.mark.asyncio
async def test_tool_handles_missing_index_and_bad_args() -> None:
    assert (
        "not available"
        in (await RegistryTool().safe_execute({"action": "list"}, {"agent_id": "a1"})).lower()
    )
    index = RegistryIndex(agents=_agents(), texts={}, file_names={}, vectors={})
    miss = await RegistryTool().safe_execute(
        {"action": "get", "agent_id": "ghost"}, _ctx(index, "a1")
    )
    assert "not found" in miss.lower()
    no_q = await RegistryTool().safe_execute({"action": "search"}, _ctx(index, "a1"))
    assert "query" in no_q.lower()

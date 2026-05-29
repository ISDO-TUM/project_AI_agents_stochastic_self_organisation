"""Phone-registry tool: semantic peer discovery as a pull-model tool.

Discovery is exposed the same way knowledge files are (``FilesTool``): the agent
calls this tool when it wants to find peers, rather than having a directory
pushed into its prompt. ``search`` ranks peers by cosine similarity over their
embedded domain knowledge, with a lexical fallback when no embedding backend is
available. Embedding helpers are imported lazily to avoid the
``server.llm -> server.tools.registry -> this module`` import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..base import Tool

DEFAULT_EMBED_MODEL = "text-embedding-3-small"

_FILE_CHAR_CAP = 500
_TEXT_CHAR_CAP = 2000


async def embed_texts(
    texts: list[str], model: str = DEFAULT_EMBED_MODEL
) -> list[list[float]] | None:
    """Lazy passthrough (breaks the import cycle; patchable in tests).

    Returns ``None`` on failure, mirroring ``server.llm.embeddings.embed_texts``.
    """
    from server.llm.embeddings import embed_texts as _impl

    result: list[list[float]] | None = await _impl(texts, model=model)
    return result


def _cosine(a: list[float], b: list[float]) -> float:
    from server.llm.embeddings import cosine

    result: float = cosine(a, b)
    return result


def _lexical_score(query: str, text: str) -> float:
    """Token-set Jaccard fallback when embeddings are unavailable."""
    qa = set(query.lower().split())
    qb = set(text.lower().split())
    if not qa or not qb:
        return 0.0
    return len(qa & qb) / len(qa | qb)


def _agent_text(agent: dict[str, Any], files: dict[str, str]) -> str:
    """The text representing an agent in the registry (what gets embedded)."""
    parts: list[str] = [agent.get("name") or "", agent.get("description") or ""]
    for name, content in files.items():
        parts.append(f"{name}: {content[:_FILE_CHAR_CAP]}")
    text = "\n".join(p for p in parts if p)
    return text[:_TEXT_CHAR_CAP]


def _format_directory(agents: list[dict[str, Any]], exclude_id: str | None) -> str:
    lines = [
        f"- {a['id']} · {a['name']} — {a.get('description') or 'no description'}"
        for a in agents
        if a["id"] != exclude_id
    ]
    return "\n".join(lines) if lines else "No other agents are available."


@dataclass
class RegistryIndex:
    """In-memory, per-run semantic index over the agent roster."""

    agents: list[dict[str, Any]]
    texts: dict[str, str]
    file_names: dict[str, list[str]]
    vectors: dict[str, list[float]] = field(default_factory=dict)
    embed_model: str = DEFAULT_EMBED_MODEL

    @classmethod
    async def build(
        cls,
        agents: list[dict[str, Any]],
        files_by_agent: dict[str, dict[str, str]],
        embed_model: str = DEFAULT_EMBED_MODEL,
    ) -> RegistryIndex:
        texts = {a["id"]: _agent_text(a, files_by_agent.get(a["id"], {})) for a in agents}
        file_names = {a["id"]: list(files_by_agent.get(a["id"], {})) for a in agents}
        vectors: dict[str, list[float]] = {}
        try:
            vecs = await embed_texts([texts[a["id"]] for a in agents], model=embed_model)
            # ``embed_texts`` returns ``None`` (not raises) on backend failure.
            if vecs is not None:
                vectors = {a["id"]: v for a, v in zip(agents, vecs, strict=True)}
        except Exception:
            vectors = {}  # lexical fallback at search time
        return cls(
            agents=agents,
            texts=texts,
            file_names=file_names,
            vectors=vectors,
            embed_model=embed_model,
        )

    async def search(
        self, query: str, k: int, exclude_id: str | None
    ) -> list[tuple[dict[str, Any], float]]:
        candidates = [a for a in self.agents if a["id"] != exclude_id]
        scored: list[tuple[dict[str, Any], float]]
        if self.vectors:
            try:
                qvecs = await embed_texts([query], model=self.embed_model)
                if not qvecs:
                    raise ValueError("no query embedding")
                qvec = qvecs[0]
                scored = [
                    (a, _cosine(qvec, self.vectors[a["id"]]))
                    for a in candidates
                    if a["id"] in self.vectors
                ]
            except Exception:
                scored = [(a, _lexical_score(query, self.texts[a["id"]])) for a in candidates]
        else:
            scored = [(a, _lexical_score(query, self.texts[a["id"]])) for a in candidates]
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]


class RegistryInput(BaseModel):
    action: Literal["list", "search", "get"] = Field(
        description=(
            "'list' returns every other agent (id, name, short description). "
            "'search' ranks peers by how well they match a free-text 'query' "
            "describing the expertise you need. 'get' returns one peer's full "
            "profile by 'agent_id'."
        )
    )
    query: str | None = Field(
        default=None,
        description="Required when action='search'. The expertise/topic you are looking for.",
    )
    agent_id: str | None = Field(
        default=None,
        description="Required when action='get'. The exact id of the peer to read.",
    )
    limit: int | None = Field(
        default=None,
        description="Optional cap on action='search' results (default 5).",
    )


class RegistryTool(Tool):
    name = "registry"
    description = (
        "Discover other agents you can hear from next round. "
        "Use action='list' for a roster, action='search' with a query to find the "
        "peers most relevant to what you need, or action='get' to read one peer's "
        "profile. After deciding, end your reply with a line: CONNECT: <id>, <id>."
    )
    input_model = RegistryInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        if not isinstance(validated_input, RegistryInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}
        index: RegistryIndex | None = ctx.get("registry")
        self_id: str | None = ctx.get("agent_id")
        if index is None:
            return "Registry not available."

        if inp.action == "list":
            return f"Agents you can contact:\n{_format_directory(index.agents, self_id)}"

        if inp.action == "get":
            target = next((a for a in index.agents if a["id"] == inp.agent_id), None)
            if target is None or target["id"] == self_id:
                return f"Agent '{inp.agent_id}' not found."
            files = index.file_names.get(target["id"], [])
            knowledge = ", ".join(files) if files else "none"
            return (
                f"{target['id']} · {target['name']}\n"
                f"{target.get('description') or 'no description'}\n"
                f"Knowledge files: {knowledge}"
            )

        # action == "search"
        if not (inp.query and inp.query.strip()):
            return "action='search' requires a 'query'."
        k = inp.limit if (inp.limit and inp.limit > 0) else 5
        ranked = await index.search(inp.query, k=k, exclude_id=self_id)
        if not ranked:
            return "No matching agents."
        lines = [
            f"- {a['id']} · {a['name']} (relevance {score:.2f}) — "
            f"{a.get('description') or 'no description'}"
            for a, score in ranked
        ]
        return "Most relevant agents:\n" + "\n".join(lines)

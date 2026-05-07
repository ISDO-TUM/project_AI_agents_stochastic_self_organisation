from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

from ..base import Tool

if TYPE_CHECKING:
    import aiosqlite


class FilesInput(BaseModel):
    action: Literal["list", "read"] = Field(
        description=(
            "'list' returns the names of all knowledge files attached to this agent. "
            "'read' returns the full text content of a specific file."
        )
    )
    file_name: str | None = Field(
        default=None,
        description="Required when action='read'. The exact file name to read, e.g. 'report.txt'.",
    )


class FilesTool(Tool):
    name = "files"
    description = (
        "Access knowledge files attached to this agent. "
        "Use action='list' to discover which files are available, "
        "then action='read' with the exact file_name to retrieve its contents. "
        "Always list first if you are unsure which files exist."
    )
    input_model = FilesInput

    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        assert isinstance(validated_input, FilesInput)
        inp = validated_input
        ctx = context or {}

        # Support both pre-loaded files dict (tests) and live DB context (runtime)
        if "files" in ctx:
            files: dict[str, str] = ctx["files"]
        else:
            files = await self._load_files(ctx)

        if inp.action == "list":
            if not files:
                return "No knowledge files are attached to this agent."
            names = "\n".join(f"- {name}" for name in files)
            return f"Available files:\n{names}"

        file_name = inp.file_name or ""
        if file_name in files:
            return files[file_name]
        available = ", ".join(files) if files else "none"
        return f"File '{file_name}' not found. Available: {available}"

    @staticmethod
    async def _load_files(ctx: dict[str, Any]) -> dict[str, str]:
        db: aiosqlite.Connection = ctx["db"]
        agent_id: str = ctx["agent_id"]
        async with db.execute(
            """
            SELECT kf.name, kf.content
              FROM knowledge_files kf
              JOIN agent_files af ON af.file_id = kf.id
             WHERE af.agent_id = ?
            """,
            (agent_id,),
        ) as cur:
            rows = await cur.fetchall()
        return {r["name"]: r["content"] for r in rows}

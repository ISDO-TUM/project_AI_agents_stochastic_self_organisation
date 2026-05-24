from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..base import Tool


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
        if not isinstance(validated_input, FilesInput):
            return "Invalid input."
        inp = validated_input
        ctx = context or {}

        # The caller pre-loads the agent's files into context, both at runtime
        # and in tests, so the tool never touches the database itself.
        files: dict[str, str] = ctx.get("files") or {}

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

from __future__ import annotations

from typing import Any

TOOL_NAME = "list_files"

TOOL_DESCRIPTION = "List the names of all knowledge files this agent is allowed to access."

TOOL_PARAMETERS = {
    "type": "object",
    "properties": {},
    "required": [],
}


def handle(arguments: dict[str, Any], context: dict[str, Any] | None = None) -> str:
    files: dict[str, str] = (context or {}).get("files", {})
    if not files:
        return "No files are available."
    names = "\n".join(f"- {name}" for name in files)
    return f"Available files:\n{names}"

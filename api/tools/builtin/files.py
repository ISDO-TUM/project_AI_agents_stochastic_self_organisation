from __future__ import annotations

from typing import Any

TOOL_NAME = "files"

TOOL_DESCRIPTION = (
    "Interact with knowledge files attached to this agent. "
    "Use action='list' to see all available files, "
    "or action='read' with a file_name to get a file's content."
)

TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list", "read"],
            "description": "'list' returns available file names; 'read' returns file content.",
        },
        "file_name": {
            "type": "string",
            "description": "Required when action is 'read'. The name of the file to read.",
        },
    },
    "required": ["action"],
}


async def handle(arguments: dict[str, Any], context: dict[str, Any] | None = None) -> str:
    context = context if context is not None else {}

    # Lazy load: if files aren't pre-populated but a loader is provided, fetch now.
    if "files" not in context and "files_loader" in context:
        context["files"] = await context["files_loader"]()

    files: dict[str, str] = context.get("files") or {}
    action = arguments.get("action")

    if action == "list":
        if not files:
            return "No files are available."
        names = "\n".join(f"- {name}" for name in files)
        return f"Available files:\n{names}"

    if action == "read":
        file_name = arguments.get("file_name", "")
        if file_name in files:
            return files[file_name]
        available = ", ".join(files) if files else "none"
        return f"File '{file_name}' not found. Available files: {available}"

    return f"Unknown action '{action}'. Use 'list' or 'read'."

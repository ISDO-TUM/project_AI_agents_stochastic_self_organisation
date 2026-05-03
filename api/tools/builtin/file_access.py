"""File access tool – stub implementation.

The actual file-reading logic will be connected later.  For now the handler
returns a placeholder message so that the tool-use loop can be exercised
end-to-end without side effects.
"""

from __future__ import annotations

from typing import Any

TOOL_NAME = "file_access"

TOOL_DESCRIPTION = "Read the content of a knowledge file that has been assigned to this agent."

TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "file_name": {
            "type": "string",
            "description": "The name of the file to read.",
        },
    },
    "required": ["file_name"],
}


def handle(arguments: dict[str, Any]) -> str:
    """Execute the file_access tool. Currently a no-op stub."""
    file_name = arguments.get("file_name", "")
    return f"[file_access] Content of '{file_name}' will be available once connected."

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import aiosqlite

TOOL_NAME = "files"

TOOL_DESCRIPTION = (
    "Interact with knowledge files attached to this agent. "
    "Use action='list' to see all available files, "
    "or action='read' with a file_name to get a file's content."
)


async def load_context(raw_context: dict[str, Any]) -> dict[str, Any]:
    """Load file names and content for this agent into the tool context."""
    db: aiosqlite.Connection = raw_context["db"]
    agent_id: str = raw_context["agent_id"]
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
    files = {r["name"]: r["content"] for r in rows}
    return {"files": files, "file_names": list(files.keys())}


def context_hint(context: dict[str, Any]) -> str | None:
    """Return a system-prompt snippet listing the attached files, or None if there are none."""
    file_names: list[str] = context.get("file_names", [])
    if not file_names:
        return None
    names = "\n".join(f"- {n}" for n in file_names)
    return (
        f"The following knowledge files are attached to you:\n{names}\n"
        "Use the `files` tool with action='read' to retrieve their contents."
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
    files: dict[str, str] = (context or {}).get("files") or {}
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

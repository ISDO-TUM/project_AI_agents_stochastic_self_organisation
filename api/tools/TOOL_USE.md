# Adding a New Tool

Create `api/tools/builtin/<your_tool>.py` with the following structure:

```python
from __future__ import annotations
from typing import Any

TOOL_NAME = "your_tool"
TOOL_DESCRIPTION = "One sentence describing what this tool does."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "param": {"type": "string", "description": "..."},
    },
    "required": ["param"],
}


async def load_context(raw_context: dict[str, Any]) -> dict[str, Any]:
    """Load any runtime data this tool needs (e.g. from the DB) into the context dict.
    Receives: raw_context with "db" (aiosqlite.Connection) and "agent_id" (str).
    Return an empty dict if no context loading is needed."""
    return {}


def context_hint(context: dict[str, Any]) -> str | None:
    """Return a system-prompt snippet telling the agent what this tool can access.
    Return None if there is nothing dynamic to surface."""
    return None


async def handle(arguments: dict[str, Any], context: dict[str, Any] | None = None) -> str:
    """Execute the tool call and return a string result."""
    ...
```

Then register it in `api/tools/registry.py`:

```python
from api.tools.builtin.your_tool import (
    TOOL_DESCRIPTION, TOOL_NAME, TOOL_PARAMETERS,
    context_hint as your_tool_context_hint,
    handle as your_tool_handle,
    load_context as your_tool_load_context,
)

_TOOLS: dict[str, dict[str, Any]] = {
    ...,
    TOOL_NAME: {
        "description": TOOL_DESCRIPTION,
        "parameters": TOOL_PARAMETERS,
        "handler": your_tool_handle,
        "context_hint": your_tool_context_hint,  # optional
        "context_loader": your_tool_load_context, # optional
    },
}
```

That's it. The tool is automatically available to any agent that lists it in `tools`, injected into the system prompt, and dispatched on LLM tool calls — no changes needed anywhere else.

# Adding a New Tool

Create `api/tools/builtin/<your_tool>.py` with the following structure:

```python
from __future__ import annotations
from typing import Any, Literal

from pydantic import BaseModel, Field
from api.tools.base import Tool


class YourToolInput(BaseModel):
    action: Literal["do_thing"] = Field(description="What to do. Example: 'do_thing'.")
    param: str = Field(description="A required parameter.")
    optional_param: str | None = Field(default=None, description="Optional. Example: 'value'.")


class YourTool(Tool):
    name = "your_tool"
    description = (
        "One or two sentences describing what this tool does and when to use it. "
        "Be specific — the LLM uses this to decide whether to call the tool."
    )
    input_model = YourToolInput

    async def execute(self, validated_input: YourToolInput, context: dict[str, Any] | None = None) -> str:
        """Run the tool and return a string result.

        context contains runtime dependencies: "db" (aiosqlite.Connection) and "agent_id" (str).
        Fetch what you need here — no pre-loading required.
        """
        ...
```

Then register it in `api/tools/registry.py`:

```python
from api.tools.builtin.your_tool import YourTool

register(YourTool())
```

That's it. The tool is automatically available to any agent that lists it in `tools` and is dispatched on LLM tool calls — no changes needed anywhere else.

---

## How it works

### Provider adapters

Tools define their schema once via the Pydantic `input_model`. The registry converts it to the correct wire format per provider:

| Provider      | Format                                                                    |
| ------------- | ------------------------------------------------------------------------- |
| OpenAI / Groq | `{"type": "function", "function": {"name", "description", "parameters"}}` |
| Anthropic     | `{"name", "description", "input_schema"}`                                 |

### Validation

Every tool call passes through `safe_execute` before reaching `execute`. If the LLM returns arguments that don't match `input_model`, a validation error string is returned to the LLM instead of crashing.

### Runtime context

The `context` dict passed to `execute` always contains:

| Key        | Type                   | Description              |
| ---------- | ---------------------- | ------------------------ |
| `db`       | `aiosqlite.Connection` | Live database connection |
| `agent_id` | `str`                  | ID of the running agent  |

Fetch whatever your tool needs inside `execute` — there is no pre-loading step.

### Descriptions matter

Tools don't inject anything into the system prompt. The LLM decides when to call a tool based solely on its `description` and `input_model` field descriptions. Write them to be unambiguous:

- Describe **what** the tool does and **when** to use it
- Add `.description` to every `Field`, including optionals
- Use `Literal` types for enum-like params — they reduce hallucinated values
- Add concrete examples in field descriptions for Anthropic and Groq models

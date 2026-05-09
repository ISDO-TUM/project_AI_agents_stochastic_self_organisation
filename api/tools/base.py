"""Base Tool class — define once, adapt to any provider."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError


class Tool(ABC):
    """A tool that can be called by any LLM provider.

    Subclasses declare a Pydantic *input_model* and implement *execute*.
    The *context* dict carries runtime dependencies (e.g. db connection, agent_id).
    """

    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]

    @abstractmethod
    async def execute(
        self, validated_input: BaseModel, context: dict[str, Any] | None = None
    ) -> str:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()

    # ── provider adapters ──────────────────────────────────────────

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema(),
            },
        }

    def to_anthropic(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema(),
        }

    # ── validation + execution ─────────────────────────────────────

    async def safe_execute(
        self, raw_args: dict[str, Any], context: dict[str, Any] | None = None
    ) -> str:
        try:
            validated = self.input_model(**raw_args)
        except ValidationError as exc:
            return f"Tool input validation error: {exc}"
        return await self.execute(validated, context)

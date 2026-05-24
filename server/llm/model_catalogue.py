"""Canonical LLM model catalogue — single source of truth.

Both ``server.routes.models`` and ``server.schemas`` import from here so that
the model allow-list and the API response are always in sync.  Adding a new
model requires only a change to this file.
"""

from __future__ import annotations

from typing import Literal

ModelProvider = Literal["openai", "anthropic", "groq", "gemini"]
ModelType = Literal["chat", "embedding"]


class _ModelEntry:
    """Lightweight record used before Pydantic models are available."""

    __slots__ = ("id", "name", "provider", "type")

    def __init__(
        self,
        id: str,
        name: str,
        provider: ModelProvider,
        type: ModelType = "chat",
    ) -> None:
        self.id = id
        self.name = name
        self.provider: ModelProvider = provider
        self.type: ModelType = type


# ---------------------------------------------------------------------------
# Standard (public-API) models
# ---------------------------------------------------------------------------

STANDARD_MODELS: list[_ModelEntry] = [
    # OpenAI
    _ModelEntry("gpt-4o-mini", "GPT-4o Mini", "openai"),
    _ModelEntry("gpt-4o", "GPT-4o", "openai"),
    _ModelEntry("gpt-4.1", "GPT-4.1", "openai"),
    _ModelEntry("gpt-4.1-mini", "GPT-4.1 Mini", "openai"),
    _ModelEntry("gpt-4.1-nano", "GPT-4.1 Nano", "openai"),
    _ModelEntry("gpt-5-nano", "GPT-5 Nano", "openai"),
    _ModelEntry("gpt-5-mini", "GPT-5 Mini", "openai"),
    _ModelEntry("gpt-5", "GPT-5", "openai"),
    _ModelEntry("gpt-5.4-nano", "GPT-5.4 Nano", "openai"),
    _ModelEntry("gpt-5.4-mini", "GPT-5.4 Mini", "openai"),
    _ModelEntry("gpt-5.4", "GPT-5.4", "openai"),
    # Anthropic
    _ModelEntry("claude-haiku-4-5-20251001", "Claude Haiku 4.5", "anthropic"),
    _ModelEntry("claude-sonnet-4-6", "Claude Sonnet 4.6", "anthropic"),
    _ModelEntry("claude-opus-4-7", "Claude Opus 4.7", "anthropic"),
    # Groq
    _ModelEntry("llama-3.1-8b-instant", "Llama 3.1 8B Instant", "groq"),
    _ModelEntry("llama-3.3-70b-versatile", "Llama 3.3 70B Versatile", "groq"),
    _ModelEntry("openai/gpt-oss-20b", "GPT OSS 20B", "groq"),
    _ModelEntry("openai/gpt-oss-120b", "GPT OSS 120B", "groq"),
    # Gemini
    _ModelEntry("gemini-2.5-pro", "Gemini 2.5 Pro", "gemini"),
    _ModelEntry("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini"),
    _ModelEntry("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "gemini"),
]

# ---------------------------------------------------------------------------
# SAP / proxy models (returned when a base-URL override is set)
# ---------------------------------------------------------------------------

SAP_MODELS: list[_ModelEntry] = [
    _ModelEntry("anthropic--claude-4-sonnet", "Claude 4 Sonnet", "anthropic"),
    _ModelEntry("anthropic--claude-4.5-haiku", "Claude 4.5 Haiku", "anthropic"),
    _ModelEntry("anthropic--claude-4.5-opus", "Claude 4.5 Opus", "anthropic"),
    _ModelEntry("anthropic--claude-4.5-sonnet", "Claude 4.5 Sonnet", "anthropic"),
    _ModelEntry("anthropic--claude-4.6-opus", "Claude 4.6 Opus", "anthropic"),
    _ModelEntry("anthropic--claude-4.6-sonnet", "Claude 4.6 Sonnet", "anthropic"),
    _ModelEntry("gpt-5", "GPT-5", "openai"),
    _ModelEntry("gpt-5-mini", "GPT-5 Mini", "openai"),
    _ModelEntry("gpt-4.1", "GPT-4.1", "openai"),
    _ModelEntry("gpt-4.1-mini", "GPT-4.1 Mini", "openai"),
    _ModelEntry("gemini-2.5-pro", "Gemini 2.5 Pro", "gemini"),
    _ModelEntry("gemini-2.5-flash", "Gemini 2.5 Flash", "gemini"),
    _ModelEntry("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", "gemini"),
]

# ---------------------------------------------------------------------------
# Derived allow-set — used by schema validators
# ---------------------------------------------------------------------------

#: Every model ID that may appear in an agent's ``model`` field.
ALLOWED_MODEL_IDS: frozenset[str] = frozenset(m.id for m in STANDARD_MODELS + SAP_MODELS)

"""Available LLM models endpoint, mounted at ``/api/models``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.llm.credentials import current_credentials, use_credentials
from server.schemas import Model

router = APIRouter(prefix="/api/models", tags=["Models"])

MODELS = [
    Model(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-4o",
        name="GPT-4o",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5-nano",
        name="GPT-5 Nano",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5-mini",
        name="GPT-5 Mini",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5",
        name="GPT-5",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5.4-nano",
        name="GPT-5.4 Nano",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5.4",
        name="GPT-5.4",
        provider="openai",
        type="chat",
    ),
    Model(
        id="claude-haiku-4-5-20251001",
        name="Claude Haiku 4.5",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="claude-opus-4-7",
        name="Claude Opus 4.7",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="llama-3.1-8b-instant",
        name="Llama 3.1 8B Instant",
        provider="groq",
        type="chat",
    ),
    Model(
        id="llama-3.3-70b-versatile",
        name="Llama 3.3 70B Versatile",
        provider="groq",
        type="chat",
    ),
    Model(
        id="openai/gpt-oss-20b",
        name="GPT OSS 20B",
        provider="groq",
        type="chat",
    ),
    Model(
        id="openai/gpt-oss-120b",
        name="GPT OSS 120B",
        provider="groq",
        type="chat",
    ),
    Model(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider="gemini",
        type="chat",
    ),
    Model(
        id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider="gemini",
        type="chat",
    ),
    Model(
        id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        provider="gemini",
        type="chat",
    ),
]

SAP_SUPPORTED_MODELS = [
    Model(
        id="anthropic--claude-4.6-sonnet",
        name="Claude 4.6 Sonnet",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="anthropic--claude-4.6-opus",
        name="Claude 4.6 Opus",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="anthropic--claude-4.5-haiku",
        name="Claude 4.5 Haiku",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="anthropic--claude-4.5-sonnet",
        name="Claude 4.5 Sonnet",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="anthropic--claude-4.5-opus",
        name="Claude 4.5 Opus",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="anthropic--claude-4-sonnet",
        name="Claude 4 Sonnet",
        provider="anthropic",
        type="chat",
    ),
    Model(
        id="gpt-5",
        name="GPT-5",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-5-mini",
        name="GPT-5 Mini",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-4.1",
        name="GPT-4.1",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gpt-4.1-mini",
        name="GPT-4.1 Mini",
        provider="openai",
        type="chat",
    ),
    Model(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider="gemini",
        type="chat",
    ),
    Model(
        id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider="gemini",
        type="chat",
    ),
    Model(
        id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        provider="gemini",
        type="chat",
    ),
]


@router.get(
    "",
    summary="List available models",
    description=(
        "Returns chat models for the providers the caller has supplied a key for "
        "(via X-LLM-* headers, falling back to env). A provider with a base-URL "
        "override returns SAP model IDs; otherwise standard model IDs."
    ),
    dependencies=[Depends(use_credentials)],
)
async def list_models() -> list[Model]:
    creds = current_credentials()
    result: list[Model] = []
    for provider in ("openai", "anthropic", "groq", "gemini"):
        if not creds.has_key(provider):
            continue
        pool = SAP_SUPPORTED_MODELS if creds.resolve_base_url(provider) else MODELS
        result.extend(m for m in pool if m.provider == provider)
    return result

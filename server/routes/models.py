"""Available LLM models endpoint, mounted at ``/api/models``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.llm.credentials import current_credentials, use_credentials
from server.llm.model_catalogue import OLLAMA_MODELS, PROXY_MODELS, STANDARD_MODELS
from server.llm.ollama_provider import ollama_available
from server.schemas import Model

router = APIRouter(prefix="/api/models", tags=["Models"])

MODELS = [
    Model(id=m.id, name=m.name, provider=m.provider, type=m.type)
    for m in STANDARD_MODELS + OLLAMA_MODELS
]
PROXY_SUPPORTED_MODELS = [
    Model(id=m.id, name=m.name, provider=m.provider, type=m.type) for m in PROXY_MODELS
]


@router.get(
    "",
    summary="List available models",
    description=(
        "Returns chat models for the providers the caller has supplied a key for "
        "(via X-LLM-* headers, falling back to env). A provider with a base-URL "
        "override returns proxy model IDs; otherwise standard model IDs."
    ),
    dependencies=[Depends(use_credentials)],
)
async def list_models() -> list[Model]:
    creds = current_credentials()
    result: list[Model] = []
    for provider in ("openai", "anthropic", "groq", "gemini", "ollama"):
        # Ollama is a local, keyless provider listed only when a loopback Ollama
        # server is actually reachable. This auto-detects dev vs prod with zero
        # config: present locally when `ollama serve` is up, absent on a deployed
        # host where nothing listens on loopback.
        if provider == "ollama":
            base = creds.resolve_base_url("ollama")
            if not base or not await ollama_available(base):
                continue
            pool = MODELS
        else:
            if not creds.has_key(provider):
                continue
            pool = PROXY_SUPPORTED_MODELS if creds.resolve_base_url(provider) else MODELS
        result.extend(m for m in pool if m.provider == provider)
    return result

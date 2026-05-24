"""Available LLM models endpoint, mounted at ``/api/models``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.llm.credentials import current_credentials, use_credentials
from server.llm.model_catalogue import SAP_MODELS, STANDARD_MODELS
from server.schemas import Model

router = APIRouter(prefix="/api/models", tags=["Models"])

MODELS = [Model(id=m.id, name=m.name, provider=m.provider, type=m.type) for m in STANDARD_MODELS]
SAP_SUPPORTED_MODELS = [
    Model(id=m.id, name=m.name, provider=m.provider, type=m.type) for m in SAP_MODELS
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

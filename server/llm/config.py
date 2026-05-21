"""Shared configuration helpers for LLM providers.

Proxy routing
-------------
All providers support an optional ``*_BASE_URL`` environment variable that
redirects SDK calls to a local proxy instead of the provider's public API.
A single ``LLM_PROXY_API_KEY`` can authenticate every proxied provider so
callers don't need per-provider keys. Provider-specific keys take precedence
when both are present, allowing mixed setups (e.g. some providers direct,
others proxied).

Environment variables
---------------------
Per-provider keys (direct or proxy):
  ANTHROPIC_API_KEY, OPENAI_API_KEY, GROQ_API_KEY, GEMINI_API_KEY

Shared proxy key (fallback when no provider-specific key is set):
  LLM_PROXY_API_KEY

Optional base URL overrides (omit to use the provider's default public API):
  ANTHROPIC_BASE_URL  e.g. http://localhost:6655/anthropic   (SDK appends /v1/messages itself)
  OPENAI_BASE_URL     e.g. http://localhost:6655/openai/v1  (SDK appends /chat/completions)
  GROQ_BASE_URL       e.g. http://localhost:6655/openai/v1  (SDK appends /chat/completions)
  GEMINI_BASE_URL     e.g. http://localhost:6655/gemini
"""

from __future__ import annotations

import os

# Maps provider name → (API key env var, base URL env var)
_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    "groq": ("GROQ_API_KEY", "GROQ_BASE_URL"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL"),
}


def get_available_models(
    standard_models: list[dict[str, str]],
    sap_models: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Return models whose provider has credentials configured.

    Routing rules (Option C):
      - key + base URL set  → SAP model IDs (calls routed through proxy)
      - key, no base URL    → standard model IDs (calls go direct to provider)
      - LLM_PROXY_API_KEY counts as a key for all providers
    """
    proxy_key = os.environ.get("LLM_PROXY_API_KEY")
    result: list[dict[str, str]] = []
    for provider, (key_var, url_var) in _PROVIDER_ENV.items():
        has_key = bool(os.environ.get(key_var) or proxy_key)
        if not has_key:
            continue
        if os.environ.get(url_var):
            result.extend(m for m in sap_models if m["provider"] == provider)
        else:
            result.extend(m for m in standard_models if m["provider"] == provider)
    return result


def resolve_api_key(provider_env_var: str) -> str:
    """Return the API key for a provider, falling back to ``LLM_PROXY_API_KEY``.

    Precedence: ``<provider_env_var>`` > ``LLM_PROXY_API_KEY``

    Raises ``KeyError`` with an actionable message if neither variable is set.
    """
    key = os.environ.get(provider_env_var) or os.environ.get("LLM_PROXY_API_KEY")
    if not key:
        raise KeyError(
            f"No API key found. Set {provider_env_var} for a direct provider key, "
            "or LLM_PROXY_API_KEY when routing through a proxy."
        )
    return key

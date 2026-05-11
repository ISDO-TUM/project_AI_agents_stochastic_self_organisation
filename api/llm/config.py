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
  ANTHROPIC_BASE_URL  e.g. http://localhost:6655/anthropic/v1
  OPENAI_BASE_URL     e.g. http://localhost:6655/openai/v1
  GROQ_BASE_URL       e.g. http://localhost:6655/openai/v1
  GEMINI_BASE_URL     e.g. http://localhost:6655/gemini
"""

import os


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

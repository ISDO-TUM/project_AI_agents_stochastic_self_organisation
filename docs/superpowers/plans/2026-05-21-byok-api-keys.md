# BYOK API Keys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users supply their own LLM API keys from the UI; the keys travel per-request as `X-LLM-*` headers, are used to build a provider client for that one request, and are never persisted, logged, or echoed.

**Architecture:** A request-scoped `contextvars.ContextVar` holds a `RequestCredentials` object (keys as `pydantic.SecretStr`). A FastAPI dependency parses `X-LLM-*` headers into it and resets it after the request. Provider clients are built per-request from the current credentials (the existing module-level singleton clients are removed). The browser keeps keys in React state mirrored to `sessionStorage` and attaches them as headers on LLM-triggering calls.

**Tech Stack:** FastAPI, Pydantic (SecretStr), pytest (`asyncio_mode=auto`), Next.js/React (client), httpx (Gemini + tests).

**Verification commands (used throughout):**
- Server tests: `cd server && uv run pytest tests/<file> -v`
- Server lint/format: `cd server && uv run ruff check . && uv run ruff format --check .`
- Server types: `cd server && uv run mypy .`
- Client types: `pnpm --filter app typecheck`
- Client lint: `pnpm --filter app lint`

**Conventions:** Conventional Commits (`feat: …`). Commit after each task. Do NOT commit `.env`. The branch must not be `main` (pre-commit blocks it).

**Security note for the implementer:** `server/index.py` calls `load_dotenv()` at import, so the real `.env` keys land in `os.environ` during tests. Any test asserting "no key" / filtering behavior MUST `monkeypatch.delenv(...)` the relevant vars, and any test that triggers a provider call MUST patch the SDK constructor (otherwise it makes a real API call).

---

## Phase A — Server (BYOK plumbing)

### Task A1: `RequestCredentials`, ContextVar, resolver, and header dependency

**Files:**
- Create: `server/llm/credentials.py`
- Test: `server/tests/test_credentials.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_credentials.py`:

```python
"""Unit tests for request-scoped BYOK credentials."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from server.llm.credentials import (
    MissingCredentialsError,
    RequestCredentials,
    _current,
    current_credentials,
    resolve_api_key,
    resolve_base_url,
    use_credentials,
)


def test_resolve_key_prefers_provider_over_proxy() -> None:
    creds = RequestCredentials(
        keys={"openai": SecretStr("sk-direct")}, proxy_key=SecretStr("proxy")
    )
    assert creds.resolve_key("openai") == "sk-direct"


def test_resolve_key_falls_back_to_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    creds = RequestCredentials(proxy_key=SecretStr("proxy"))
    assert creds.resolve_key("anthropic") == "proxy"


def test_resolve_key_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "env-groq")
    assert RequestCredentials().resolve_key("groq") == "env-groq"


def test_resolve_key_none_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    assert RequestCredentials().resolve_key("openai") is None


def test_secret_str_masked_in_repr() -> None:
    creds = RequestCredentials(keys={"openai": SecretStr("sk-supersecret")})
    assert "sk-supersecret" not in repr(creds)
    assert "**********" in repr(creds)


def test_resolve_base_url_header_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://env")
    creds = RequestCredentials(base_urls={"openai": "http://header"})
    assert creds.resolve_base_url("openai") == "http://header"


def test_resolve_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    token = _current.set(RequestCredentials())
    try:
        with pytest.raises(MissingCredentialsError):
            resolve_api_key("openai")
    finally:
        _current.reset(token)


def test_missing_error_message_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    token = _current.set(RequestCredentials())
    try:
        with pytest.raises(MissingCredentialsError) as exc:
            resolve_api_key("gemini")
    finally:
        _current.reset(token)
    assert "gemini" in str(exc.value)


async def test_use_credentials_sets_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROXY_API_KEY", raising=False)
    gen = use_credentials(
        x_llm_openai_key="sk-ctx",
        x_llm_anthropic_key=None,
        x_llm_groq_key=None,
        x_llm_gemini_key=None,
        x_llm_proxy_key=None,
        x_llm_openai_base_url=None,
        x_llm_anthropic_base_url=None,
        x_llm_groq_base_url=None,
        x_llm_gemini_base_url=None,
    )
    await gen.__anext__()
    assert current_credentials().resolve_key("openai") == "sk-ctx"
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert current_credentials().resolve_key("openai") is None


def test_resolve_base_url_module_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    token = _current.set(RequestCredentials(base_urls={"openai": "http://p"}))
    try:
        assert resolve_base_url("openai") == "http://p"
    finally:
        _current.reset(token)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd server && uv run pytest tests/test_credentials.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'server.llm.credentials'`.

- [ ] **Step 3: Implement `server/llm/credentials.py`**

```python
"""Request-scoped LLM credentials (BYOK).

Credentials arrive as ``X-LLM-*`` request headers, are parsed into a
:class:`RequestCredentials` (keys held as ``SecretStr`` so they never appear in
logs or tracebacks), and published on a :class:`contextvars.ContextVar` for the
duration of one request. Provider clients read the current credentials at
construction time and are discarded when the request ends — nothing is persisted.

When no header is supplied the resolver falls back to environment variables, so
local development with a populated ``.env`` keeps working.

Precedence per provider: header provider key > header proxy key > env provider
key > env ``LLM_PROXY_API_KEY``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextvars import ContextVar
from typing import Annotated

from fastapi import Header
from pydantic import BaseModel, Field, SecretStr

# provider -> (env key var, env base-url var)
_PROVIDER_ENV: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
    "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    "groq": ("GROQ_API_KEY", "GROQ_BASE_URL"),
    "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL"),
}

PROVIDERS: tuple[str, ...] = tuple(_PROVIDER_ENV)


class MissingCredentialsError(Exception):
    """Raised when no API key is available for a provider (header or env)."""


class RequestCredentials(BaseModel):
    """Per-request LLM credentials. Keys are masked in repr via ``SecretStr``."""

    keys: dict[str, SecretStr] = Field(default_factory=dict)
    base_urls: dict[str, str] = Field(default_factory=dict)
    proxy_key: SecretStr | None = None

    def resolve_key(self, provider: str) -> str | None:
        """Header provider key > header proxy key > env provider key > env proxy key."""
        if provider in self.keys:
            return self.keys[provider].get_secret_value()
        if self.proxy_key is not None:
            return self.proxy_key.get_secret_value()
        env_key_var, _ = _PROVIDER_ENV[provider]
        return os.environ.get(env_key_var) or os.environ.get("LLM_PROXY_API_KEY")

    def resolve_base_url(self, provider: str) -> str | None:
        """Header base URL > env base URL > None (provider default)."""
        if provider in self.base_urls:
            return self.base_urls[provider]
        _, env_url_var = _PROVIDER_ENV[provider]
        return os.environ.get(env_url_var) or None

    def has_key(self, provider: str) -> bool:
        return self.resolve_key(provider) is not None


_current: ContextVar[RequestCredentials | None] = ContextVar("llm_credentials", default=None)


def current_credentials() -> RequestCredentials:
    """Credentials for the active request, or an env-only fallback."""
    creds = _current.get()
    return creds if creds is not None else RequestCredentials()


def resolve_api_key(provider: str) -> str:
    key = current_credentials().resolve_key(provider)
    if not key:
        raise MissingCredentialsError(
            f"No API key for provider '{provider}'. Provide it via the matching "
            "X-LLM-* header or set the corresponding environment variable."
        )
    return key


def resolve_base_url(provider: str) -> str | None:
    return current_credentials().resolve_base_url(provider)


def _build(
    *,
    openai_key: str | None,
    anthropic_key: str | None,
    groq_key: str | None,
    gemini_key: str | None,
    proxy_key: str | None,
    openai_base_url: str | None,
    anthropic_base_url: str | None,
    groq_base_url: str | None,
    gemini_base_url: str | None,
) -> RequestCredentials:
    raw_keys = {
        "openai": openai_key,
        "anthropic": anthropic_key,
        "groq": groq_key,
        "gemini": gemini_key,
    }
    raw_urls = {
        "openai": openai_base_url,
        "anthropic": anthropic_base_url,
        "groq": groq_base_url,
        "gemini": gemini_base_url,
    }
    keys = {p: SecretStr(v) for p, v in raw_keys.items() if v}
    base_urls = {p: v for p, v in raw_urls.items() if v}
    return RequestCredentials(
        keys=keys,
        base_urls=base_urls,
        proxy_key=SecretStr(proxy_key) if proxy_key else None,
    )


async def use_credentials(
    x_llm_openai_key: Annotated[str | None, Header()] = None,
    x_llm_anthropic_key: Annotated[str | None, Header()] = None,
    x_llm_groq_key: Annotated[str | None, Header()] = None,
    x_llm_gemini_key: Annotated[str | None, Header()] = None,
    x_llm_proxy_key: Annotated[str | None, Header()] = None,
    x_llm_openai_base_url: Annotated[str | None, Header()] = None,
    x_llm_anthropic_base_url: Annotated[str | None, Header()] = None,
    x_llm_groq_base_url: Annotated[str | None, Header()] = None,
    x_llm_gemini_base_url: Annotated[str | None, Header()] = None,
) -> AsyncIterator[None]:
    """FastAPI dependency: publish per-request credentials on the ContextVar."""
    creds = _build(
        openai_key=x_llm_openai_key,
        anthropic_key=x_llm_anthropic_key,
        groq_key=x_llm_groq_key,
        gemini_key=x_llm_gemini_key,
        proxy_key=x_llm_proxy_key,
        openai_base_url=x_llm_openai_base_url,
        anthropic_base_url=x_llm_anthropic_base_url,
        groq_base_url=x_llm_groq_base_url,
        gemini_base_url=x_llm_gemini_base_url,
    )
    token = _current.set(creds)
    try:
        yield
    finally:
        _current.reset(token)
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd server && uv run pytest tests/test_credentials.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Lint/type then commit**

```bash
cd server && uv run ruff check . && uv run ruff format . && uv run mypy .
cd .. && git add server/llm/credentials.py server/tests/test_credentials.py
git commit -m "feat: add request-scoped BYOK credentials"
```

---

### Task A2: Refactor providers to per-request clients; delete `config.py`

**Files:**
- Modify: `server/llm/openai_provider.py`, `server/llm/groq_provider.py`, `server/llm/anthropic_provider.py`, `server/llm/gemini_provider.py`
- Delete: `server/llm/config.py` (its `resolve_api_key` moved to `credentials.py`; `get_available_models` is unused)
- Test: existing `server/tests/test_credentials.py` + the suite must stay green.

- [ ] **Step 1: Edit `server/llm/openai_provider.py`**

Replace the import and client builder. Change line 7 `from .config import resolve_api_key` and the `_client`/`_get_openai_client` block (lines 10–35) to:

```python
from .credentials import resolve_api_key, resolve_base_url
```

```python
def _get_openai_client() -> AsyncOpenAI:
    """Build a per-request AsyncOpenAI client from the current credentials."""
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("openai")}
    base_url = resolve_base_url("openai")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)
```

Remove the now-unused `import os` (line 1) and the module-level `_client: AsyncOpenAI | None = None`.

- [ ] **Step 2: Edit `server/llm/groq_provider.py`**

Change line 6 to `from .credentials import resolve_api_key, resolve_base_url`, remove `import os` (line 1) and the `_client` global, and replace `_get_groq_client` (lines 13–28) with:

```python
def _get_groq_client() -> AsyncGroq:
    """Build a per-request AsyncGroq client from the current credentials."""
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("groq")}
    base_url = resolve_base_url("groq")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncGroq(**kwargs)
```

- [ ] **Step 3: Edit `server/llm/anthropic_provider.py`**

Change line 7 to `from .credentials import resolve_api_key, resolve_base_url`, remove `import os` (line 1) and the `_client` global, and replace `_get_anthropic_client` (lines 17–32) with:

```python
def _get_anthropic_client() -> AsyncAnthropic:
    """Build a per-request AsyncAnthropic client from the current credentials."""
    kwargs: dict[str, Any] = {"api_key": resolve_api_key("anthropic")}
    base_url = resolve_base_url("anthropic")
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncAnthropic(**kwargs)
```

- [ ] **Step 4: Edit `server/llm/gemini_provider.py`**

Change line 25 to `from .credentials import resolve_api_key, resolve_base_url`, remove `import os` (line 19), and replace the helpers (lines 31–37) and the `using_proxy` line (line 73):

```python
def _get_base_url() -> str:
    return resolve_base_url("gemini") or "https://generativelanguage.googleapis.com"


def _get_api_key() -> str:
    return resolve_api_key("gemini")
```

Inside `_send`, replace `using_proxy = bool(os.environ.get("GEMINI_BASE_URL"))` with:

```python
        using_proxy = bool(resolve_base_url("gemini"))
```

- [ ] **Step 5: Delete `server/llm/config.py`**

```bash
git rm server/llm/config.py
```

- [ ] **Step 6: Run the full suite + lint + types**

Run: `cd server && uv run pytest -v`
Expected: PASS. (The existing `test_llm_endpoints.py` mocks `call_*`, so per-request client construction is not exercised there; `test_credentials.py` passes.)
Run: `cd server && uv run ruff check . && uv run mypy .`
Expected: clean (no references to deleted `config` remain).

- [ ] **Step 7: Commit**

```bash
cd .. && git add -A server/llm
git commit -m "feat: build provider clients per request from BYOK credentials"
```

---

### Task A3: Wire the credentials dependency into LLM routes + filter `/api/models`

**Files:**
- Modify: `server/routes/models.py`, `server/routes/agents.py`, `server/routes/simulation.py`, `server/routes/test.py`, `server/index.py`
- Test: `server/tests/test_byok.py` (new, added in Task A4 — this task is verified by the existing suite staying green)

- [ ] **Step 1: Rewrite `server/routes/models.py` to filter by credentials**

Replace the imports/router/decorator/handler (top of file + lines 204–218) so the file reads (keep `MODELS` and `SAP_SUPPORTED_MODELS` lists unchanged):

```python
"""Available LLM models endpoint, mounted at ``/api/models``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from server.llm.credentials import current_credentials, use_credentials
from server.schemas import Model

router = APIRouter(prefix="/api/models", tags=["Models"])

MODELS = [
    # ... unchanged ...
]

SAP_SUPPORTED_MODELS = [
    # ... unchanged ...
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
```

Remove the old `Query` import and the `is_sap_supported` parameter entirely.

- [ ] **Step 2: Add the dependency + clean 400 to `server/routes/agents.py`**

Add to imports (near line 20):

```python
from server.llm.credentials import MissingCredentialsError, use_credentials
```

Add `dependencies=[Depends(use_credentials)]` to the `@router.post("/{agent_id}/run", ...)` decorator (line 267). Then in `run_agent`, change the `try/except` (lines 289–303) to handle missing credentials before the broad handler:

```python
    try:
        response, tools_used = await call_agent(
            body.prompt,
            provider=agent["provider"],
            model=agent["model"],
            system_prompt=system_prompt,
            tool_names=tool_names or None,
            tool_context={"db": db, "agent_id": agent_id},
        )
    except MissingCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Agent run failed for agent_id=%s", agent_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider error. Check server logs for details.",
        ) from exc
```

- [ ] **Step 3: Add the dependency to `server/routes/simulation.py`**

Add to imports:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from server.llm.credentials import use_credentials
```

Add `dependencies=[Depends(use_credentials)]` to the `@router.post("/run", ...)` decorator (line 19). (Per-agent failures, including missing keys, are already captured as agent error text by the engine — no key value is exposed.)

- [ ] **Step 4: Add the dependency to the provider-test routes in `server/routes/test.py`**

Add to imports:

```python
from fastapi import APIRouter, Depends, HTTPException, status
from server.llm.credentials import use_credentials
```

Add `dependencies=[Depends(use_credentials)]` to each of the three decorators: `@router.post("/openai", ...)`, `@router.post("/anthropic", ...)`, `@router.post("/groq", ...)`. Leave `/tools` and `/tools/files` unchanged.

- [ ] **Step 5: Register a global 400 handler in `server/index.py`**

Add imports near the top:

```python
from fastapi.responses import JSONResponse
from fastapi import Request
from server.llm.credentials import MissingCredentialsError
```

After the `app = FastAPI(...)` block (after line 44) add:

```python
@app.exception_handler(MissingCredentialsError)
async def _missing_credentials_handler(
    request: Request, exc: MissingCredentialsError
) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
```

- [ ] **Step 6: Run the suite + lint + types**

Run: `cd server && uv run pytest -v`
Expected: PASS. The existing `test_llm_endpoints.py` still passes (mocked calls; the added dependency just sets/clears the ContextVar with no headers).
Run: `cd server && uv run ruff check . && uv run mypy .`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
cd .. && git add server/routes server/index.py
git commit -m "feat: thread BYOK credentials into LLM routes and filter models"
```

---

### Task A4: Integration & no-leak tests

**Files:**
- Create: `server/tests/test_byok.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_byok.py`:

```python
"""Integration tests for BYOK header plumbing and no-leak guarantees."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

_ALL_KEY_ENV = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "LLM_PROXY_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "GROQ_BASE_URL",
    "GEMINI_BASE_URL",
)

_OPENAI_AGENT = {
    "name": "Tester",
    "description": "",
    "system_prompt": "",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "tools": [],
    "connections": [],
}


def _fake_openai_response(text: str) -> MagicMock:
    message = MagicMock()
    message.content = text
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _capturing_openai_ctor(captured: dict[str, object], text: str = "ok"):
    def _ctor(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        inst = MagicMock()
        inst.chat.completions.create = AsyncMock(return_value=_fake_openai_response(text))
        return inst

    return _ctor


async def _create_openai_agent(client: AsyncClient) -> str:
    resp = await client.post("/api/agents/", json=_OPENAI_AGENT)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_agent_run_uses_header_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent_id = await _create_openai_agent(client)
    captured: dict[str, object] = {}
    with patch(
        "server.llm.openai_provider.AsyncOpenAI",
        side_effect=_capturing_openai_ctor(captured, "hi"),
    ):
        resp = await client.post(
            f"/api/agents/{agent_id}/run",
            json={"prompt": "hello"},
            headers={"X-LLM-OpenAI-Key": "sk-header-123"},
        )
    assert resp.status_code == 200, resp.text
    assert captured["api_key"] == "sk-header-123"


async def test_agent_run_missing_key_returns_400(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    agent_id = await _create_openai_agent(client)
    resp = await client.post(f"/api/agents/{agent_id}/run", json={"prompt": "x"})
    assert resp.status_code == 400


async def test_key_not_leaked_on_provider_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent_id = await _create_openai_agent(client)

    def _boom(**kwargs: object) -> MagicMock:
        inst = MagicMock()
        inst.chat.completions.create = AsyncMock(side_effect=RuntimeError("upstream boom"))
        return inst

    secret = "sk-leak-SECRET-DO-NOT-LOG"
    with patch("server.llm.openai_provider.AsyncOpenAI", side_effect=_boom):
        with caplog.at_level(logging.DEBUG):
            resp = await client.post(
                f"/api/agents/{agent_id}/run",
                json={"prompt": "x"},
                headers={"X-LLM-OpenAI-Key": secret},
            )
    assert resp.status_code == 502
    assert secret not in resp.text
    assert secret not in caplog.text


async def test_models_filtered_by_header_key(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get("/api/models", headers={"X-LLM-Anthropic-Key": "sk-a"})
    assert resp.status_code == 200
    providers = {m["provider"] for m in resp.json()}
    assert providers == {"anthropic"}


async def test_models_returns_sap_ids_with_base_url(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get(
        "/api/models",
        headers={"X-LLM-Anthropic-Key": "sk-a", "X-LLM-Anthropic-Base-Url": "http://proxy"},
    )
    assert resp.status_code == 200
    ids = {m["id"] for m in resp.json()}
    assert any(i.startswith("anthropic--") for i in ids)


async def test_models_empty_without_keys(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in _ALL_KEY_ENV:
        monkeypatch.delenv(var, raising=False)
    resp = await client.get("/api/models")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_simulation_propagates_key_through_gather(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    await _create_openai_agent(client)
    captured: dict[str, object] = {}
    with patch(
        "server.llm.openai_provider.AsyncOpenAI",
        side_effect=_capturing_openai_ctor(captured, "REASON: r\nVOTE: x"),
    ):
        resp = await client.post(
            "/api/simulation/run",
            json={"prompt": "hi", "rounds": 1, "mode": "voting"},
            headers={"X-LLM-OpenAI-Key": "sk-sim-key"},
        )
    assert resp.status_code == 200, resp.text
    assert captured.get("api_key") == "sk-sim-key"
```

- [ ] **Step 2: Run to verify (and confirm none make real network calls)**

Run: `cd server && uv run pytest tests/test_byok.py -v`
Expected: PASS. If any test hangs/network-errors, a provider call escaped the mock — fix the patch target before continuing.

- [ ] **Step 3: Commit**

```bash
cd .. && git add server/tests/test_byok.py
git commit -m "test: cover BYOK header plumbing and key non-leakage"
```

---

## Phase B — Client (key entry UI + header attachment)

> No JS test runner is configured in this repo. Client tasks are verified with
> `pnpm --filter app typecheck`, `pnpm --filter app lint`, and a manual browser check.

### Task B1: API-keys context + header injection into the API client

**Files:**
- Create: `client/lib/api-keys-context.tsx`
- Modify: `client/lib/api.ts`

- [ ] **Step 1: Add a header holder + injection to `client/lib/api.ts`**

At the top of the file (after the imports, before `request`), add:

```typescript
// ─── BYOK credential headers ──────────────────────────────────────────────────
// Set by ApiKeysProvider; merged into every request. Kept in memory only.
let llmHeaders: Record<string, string> = {};

export function setLlmHeaders(headers: Record<string, string>): void {
  llmHeaders = headers;
}
```

Then in `request()` (lines 73–89) merge the headers:

```typescript
async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { ...llmHeaders };
  if (body) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${method} ${path} → ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}
```

- [ ] **Step 2: Create `client/lib/api-keys-context.tsx`**

```tsx
"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { setLlmHeaders } from "@/lib/api";

export interface ApiKeys {
  openaiKey: string;
  anthropicKey: string;
  groqKey: string;
  geminiKey: string;
  proxyKey: string;
  openaiBaseUrl: string;
  anthropicBaseUrl: string;
  groqBaseUrl: string;
  geminiBaseUrl: string;
}

export const EMPTY_KEYS: ApiKeys = {
  openaiKey: "",
  anthropicKey: "",
  groqKey: "",
  geminiKey: "",
  proxyKey: "",
  openaiBaseUrl: "",
  anthropicBaseUrl: "",
  groqBaseUrl: "",
  geminiBaseUrl: "",
};

const STORAGE_KEY = "llm-api-keys";

// Map ApiKeys -> X-LLM-* headers, omitting empty values.
export function apiKeyHeaders(keys: ApiKeys): Record<string, string> {
  const pairs: [string, string][] = [
    ["X-LLM-OpenAI-Key", keys.openaiKey],
    ["X-LLM-Anthropic-Key", keys.anthropicKey],
    ["X-LLM-Groq-Key", keys.groqKey],
    ["X-LLM-Gemini-Key", keys.geminiKey],
    ["X-LLM-Proxy-Key", keys.proxyKey],
    ["X-LLM-OpenAI-Base-Url", keys.openaiBaseUrl],
    ["X-LLM-Anthropic-Base-Url", keys.anthropicBaseUrl],
    ["X-LLM-Groq-Base-Url", keys.groqBaseUrl],
    ["X-LLM-Gemini-Base-Url", keys.geminiBaseUrl],
  ];
  return Object.fromEntries(
    pairs.filter(([, v]) => v.trim().length > 0).map(([k, v]) => [k, v.trim()]),
  );
}

export function hasAnyProviderKey(keys: ApiKeys): boolean {
  return [
    keys.openaiKey,
    keys.anthropicKey,
    keys.groqKey,
    keys.geminiKey,
    keys.proxyKey,
  ].some((v) => v.trim().length > 0);
}

interface ApiKeysContextValue {
  keys: ApiKeys;
  setKeys: (keys: ApiKeys) => void;
  clearKeys: () => void;
  hasAnyKey: boolean;
}

const ApiKeysContext = createContext<ApiKeysContextValue>({
  keys: EMPTY_KEYS,
  setKeys: () => {},
  clearKeys: () => {},
  hasAnyKey: false,
});

export function ApiKeysProvider({ children }: { children: React.ReactNode }) {
  const [keys, setKeysState] = useState<ApiKeys>(() => {
    if (typeof window === "undefined") return EMPTY_KEYS;
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return EMPTY_KEYS;
    try {
      return { ...EMPTY_KEYS, ...(JSON.parse(raw) as Partial<ApiKeys>) };
    } catch {
      return EMPTY_KEYS;
    }
  });

  useEffect(() => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(keys));
    setLlmHeaders(apiKeyHeaders(keys));
  }, [keys]);

  const setKeys = useCallback((next: ApiKeys) => setKeysState(next), []);
  const clearKeys = useCallback(() => {
    setKeysState(EMPTY_KEYS);
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <ApiKeysContext.Provider
      value={{ keys, setKeys, clearKeys, hasAnyKey: hasAnyProviderKey(keys) }}
    >
      {children}
    </ApiKeysContext.Provider>
  );
}

export const useApiKeys = () => useContext(ApiKeysContext);
```

- [ ] **Step 3: Verify types/lint**

Run: `pnpm --filter app typecheck`
Expected: PASS.
Run: `pnpm --filter app lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add client/lib/api-keys-context.tsx client/lib/api.ts
git commit -m "feat: add session-scoped api-keys context and header injection"
```

---

### Task B2: API Keys modal component

**Files:**
- Create: `client/components/panels/api-keys-modal.tsx`

- [ ] **Step 1: Create `client/components/panels/api-keys-modal.tsx`**

```tsx
"use client";

import { useState } from "react";
import { LIcon } from "@/lib/icons";
import { BURG, getTheme } from "@/lib/theme";
import { useTheme } from "@/lib/theme-context";
import {
  useApiKeys,
  EMPTY_KEYS,
  type ApiKeys,
} from "@/lib/api-keys-context";

interface FieldDef {
  key: keyof ApiKeys;
  label: string;
  secret: boolean;
}

const FIELDS: FieldDef[] = [
  { key: "openaiKey", label: "OPENAI_API_KEY", secret: true },
  { key: "anthropicKey", label: "ANTHROPIC_API_KEY", secret: true },
  { key: "groqKey", label: "GROQ_API_KEY", secret: true },
  { key: "geminiKey", label: "GEMINI_API_KEY", secret: true },
  { key: "proxyKey", label: "LLM_PROXY_API_KEY", secret: true },
  { key: "openaiBaseUrl", label: "OPENAI_BASE_URL", secret: false },
  { key: "anthropicBaseUrl", label: "ANTHROPIC_BASE_URL", secret: false },
  { key: "groqBaseUrl", label: "GROQ_BASE_URL", secret: false },
  { key: "geminiBaseUrl", label: "GEMINI_BASE_URL", secret: false },
];

export function ApiKeysModal({ onClose }: { onClose: () => void }) {
  const { keys, setKeys, clearKeys } = useApiKeys();
  const [draft, setDraft] = useState<ApiKeys>(keys);
  const { dark } = useTheme();
  const t = getTheme(dark);

  const update = (key: keyof ApiKeys, value: string) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const save = () => {
    setKeys(draft);
    onClose();
  };

  const clearAll = () => {
    setDraft(EMPTY_KEYS);
    clearKeys();
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(0,0,0,0.45)",
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "min(560px, 92vw)",
          maxHeight: "85vh",
          overflowY: "auto",
          background: dark ? "rgba(14,12,22,0.98)" : "rgba(255,254,255,0.99)",
          border: `1px solid ${t.borderHi}`,
          borderRadius: 14,
          padding: 22,
          boxShadow: dark
            ? "0 12px 48px rgba(0,0,0,0.6)"
            : "0 12px 40px rgba(0,0,0,0.18)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 6,
          }}
        >
          <h2 style={{ fontSize: 16, fontWeight: 700, color: t.text, margin: 0 }}>
            API Keys
          </h2>
          <button
            onClick={onClose}
            title="Close"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: t.textSub,
              display: "flex",
            }}
          >
            <LIcon name="X" size={16} color="currentColor" />
          </button>
        </div>

        <p style={{ fontSize: 11.5, color: t.textSub, marginTop: 0, lineHeight: 1.5 }}>
          Keys are kept only in this browser tab (sessionStorage) and sent with each
          request. They are never stored on the server. Closing the tab clears them.
        </p>

        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 14 }}>
          {FIELDS.map((f) => (
            <label key={f.key} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <span
                style={{
                  fontSize: 10.5,
                  fontWeight: 600,
                  letterSpacing: 0.3,
                  color: t.textSub,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {f.label}
              </span>
              <input
                type={f.secret ? "password" : "text"}
                value={draft[f.key]}
                onChange={(e) => update(f.key, e.target.value)}
                autoComplete="off"
                spellCheck={false}
                placeholder={f.secret ? "sk-…" : "https://…"}
                style={{
                  background: t.inputBg,
                  border: `1px solid ${t.border}`,
                  borderRadius: 8,
                  color: t.text,
                  fontSize: 12.5,
                  padding: "8px 11px",
                  outline: "none",
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              />
            </label>
          ))}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 18,
          }}
        >
          <button
            onClick={clearAll}
            style={{
              background: "none",
              border: `1px solid ${t.border}`,
              borderRadius: 8,
              color: t.textSub,
              fontSize: 12,
              fontWeight: 600,
              padding: "8px 14px",
              cursor: "pointer",
            }}
          >
            Clear all keys
          </button>
          <button
            onClick={save}
            style={{
              background: BURG,
              border: "none",
              borderRadius: 8,
              color: "#fff",
              fontSize: 12.5,
              fontWeight: 700,
              padding: "8px 20px",
              cursor: "pointer",
            }}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
```

> Note: if `t.inputBg`, `t.border`, `t.borderHi`, `t.textSub` are not all present on the theme object, check `client/lib/theme.ts` and substitute the closest existing token. Verify with typecheck in Step 2.

- [ ] **Step 2: Verify types/lint**

Run: `pnpm --filter app typecheck && pnpm --filter app lint`
Expected: PASS. (If a theme token name is wrong, fix it against `client/lib/theme.ts`.)

- [ ] **Step 3: Commit**

```bash
git add client/components/panels/api-keys-modal.tsx
git commit -m "feat: add API keys entry modal"
```

---

### Task B3: Mount provider + wire toolbar button to open the modal

**Files:**
- Modify: `client/app/page.tsx`, `client/components/toolbar.tsx`, `client/components/app.tsx`

- [ ] **Step 1: Wrap the app in `ApiKeysProvider` (`client/app/page.tsx`)**

```tsx
import { ThemeProvider } from "@/lib/theme-context";
import { ApiKeysProvider } from "@/lib/api-keys-context";
import { App } from "@/components/app";

export default function Home() {
  return (
    <ThemeProvider>
      <ApiKeysProvider>
        <App />
      </ApiKeysProvider>
    </ThemeProvider>
  );
}
```

- [ ] **Step 2: Add an `onOpenKeys` prop + button to `client/components/toolbar.tsx`**

Add `onOpenKeys: () => void;` to `ToolbarProps` (after `onToggleTweaks`). Then add a button in the non-sim toolbar group, immediately before the `Settings` button (before line 301):

```tsx
            <TBtn
              onClick={onOpenKeys}
              icon="KeyRound"
              title="API Keys"
              t={t}
            >
              Keys
            </TBtn>
```

Add `onOpenKeys,` to the destructured props in the `Toolbar({ ... })` signature.

> Note: confirm `"KeyRound"` exists in `client/lib/icons`. If not, use an available icon name (e.g. `"Settings2"` or `"Lock"`). Verify with typecheck.

- [ ] **Step 3: Render the modal + pass the handler in `client/components/app.tsx`**

Add the imports:

```tsx
import { useState } from "react"; // if not already imported — otherwise add `useState` to the existing import
import { ApiKeysModal } from "@/components/panels/api-keys-modal";
```

Add modal open state alongside the other component state (near the top of the `App` component body):

```tsx
  const [showKeys, setShowKeys] = useState(false);
```

Pass the handler to the `<Toolbar .../>` (around line 429):

```tsx
        <Toolbar
          /* ...existing props... */
          onOpenKeys={() => setShowKeys(true)}
        />
```

Render the modal near the other top-level overlays in the returned JSX (e.g. right after `<PromptBar .../>`, line 443):

```tsx
        {showKeys && <ApiKeysModal onClose={() => setShowKeys(false)} />}
```

- [ ] **Step 4: Verify types/lint**

Run: `pnpm --filter app typecheck && pnpm --filter app lint`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add client/app/page.tsx client/components/toolbar.tsx client/components/app.tsx
git commit -m "feat: open API keys modal from the toolbar"
```

---

### Task B4: Gate runs on having a key + refresh models when keys change

**Files:**
- Modify: `client/components/prompt-bar.tsx`, `client/components/panels/agent-panel.tsx`

- [ ] **Step 1: Disable Run + hint when no key (`client/components/prompt-bar.tsx`)**

Add the import:

```tsx
import { useApiKeys } from "@/lib/api-keys-context";
```

Inside `PromptBar`, read the flag and fold it into `canRun` (replace line 34):

```tsx
  const { hasAnyKey } = useApiKeys();
  const canRun = !simMode && hasAnyKey && val.trim().length > 0;
```

Replace the disclaimer text node (lines 257–258) so it nudges the user when no key is set:

```tsx
          {hasAnyKey
            ? "This is an AI simulation and may make mistakes. Verify outputs independently."
            : "Add an API key (Keys button, top bar) to start running simulations."}
```

- [ ] **Step 2: Refetch models when keys change (`client/components/panels/agent-panel.tsx`)**

Add the import:

```tsx
import { useApiKeys } from "@/lib/api-keys-context";
```

Inside the component, read the keys, and add `keys` to the `fetchModels` effect deps so the model list updates after the user enters a key. Change the effect at line 57:

```tsx
  const { keys } = useApiKeys();

  useEffect(() => {
    fetchModels().then(setAvailableModels).catch(console.error);
  }, [keys]);
```

> Note: keep whatever `setAvailableModels` state setter already exists; only the dependency array changes (it was previously `[]`). If the effect already lists deps, add `keys`.

- [ ] **Step 3: Verify types/lint**

Run: `pnpm --filter app typecheck && pnpm --filter app lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add client/components/prompt-bar.tsx client/components/panels/agent-panel.tsx
git commit -m "feat: gate runs and model list on supplied api keys"
```

---

### Task B5: Manual end-to-end verification

**Files:** none (manual).

- [ ] **Step 1: Start the stack**

Run: `pnpm dev` (UI on :3000, API on :8000). Ensure the server env has NO provider keys to truly exercise BYOK (temporarily rename `.env`), OR keep `.env` to confirm fallback — test both if possible.

- [ ] **Step 2: Golden path**

  1. Open http://localhost:3000. Confirm the Run button is disabled and the prompt bar shows the "Add an API key…" hint.
  2. Click **Keys**, paste a real key into one provider (e.g. OpenAI), Save.
  3. Add an agent; confirm the model dropdown now lists that provider's models only.
  4. Enter a prompt and Run; confirm a real response comes back.

- [ ] **Step 3: Security checks (DevTools)**

  1. Network tab → the `/api/...` requests carry `X-LLM-*` headers; the key is NOT in any URL or response body.
  2. Application tab → `sessionStorage` has `llm-api-keys`; `localStorage` does NOT.
  3. Reload the tab: keys persist. Close the tab and reopen: keys are gone.
  4. Server console: trigger a provider error (use a bogus key) and confirm the logs/response never show the key value.

- [ ] **Step 4: Final full verification + summary**

Run: `cd server && uv run pytest -v && uv run ruff check . && uv run mypy .`
Run: `pnpm --filter app typecheck && pnpm --filter app lint`
Expected: all PASS. Report results.

---

## Self-Review Notes (author)

- **Spec coverage:** §3 data flow → A1–A3, B1; §4 server design → A1–A3; §5 client → B1–B4; §6 defense-in-depth → SecretStr (A1), sessionStorage/password (B1–B2), ContextVar reset (A1), sanitized errors (A3), no-leak tests (A4); §7 error handling → A3 (400/502); §8 testing → A1/A4 + B5 manual.
- **Type consistency:** `resolve_api_key`/`resolve_base_url` take a provider name (`"openai"`) everywhere; providers updated in A2. `apiKeyHeaders`/`hasAnyProviderKey`/`setLlmHeaders` names are consistent across B1–B4.
- **Known check-points flagged inline:** theme token names (B2), icon name `KeyRound` (B3), and existing import/state in `app.tsx`/`agent-panel.tsx` (B3/B4) must be confirmed against the real files during execution — typecheck catches mismatches.

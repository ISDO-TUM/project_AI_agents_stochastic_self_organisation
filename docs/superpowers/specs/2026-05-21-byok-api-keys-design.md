# BYOK API Keys — Design Spec

- **Date:** 2026-05-21
- **Status:** Approved (pending written-spec review)
- **Topic:** Let users supply their own LLM API keys from the UI, with maximum protection against saving, logging, or displaying the keys anywhere.

## 1. Context & Goal

The server makes all LLM calls. Today every provider reads its key from a process
environment variable (`OPENAI_API_KEY`, …) via `resolve_api_key()` in
[`server/llm/config.py`](../../../server/llm/config.py), and each provider caches a
**module-level singleton client** built from those env vars on first use (e.g.
`_client` in [`server/llm/openai_provider.py`](../../../server/llm/openai_provider.py)).

We want visitors to a **public/shared deployment** to bring their own keys (BYOK) so
they can use the models, without the server ever holding, persisting, logging, or
echoing any key.

## 2. Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Deployment model | Public/shared demo. Each visitor brings their own key. Server is stateless w.r.t. keys. |
| Credentials captured | Full `.env.example` set: 4 provider keys (`OPENAI`, `ANTHROPIC`, `GROQ`, `GEMINI`) + `LLM_PROXY_API_KEY` + 4 `*_BASE_URL` overrides. |
| Browser persistence | **Session only** — in-memory React state + `sessionStorage`. Survives reload within the tab; wiped on tab/browser close. Never `localStorage`. |
| Transport | Per-request HTTP headers under an `X-LLM-*` prefix (not request body). |
| Server injection | Request-scoped `contextvars.ContextVar`, set by a FastAPI dependency, read only at provider-client construction. |
| Model picker | Filtered to providers the caller has supplied a key for. |

## 3. Architecture & Data Flow

```
Browser
  ApiKeysProvider (React context)
    state in memory + mirrored to sessionStorage
  ──> on each LLM-triggering request, attach X-LLM-* headers (HTTPS)
        e.g. X-LLM-OpenAI-Key, X-LLM-OpenAI-Base-Url, X-LLM-Proxy-Key, …
Next.js rewrite (/api/:path*  ->  INTERNAL_API_URL)
  ──> forwards X-LLM-* headers; no request/header logging
FastAPI
  Depends(credentials_from_headers)  -> builds RequestCredentials (SecretStr fields)
                                      -> token = _CREDS_CTX.set(creds)  (try/finally reset)
  route -> run_topology / call_agent (UNCHANGED signatures)
        -> provider._get_client() reads _CREDS_CTX.get(), builds a client for THIS request
        -> client discarded when request ends; nothing persisted/logged
```

The credential object exists only for the duration of one request. Recommended
deployment posture: **run the server with no provider keys in its environment** so
there is no server-side secret to leak; every call is BYOK. Env vars remain a
fallback for local development only.

## 4. Server Design

### 4.1 `RequestCredentials` (new)
A small dataclass/Pydantic model with all key fields typed as
`pydantic.SecretStr` and base-URL fields as plain `str | None`. `SecretStr` masks
the value in `repr()`/`str()`/tracebacks (`SecretStr('**********')`); the raw value
is reachable only via an explicit `.get_secret_value()`, which is called **only** at
the SDK-client construction site.

### 4.2 Header dependency (new)
A FastAPI dependency reads the `X-LLM-*` headers, constructs a `RequestCredentials`,
and publishes it on a module-level `ContextVar` (`_CREDS_CTX`). Implemented as a
`yield` dependency so the `ContextVar` token is **reset in a `finally`** after the
request, preventing any cross-request bleed. Missing headers fall back to env vars
(local dev). The dependency is attached to the LLM-triggering routes:
`/api/agents/{id}/run`, `/api/simulation/run`, `/api/models`.

### 4.3 `config.py` refactor
`resolve_api_key()` and `get_available_models()` take credentials from the
`ContextVar` (or an explicit `RequestCredentials` arg) instead of reading
`os.environ` directly. Same precedence rules as today: provider key > `LLM_PROXY_API_KEY`;
base URL present ⇒ proxy/SAP model IDs, absent ⇒ direct model IDs.

### 4.4 Provider refactor (the core change)
Remove the module-level singleton clients (`_client = None` + `_get_*_client()` global
cache) in all four providers. `_get_client()` builds a fresh SDK client per call from
the current `RequestCredentials` (key + optional base URL). This is required for BYOK
regardless of transport — a shared singleton cannot serve different users' keys.

### 4.5 Models endpoint
Wire `/api/models` ([`server/routes/models.py`](../../../server/routes/models.py)) to
`get_available_models()` so it returns only the models whose provider the caller has a
key for, using the existing `MODELS` / `SAP_SUPPORTED_MODELS` lists and routing rules.

### 4.6 Untouched
`run_topology` and its three mode functions, `_call_agent`, `call_agent`, and
`run_agent` keep their current signatures — they never see the secret. The existing
sanitized error handling at [`agents.py`](../../../server/routes/agents.py) (logs a
generic message, returns a 502 without the key) is kept; with `SecretStr` even logged
tracebacks stay masked.

## 5. Client Design

- **`ApiKeysProvider` / `useApiKeys`** — React context holding the 9 fields; mirrored
  to `sessionStorage` on change, hydrated from it on load. A `clearKeys()` action.
- **API Keys modal** — opened from a new toolbar button in
  [`toolbar.tsx`](../../../client/components/toolbar.tsx). Fields use
  `type="password"`, `autoComplete="off"`, `spellCheck={false}`. After a value is
  saved it is shown only masked (e.g. `••••••••1234`); the full value is never
  re-rendered. Includes a "Clear all keys" button.
- **Header attachment** — `request()` in [`lib/api.ts`](../../../client/lib/api.ts)
  reads the context and adds `X-LLM-*` headers on the LLM-triggering calls
  (`runAgent`, `runSimulation`, `fetchModels`).
- **Gating** — run actions are disabled (with a prompt to add a key) when no key is
  present; the model picker lists only models returned by the now-filtered
  `/api/models`.

## 6. Defense-in-Depth (every leak vector → control)

| Layer | Risk | Control |
|---|---|---|
| UI input | Visible / shoulder-surf | `password` input, `autoComplete=off`, masked display, never re-render full value |
| Browser storage | localStorage persists / XSS | `sessionStorage` only; no localStorage; strict CSP; no third-party/analytics scripts |
| Client logging | `console.log` of keys | Keys never passed to logging or error reporting |
| Transport | Interception | HTTPS only; keys in headers, never query string |
| Next.js proxy hop | Proxy logs headers | Confirm rewrite forwards `X-LLM-*`; no header/body logging middleware on Next |
| App logs / tracebacks | Key printed in a log | `SecretStr` masks repr; raw value read only at SDK call site |
| Access logs | Uvicorn logs headers | Default uvicorn logs neither headers nor bodies; add no middleware that does |
| Errors to client | Traceback echoes key | Debug off in prod; sanitized 502; `SecretStr` masking |
| Persistence | Key written to SQLite | Credentials never enter any persisted schema/model |
| Provider SDKs | SDK debug logging | SDK debug not enabled; key passed only as `api_key` arg |
| Cross-request | ContextVar bleed | `yield` dependency resets the ContextVar token in `finally` |

## 7. Error Handling

- No credentials supplied (and none in env) ⇒ a clean `400`/`422` "no API key for
  provider X" message, never a 500 with a traceback.
- Provider/auth failure ⇒ existing sanitized 502 ("LLM provider error"), key never
  included in the response.

## 8. Testing Strategy (prove absence of leaks)

- **No-leak tests:** force a provider error and assert the key string appears in
  neither the HTTP response nor captured logs (only `**********`).
- **Persistence test:** after a run, assert no DB row/table contains the key.
- **ContextVar isolation:** two sequential requests with different keys each use their
  own key; a third request with none falls back to env (or errors cleanly).
- **Models filtering:** `/api/models` returns only providers whose key header is
  present; SAP IDs when a base URL header is present.
- **Header plumbing:** an integration check that `X-LLM-*` headers survive the Next.js
  rewrite to the backend.

## 9. Affected Files

**Server:** `server/llm/config.py`, `server/llm/{openai,anthropic,groq,gemini}_provider.py`,
`server/llm/base_provider.py` (if client construction is hoisted), `server/routes/models.py`,
a new credentials/dependency module (e.g. `server/llm/credentials.py`), wiring in
`server/routes/agents.py` and `server/routes/simulation.py`, and tests under `server/tests/`.

**Client:** new `ApiKeysProvider`/context + modal component, `client/lib/api.ts`,
`client/components/toolbar.tsx`, and wherever run actions / model picker live
(`client/components/app.tsx`, panels).

## 10. Non-Goals (YAGNI)

- No server-side storage of keys (no DB, no session store, no token exchange).
- No `localStorage` / cross-session persistence.
- No per-user accounts or auth system.
- No encryption-at-rest of keys (there is no "rest" — keys are never stored server-side;
  in the browser they live only in session memory).

## 11. Open Questions

None outstanding. (Operator's own real keys currently in `.env` should be rotated and
the deployment run keyless — tracked separately from this feature.)

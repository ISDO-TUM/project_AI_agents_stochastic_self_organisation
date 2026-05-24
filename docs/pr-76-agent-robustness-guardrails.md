# PR #76 — Agent Robustness & Guardrails

> **Ticket:** Agents must be robust against hallucinations and malicious attacks.  
> **Branch:** `feat/76-agent-robustness-guardrails` → `main`  
> **Tests:** 128 / 128 ✅ (+65 new)

Two adversarial audit passes were performed with full source access. All 30 findings are fixed across a 4-layer defence-in-depth stack:

```
HTTP Request
    → [1] Schema Layer       field limits · UUID validation · model allowlist · list/dict caps
    → [2] Input Guardrail    injection patterns (7 classes) · repetition DoS
    → [3] Prompt Builder     anti-hallucination 6-rule prefix on every system prompt
    → [4] Output Validator   echo detection · refusal guard · empty guard
    → LLM Provider           60 s timeout · max_iterations=5
```

---

## New: `server/guardrails/`

| Module | What it does |
|--------|-------------|
| `input_sanitizer.py` | Blocks instruction overrides, role-switch, DAN jailbreak, delimiter smuggling, meta-overrides, repetition DoS → `PromptInjectionError` |
| `prompt_builder.py` | Prepends 6 non-negotiable rules (no fabrication, cite only provided context, admit uncertainty, no role-switching) to every system prompt |
| `output_validator.py` | Post-generation checks: injection echo → 502, LLM refusal → 422, empty output → 502 |

## New: `server/llm/model_catalogue.py`

Single source of truth for all 34 allowed model IDs. Both `schemas/__init__.py` and `routes/models.py` derive their lists from it — the advertised list and the enforced list are always identical.

---

## Audit Findings

### Pass 1 — 13 findings

| # | Sev | Location | Finding → Fix |
|---|-----|----------|--------------|
| 1 | 🔴 | `schemas/` | All string fields unbounded → `max_length` on every field |
| 2 | 🔴 | `routes/agents.py` | No injection detection on `/run` → `sanitize_prompt()` |
| 3 | 🔴 | `simulation/` | No injection detection on simulation → `sanitize_prompt()` in `_call_agent` |
| 4 | 🔴 | `schemas/` | Free-form `model` field → `@field_validator` against allowlist |
| 5 | 🔴 | `llm/base_provider.py` | No timeout → `asyncio.wait_for(60s)` |
| 6 | 🔴 | `llm/base_provider.py` | `max_iterations=10` → reduced to `5` |
| 7 | 🟠 | `routes/agents.py` | No output validation → `validate_llm_output()` post-generation |
| 8 | 🟠 | `simulation/` | Raw system prompt → `build_guarded_system_prompt()` on every call |
| 9 | 🟠 | `routes/agents.py` | `TimeoutError` bubbles as 500 → caught, returns 504 |
| 10 | 🟡 | `index.py` | `allow_methods=["*"]` includes CONNECT/TRACE → explicit list |
| 11–13 | 🟡 | `schemas/` | Test schemas: no length limits, no model allowlist, no exception exports → fixed |

### Pass 2 — 17 findings

| # | Sev | Location | Attack vector → Fix |
|---|-----|----------|--------------------|
| 1 | 🔴 | `schemas/` | `ALLOWED_MODELS` hardcoded, diverged from `routes/models.py` → derived from `model_catalogue.py` |
| 2 | 🔴 | `routes/files.py` | File content stored raw → injected verbatim into agent context → `sanitize_prompt()` on POST/PUT/PATCH |
| 3 | 🔴 | `simulation/` | `ruleset` injected raw into system prompt → `sanitize_prompt()` before prepend |
| 4 | 🟠 | `schemas/` | `AgentUpdate.model` had no allowlist → PATCH bypassed cost control → `@field_validator` added |
| 5 | 🟠 | `schemas/` | `AgentCreate.id` accepted arbitrary strings → FK poisoning → UUID format validation |
| 6 | 🟠 | `schemas/` | `KnowledgeFileCreate.id` same issue → UUID validation |
| 7 | 🟠 | `db/__init__.py` | File names interpolated raw into system prompt → `\n"<>` stripped in `hint_files_in_prompt` |
| 8 | 🟠 | `schemas/` | `tools`/`connections` lists unbounded → `max_length=20`/`50` |
| 9 | 🟠 | `schemas/` | `FilesToolRequest.files` dict unbounded → `max_length=20` |
| 10 | 🟠 | `schemas/` | `agent_context` uncapped → memory DoS → max 100 entries × 8 000 chars |
| 11 | 🟡 | `routes/test.py` | Test endpoints bypassed all guardrails → `sanitize_prompt()` in all three handlers |
| 12 | 🟡 | `routes/history.py` | `GET /messages` full table dump → `limit` param (default 500, max 2 000) |
| 13 | 🟡 | `routes/history.py` | `message_type` free-form string → validated against closed 8-value allowlist |
| 14 | 🟡 | `index.py` | `allow_headers=["*"]` → explicit 6-header allowlist |
| 15 | 🟡 | `index.py` | No security headers → middleware adds `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` |
| 16 | 🟡 | `schemas/` | `KnowledgeFileUpdate` fields unbounded → `max_length` on name + content |
| 17 | 🟡 | `routes/models.py` | Model list hardcoded separately from schema allowlist → both from `model_catalogue.py` |

---

## Test Coverage

| Class | Tests | Covers |
|-------|-------|--------|
| `TestInputSanitizer` | 17 | All 7 injection patterns + clean inputs |
| `TestOutputValidator` | 9 | Echo, refusal, empty, clean |
| `TestPromptBuilder` | 6 | Block structure, all 6 rules |
| `TestSchemaLengthLimits` | 9 | Field length limits |
| `TestModelAllowlist` | 4 | Allow/reject model IDs |
| `TestSchemaSecondPass` | 15 | `AgentUpdate` validator, UUID, list/dict caps, `agent_context` |
| `TestHintFilesInPrompt` | 3 | File name injection stripping |
| `TestHistoryMessageTypeAllowlist` | 4 | `message_type` allowlist + `limit` param |
| **Total** | **67** | |

---

## Attack → Mitigation Summary

| Attack | Blocked by |
|--------|-----------|
| Prompt injection (user input) | `InputSanitizer` on all prompt entry points |
| Stored injection (file upload) | `sanitize_prompt()` in `routes/files` |
| Injection via file names | `hint_files_in_prompt()` char stripping |
| Injection via ruleset / agent_context | `sanitize_prompt()` in `simulation/_call_agent` |
| Role-switch / DAN jailbreak | `InputSanitizer` patterns 2 & 3 |
| Delimiter smuggling | `InputSanitizer` pattern 5 |
| Repetition DoS | `InputSanitizer` pattern 7 |
| Model cost abuse | `@field_validator` on `AgentCreate` + `AgentUpdate` |
| Token / memory DoS | `max_length` on all string, list, and dict fields |
| Hallucination / fabrication | 6-rule `PromptBuilder` block |
| Runaway agent loop | `max_iterations=5` + 60 s timeout |
| Injection echo in response | `OutputValidator` echo detection |
| Full table dump | `limit` param on `GET /messages` |
| SQL-adjacent filter abuse | `message_type` closed allowlist |
| FK poisoning via caller-supplied ID | `_validate_uuid()` on create schemas |
| Clickjacking / MIME sniffing | `X-Frame-Options: DENY` · `X-Content-Type-Options: nosniff` |
| Header fingerprinting | CORS `allow_headers` explicit list |

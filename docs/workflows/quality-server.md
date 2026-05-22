# Workflow: \_quality-server.yml (Server Quality)

**File:** `.github/workflows/_quality-server.yml`
**Type:** Reusable (`workflow_call`), called by [`pr.yml`](pr.md)

---

## What it checks

| Step             | Tool                                    | Scope                                                                        |
| ---------------- | --------------------------------------- | ---------------------------------------------------------------------------- |
| Lint & format    | `ruff` + `ruff-format` (via pre-commit) | PEP 8, import order, style, formatting                                       |
| Type check       | `mypy` (via pre-commit)                 | Static types across `server/`                                                |
| File hygiene     | pre-commit built-ins                    | Trailing whitespace, YAML/JSON validity, merge conflict markers, large files |
| JS/TS formatting | `prettier` (via pre-commit)             | `.ts`, `.tsx`, `.json`, `.css`, `.md`                                        |
| Tests            | `pytest` with coverage                  | All tests in `server/tests/`                                                 |

All lint/format/type checks run via `pre-commit run --all-files`. The pre-commit config lives at `.pre-commit-config.yaml` in the repo root; pre-commit locates it automatically via git.

Tests run against an **in-memory SQLite database** (forced in `conftest.py`). No external services or credentials are needed.

---

## Caching

| Cache                   | Key                                |
| ----------------------- | ---------------------------------- |
| uv package cache        | `server/requirements-dev.txt` hash |
| pre-commit environments | `.pre-commit-config.yaml` hash     |

---

## Running locally

**Lint, format, and type check (everything pre-commit covers):**

```bash
cd server && uv run pre-commit run --all-files
```

**A single hook:**

```bash
cd server && uv run pre-commit run ruff --all-files
cd server && uv run pre-commit run mypy --all-files
cd server && uv run pre-commit run prettier --all-files
```

**Tests with coverage:**

```bash
cd server && uv run pytest --cov=server --cov-report=term-missing
```

**Stop at first failure:**

```bash
cd server && uv run pytest -x --tb=short
```

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for lint, mypy, and pytest failure guidance.

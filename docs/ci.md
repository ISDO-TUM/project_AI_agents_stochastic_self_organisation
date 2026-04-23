# CI — Pull Request Checks

**Workflow:** `.github/workflows/pull-request-checks.yaml`
**Trigger:** Every pull request.

---

## How it works

No PR merges to `main` without passing both jobs:

```
pull_request
    branch-name  ->  validates branch name pattern
    quality      ->  runs the full pre-commit suite
```

`quality` only runs after `branch-name` passes. A badly named branch fails fast and skips the heavier checks.

---

## Job: `branch-name`

Validates the source branch against the project convention before anything else runs.

**Pattern:**

```
<type>/<issue-number>-<short-description>
```

```
feat/42-sap-agent-streaming    OK
fix/17-hydration-mismatch      OK
my-feature                     FAIL  no type, no issue number
feature/new-endpoint           FAIL  missing issue number
```

Valid types: `feat` `fix` `docs` `refactor` `test` `ci` `chore` `perf`

See [CONTRIBUTING.md](../CONTRIBUTING.md#branch-naming) for the full reference.

---

## Job: `quality`

Installs the full toolchain and runs `pre-commit run --all-files`.

**Toolchain:**

| Tool        | Version       |
| ----------- | ------------- |
| Python / uv | 3.12 / latest |
| Node.js     | 22 LTS        |
| pnpm        | 9             |

**What runs** (in order):

| Hook                                   | Scope                       |
| -------------------------------------- | --------------------------- |
| `trailing-whitespace`                  | All files                   |
| `end-of-file-fixer`                    | All files                   |
| `check-yaml` / `check-json`            | Config files                |
| `check-merge-conflict`                 | All files                   |
| `check-added-large-files` (max 500 KB) | All files                   |
| `no-commit-to-branch`                  | Blocks commits to `main`    |
| `ruff` + `ruff-format`                 | Python (`api/`)             |
| `mypy`                                 | Python (`api/`)             |
| `prettier`                             | JS, TS, CSS, JSON, Markdown |
| `tsc --noEmit`                         | TypeScript (`app/`)         |

---

## Reproducing CI locally

To run exactly what CI runs:

```bash
cd api && uv run pre-commit run --all-files
```

To run a single hook:

```bash
cd api && uv run pre-commit run ruff --all-files
cd api && uv run pre-commit run mypy --all-files
cd api && uv run pre-commit run tsc --all-files
cd api && uv run pre-commit run prettier --all-files
```

If a hook fails in CI but passes locally, make sure your local dependencies are up to date:

```bash
uv pip install -r api/requirements-dev.txt
pnpm install
```

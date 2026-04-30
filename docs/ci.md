# CI — Pull Request Checks

**Workflow:** `.github/workflows/pull-request-checks.yaml`
**Trigger:** Every pull request targeting `main`.

> **Why does CI exist?** It's the safety net that catches issues before they land on `main` — bad branch names, broken types, unformatted code. If CI is green, the basics are solid.

---

## ⚙️ How it works

No PR merges to `main` without passing both jobs:

```
pull_request
    │
    ├── branch-name   validates branch name pattern (fast, runs first)
    │
    └── quality       runs the full pre-commit suite (only if branch-name passes)
```

`quality` only runs after `branch-name` passes. A badly named branch fails fast without wasting time on the heavier checks.

---

## 🌿 Job: `branch-name`

Validates the source branch against the naming convention before anything else runs.

**Pattern:**

```
<type>/<issue-number>-<short-description>
```

| Example                     | Result                             |
| --------------------------- | ---------------------------------- |
| `feat/42-agent-streaming`   | ✅ OK                              |
| `fix/17-hydration-mismatch` | ✅ OK                              |
| `my-feature`                | ❌ FAIL — no type, no issue number |
| `feature/new-endpoint`      | ❌ FAIL — missing issue number     |

Valid types: `feat` `fix` `docs` `refactor` `test` `ci` `chore` `perf`

See [CONTRIBUTING.md](../CONTRIBUTING.md#branch-naming) for the full reference.

---

## 🔍 Job: `quality`

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

## 🖥️ Reproducing CI locally

Run exactly what CI runs before pushing to avoid a round-trip:

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

---

## 🚨 CI failed — now what?

<details>
<summary>❌ branch-name check failed</summary>

Your branch name doesn't match the required pattern. You'll need to rename the branch:

```bash
# rename the current branch
git branch -m feat/42-my-correct-name

# update the remote if you've already pushed
git push origin -u feat/42-my-correct-name
git push origin --delete old-branch-name
```

See [CONTRIBUTING.md](../CONTRIBUTING.md#branch-naming) for valid types and format.

</details>

<details>
<summary>❌ quality check failed (formatting)</summary>

A formatter (`ruff-format`, `prettier`) found code that isn't formatted to spec. Run the hooks locally to auto-fix:

```bash
cd api && uv run pre-commit run --all-files
git add -A
git commit -m "style: apply formatter fixes"
git push
```

</details>

<details>
<summary>❌ quality check failed (mypy or tsc type error)</summary>

A type error slipped through. Run the specific hook locally to see the exact error:

```bash
cd api && uv run pre-commit run mypy --all-files
# or
cd api && uv run pre-commit run tsc --all-files
```

Fix the type error, commit, and push. The error output is usually clear about what's missing.

</details>

<details>
<summary>❌ CI passed locally but fails on GitHub</summary>

The most common cause is stale dependencies. Make sure your local environment is up to date:

```bash
uv pip install -r api/requirements-dev.txt
pnpm install
```

Then run the full suite again:

```bash
cd api && uv run pre-commit run --all-files
```

</details>

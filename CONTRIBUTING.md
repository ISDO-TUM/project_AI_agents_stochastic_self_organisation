# Contributing to Self-Organising Agentic System

Welcome to the team! This guide is the single source of truth for how we work together — branches, commits, code style, and the automated checks that keep everything consistent.

> **tl;dr** — Branch from `main`, name it `feat/42-my-feature`, write [Conventional Commits](https://www.conventionalcommits.org/), and let the hooks handle formatting. That's 90% of it.

---

## 📋 Quick reference

| What          | Pattern                                       | Example                       |
| ------------- | --------------------------------------------- | ----------------------------- |
| Branch        | `<type>/<issue-number>-<description>`         | `feat/42-agent-streaming`     |
| Commit        | `<type>(<scope>): <summary>`                  | `feat(api): add SSE endpoint` |
| Run all hooks | `cd api && uv run pre-commit run --all-files` |                               |

---

## 📜 The golden rules

1. **Every branch ties to a GitHub issue** — no issue, no branch
2. **Every commit is self-describing** — future-you will thank present-you
3. **The hooks are your friend** — they auto-fix most things before you even see a CI failure

---

## 🌿 Branch naming

```
<type>/<issue-number>-<short-description>
```

| Type       | When to use it                    |
| ---------- | --------------------------------- |
| `feat`     | You're building something new     |
| `fix`      | You're squashing a bug            |
| `hotfix`   | Urgent fix for a production issue |
| `refactor` | Same behaviour, better code       |
| `docs`     | Documentation only                |
| `test`     | Adding or updating tests          |
| `chore`    | Deps, config, tooling             |
| `ci`       | CI/CD pipeline changes            |
| `perf`     | Making something faster           |

```bash
# ✅ Good
feat/42-agent-streaming
fix/17-hydration-mismatch
chore/5-pre-commit-setup

# ❌ Will be rejected by CI
my-feature          # no type, no issue number
feature/new-thing   # missing issue number
```

> Direct pushes to `main` are blocked. Always work on a branch and open a PR.

---

## 💬 Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/). `commitlint` enforces this automatically on every `git commit`.

```
<type>(<scope>): <short summary>

[optional body — explain the why, not the what]

Closes #<issue-number>
```

```bash
# ✅ Good
feat(api): add SSE streaming endpoint for agent responses
fix(ui): suppress hydration warning caused by browser extensions
chore: bump ruff to v0.15.11

# ❌ Will be rejected
added new feature       # no type
feat: updated stuff     # vague summary
```

**A few habits that make a big difference:**

- Write in the imperative: `add` not `added`, `fix` not `fixed`
- Keep the subject line under 72 characters
- Always close the issue in the footer: `Closes #42`

> **Why bother?** Good commit history is searchable. When something breaks at 2am, `git log --oneline` is your best friend — but only if the messages actually mean something.

---

## 🪝 Before you push: pre-commit hooks

The hooks run automatically on `git commit` — you don't need to enable anything after `setup.sh`. Here's what runs and why:

| Hook                        | What it does for you                               |
| --------------------------- | -------------------------------------------------- |
| `trailing-whitespace`       | Strips invisible clutter                           |
| `end-of-file-fixer`         | Ensures every file ends with a newline             |
| `check-yaml` / `check-json` | Catches syntax errors before they hit CI           |
| `check-merge-conflict`      | Stops `<<<<<<` markers sneaking into commits       |
| `check-added-large-files`   | Blocks files > 500 KB (use Git LFS for assets)     |
| `no-commit-to-branch`       | Prevents accidental direct commits to `main`       |
| `ruff`                      | Lints Python and auto-fixes what it can            |
| `ruff-format`               | Formats Python code                                |
| `mypy`                      | Type-checks Python (`--strict`)                    |
| `prettier`                  | Formats JS, TS, CSS, JSON, and Markdown            |
| `tsc`                       | Type-checks TypeScript                             |
| `commitlint`                | Validates your commit message format               |
| **pytest + coverage**       | Runs the API test suite and reports total coverage |

Most hooks that touch files (formatters) are **auto-fixing** — they'll modify the file and you just `git add` and commit again. Type errors (`mypy`, `tsc`) and failing tests require a manual fix.

### 🔧 Running hooks manually

```bash
cd api && uv run pre-commit run --all-files          # run everything
cd api && uv run pre-commit run ruff --all-files     # just ruff
cd api && uv run pre-commit run mypy --all-files     # just mypy
cd api && uv run pre-commit run tsc --all-files      # just tsc
cd api && uv run pre-commit run prettier --all-files # just prettier

# Run tests + coverage separately (same command the hook uses)
cd api && uv run pytest --tb=short --cov=. --cov-report=term-missing:skip-covered -q
```

### 🚨 Hook failed? Here’s what to do

#### 🔧 A formatter modified my files (ruff-format, prettier)

The hook auto-fixed your files. Stage the changes and commit again:

```bash
git add -A
git commit -m "your original message"
```

#### 🔴 mypy or tsc type error

This requires a manual fix — add the missing type annotation or resolve the type mismatch. Run the hook again to confirm it passes:

```bash
cd api && uv run pre-commit run mypy --all-files
# or
cd api && uv run pre-commit run tsc --all-files
```

#### 🔴 commitlint rejected my commit message

Your message doesn’t match the [Conventional Commits](https://www.conventionalcommits.org/) format. Common culprits:

- Missing type prefix: `added thing` → `feat: add thing`
- Uppercase subject: `feat: Add thing` → `feat: add thing`
- Past tense: `feat: added thing` → `feat: add thing`

Amend the last commit message with:

```bash
git commit --amend
```

#### 🔴 A test failed

The hook shows which test failed and the short traceback. Fix the test or the code, then commit again.

To iterate quickly without running the full hook suite:

```bash
cd api && uv run pytest --tb=short -q
```

Coverage is shown automatically — no separate command needed.

#### 😶 Hooks aren’t running at all

Re-run the setup script — the git hooks may not have been installed:

```bash
./scripts/setup.sh
```

---

## 🐍 Python code style

Configured in `server/pyproject.toml`. Enforced automatically by **ruff** and **mypy**.

- **Line length:** 100 characters
- **Python version:** 3.12
- **Imports:** stdlib → third-party → first-party (sorted automatically by ruff)
- **Types:** All public functions and classes need type annotations — `mypy --strict` will catch missing ones
- **Async:** Use `async`/`await` for all I/O-bound work (every FastAPI endpoint)
- **Naming:** `snake_case` variables/functions · `PascalCase` classes · `UPPER_SNAKE_CASE` constants

Active lint rules: `E/W` pycodestyle · `F` pyflakes · `I` isort · `N` pep8-naming · `UP` pyupgrade · `B` bugbear · `S` security · `C4` comprehensions · `RUF` ruff-specific.

---

## 🟦 TypeScript code style

Configured in `client/tsconfig.json` (strict mode) and enforced by **ESLint** + **Prettier** + **tsc**.

- **Line length:** 80 characters
- **Quotes:** double · **Semicolons:** yes
- **No `any`** — if you find yourself reaching for it, there's almost always a better way
- **`const` by default** — only use `let` when you genuinely need to reassign
- **Named exports** preferred over default exports (except for pages and layouts, which Next.js requires as default)
- **Styling:** Tailwind utility classes directly on elements — avoid inline `style` props except for truly dynamic values

---

## 🔒 Branch protection on `main`

The following rules are active on GitHub (Settings → Branches):

- Pull request required before merging — no direct pushes
- All CI status checks must pass (`branch-name` + `quality`)
- Branch must be up to date with `main` before merging
- Stale approvals are dismissed when new commits are pushed

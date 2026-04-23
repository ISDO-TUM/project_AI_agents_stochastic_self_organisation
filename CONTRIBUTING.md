# Contributing to SAP AI Agent

Welcome to the team. This guide is the single source of truth for how we work together — branches, commits, code style, and the automated checks that keep everything consistent. Read it once and you'll rarely need to think about it again.

---

## The golden rules

1. **Every branch ties to a GitHub issue** — no issue, no branch
2. **Every commit is self-describing** — future-you will thank present-you
3. **The hooks are your friend** — they auto-fix most things before you even see a CI failure

---

## Branch naming

```
<type>/<issue-number>-<short-description>
```

| Type       | When to use it                |
| ---------- | ----------------------------- |
| `feat`     | You're building something new |
| `fix`      | You're squashing a bug        |
| `refactor` | Same behaviour, better code   |
| `docs`     | Documentation only            |
| `test`     | Adding or updating tests      |
| `chore`    | Deps, config, tooling         |
| `ci`       | CI/CD pipeline changes        |
| `perf`     | Making something faster       |

```bash
# Good
feat/42-sap-agent-streaming
fix/17-hydration-mismatch
chore/5-pre-commit-setup

# Will be rejected by CI
my-feature          # no type, no issue
feature/new-thing   # missing issue number
```

> Direct pushes to `main` are blocked. Always work on a branch and open a PR.

---

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/). `commitlint` enforces this automatically on every `git commit`.

```
<type>(<scope>): <short summary>

[optional body — explain the why, not the what]

Closes #<issue-number>
```

```bash
# Good
feat(api): add SSE streaming endpoint for agent responses
fix(ui): suppress hydration warning caused by browser extensions
chore: bump ruff to v0.15.11

# Will be rejected
added new feature       # no type
feat: updated stuff     # vague summary
```

**A few habits that make a big difference:**

- Write in the imperative: `add` not `added`, `fix` not `fixed`
- Keep the subject line under 72 characters
- Always close the issue in the footer: `Closes #42`

---

## Before you push: pre-commit hooks

The hooks run automatically on `git commit` — you don't need to do anything to enable them after setup. Here's what runs and why:

| Hook                        | What it does for you                           |
| --------------------------- | ---------------------------------------------- |
| `trailing-whitespace`       | Strips invisible clutter                       |
| `end-of-file-fixer`         | Ensures every file ends with a newline         |
| `check-yaml` / `check-json` | Catches syntax errors before they hit CI       |
| `check-merge-conflict`      | Stops `<<<<<<` markers sneaking into commits   |
| `check-added-large-files`   | Blocks files > 500 KB (use Git LFS for assets) |
| `no-commit-to-branch`       | Prevents accidental direct commits to `main`   |
| `ruff`                      | Lints Python and auto-fixes what it can        |
| `ruff-format`               | Formats Python code                            |
| `mypy`                      | Type-checks Python (`--strict`)                |
| `prettier`                  | Formats JS, TS, CSS, JSON, and Markdown        |
| `tsc`                       | Type-checks TypeScript                         |
| `commitlint`                | Validates your commit message format           |

If a hook fails and you want to dig in or run something manually:

```bash
cd api && uv run pre-commit run --all-files          # run everything
cd api && uv run pre-commit run ruff --all-files     # run just ruff
cd api && uv run pre-commit run tsc --all-files      # run just tsc
```

---

## Python code style

Configured in `api/pyproject.toml`. Enforced by **ruff** and **mypy**.

- **Line length:** 100 characters
- **Python version:** 3.12
- **Imports:** stdlib → third-party → first-party (sorted automatically by ruff)
- **Types:** All public functions and classes need type annotations — `mypy --strict` will catch any missing ones
- **Async:** Use `async`/`await` for all I/O-bound work (every FastAPI endpoint)
- **Naming:** `snake_case` variables and functions · `PascalCase` classes · `UPPER_SNAKE_CASE` constants

Active lint rules: `E/W` pycodestyle · `F` pyflakes · `I` isort · `N` pep8-naming · `UP` pyupgrade · `B` bugbear · `S` security · `C4` comprehensions · `RUF` ruff-specific.

---

## TypeScript code style

Configured in `app/tsconfig.json` (strict mode) and enforced by **ESLint** + **Prettier** + **tsc**.

- **Line length:** 80 characters
- **Quotes:** double · **Semicolons:** yes
- **No `any`** — if you find yourself reaching for it, there's a better way
- **`const` by default** — only use `let` when you genuinely reassign
- **Named exports** preferred over default exports (except for pages and layouts, which Next.js requires as default)
- **Styling:** Tailwind utility classes directly on elements — avoid inline `style` props except for truly dynamic values

---

## Branch protection on `main`

The following rules are active on GitHub (Settings → Branches):

- Pull request required before merging — no direct pushes
- All CI status checks must pass (`branch-name` + `quality`)
- Branch must be up to date with `main` before merging
- Stale approvals are dismissed when new commits are pushed

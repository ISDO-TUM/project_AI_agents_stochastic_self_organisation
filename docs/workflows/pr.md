# Workflow: pr.yml (Pull Request Checks)

**File:** `.github/workflows/pr.yml`
**Trigger:** `pull_request` targeting `main`

---

## What it does

```
pull_request
      │
  branch-name  (inline bash check, not complex enough to warrant its own file)
      │
  ┌───┴───────────────────┐
  │                       │
_quality-server       _quality-client      ← parallel
```

The branch-name job must pass before either quality job starts. Both quality jobs are independent of each other and run in parallel to minimise wall-clock time.

---

## Concurrency

```yaml
concurrency:
  group: pr-${{ github.head_ref }}
  cancel-in-progress: true
```

One run per branch at a time. Pushing a new commit to an open PR cancels the previous in-progress run for that branch, preventing stale runs from consuming CI minutes.

---

## Job: `branch-name`

Validates the source branch name against the project convention before any expensive work runs.

**Pattern:** `<type>/<issue-number>-<short-description>`

| Example                     | Result                      |
| --------------------------- | --------------------------- |
| `feat/42-agent-streaming`   | ✅                          |
| `fix/17-hydration-mismatch` | ✅                          |
| `my-feature`                | ❌ no type, no issue number |
| `feature/new-endpoint`      | ❌ missing issue number     |

Valid types: `feat` `fix` `docs` `refactor` `test` `ci` `chore` `perf`

Dependabot branches are exempt (they follow their own convention).

**If this fails:** see [troubleshooting.md](troubleshooting.md#branch-name-check-failed).

---

## Jobs: `quality-server` and `quality-client`

Both delegate to their respective reusable workflows:

- [`_quality-server.yml`](quality-server.md): lint, type check, and test the Python server
- [`_quality-client.yml`](quality-client.md): lint, typecheck, and build the Next.js client

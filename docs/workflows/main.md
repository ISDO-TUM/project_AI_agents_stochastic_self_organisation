# Workflow: main.yml (Deploy)

**File:** `.github/workflows/main.yml`
**Trigger:** `push` to `main`, `workflow_dispatch`

---

## What it does

```
push to main
      │
  _deploy
  (deploy-server + deploy-client in parallel)
```

Quality checks do **not** run here. Main is protected by a GitHub ruleset that blocks force-pushes and requires all PRs to pass CI before merging. Quality is guaranteed before any commit reaches `main`, so re-running it would waste CI minutes for no added safety.

---

## Concurrency

```yaml
concurrency:
  group: deploy-main
  cancel-in-progress: false
```

Only one deploy runs at a time. Unlike PR runs, in-progress deploys are **not** cancelled when a new push arrives. Interrupting a deploy mid-flight risks leaving services in a broken state. New pushes queue behind the running deploy instead.

---

## Job: `deploy`

Delegates entirely to [`_deploy.yml`](deploy.md).

Secrets are forwarded via `secrets: inherit`. No secrets are redeclared in this file.

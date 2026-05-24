# Workflow: \_deploy.yml (Railway Deploy)

**File:** `.github/workflows/_deploy.yml`
**Type:** Reusable (`workflow_call`), called by [`main.yml`](main.md)

---

## What it does

Deploys both services to Railway in parallel:

| Job             | Service            | Working directory |
| --------------- | ------------------ | ----------------- |
| `deploy-server` | `server` (FastAPI) | `server/`         |
| `deploy-client` | `client` (Next.js) | repo root         |

Both jobs use `railway up --detach` so the CI step exits immediately after the deploy is queued, rather than waiting for Railway's full build to complete.

---

## Required secrets

Passed from the caller via `secrets: inherit`. Set these in the repository's GitHub secrets:

| Secret               | Purpose                                       |
| -------------------- | --------------------------------------------- |
| `RAILWAY_TOKEN`      | Authentication token for the Railway CLI      |
| `RAILWAY_PROJECT_ID` | Identifies which Railway project to deploy to |

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md#deploy-failed) for Railway failure guidance.

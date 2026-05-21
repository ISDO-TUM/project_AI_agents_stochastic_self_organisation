# Railway Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace HuggingFace Spaces deployment with Railway, using a GitHub Actions workflow that deploys both services to a project-scoped Railway token — so any team member's merge to `main` triggers deployment without needing a personal Railway account.

**Architecture:** The repo has two independent services — `server/` (FastAPI/Python) and `client/` (Next.js). Each gets its own `railway.toml`. The server service uses `server/` as its Railway root directory; the client service uses the repo root (it needs `pnpm-workspace.yaml` and the root lock file). A single GitHub Actions workflow deploys both services in parallel using a project-scoped `RAILWAY_TOKEN` stored in GitHub secrets.

**Tech Stack:** Railway CLI (`@railway/cli`), GitHub Actions, Docker (existing `server/Dockerfile` and `client/Dockerfile`), pnpm workspaces.

---

## Pre-requisites (done once by whoever owns the Railway account)

Before the GitHub Actions workflow can run, one team member must:

1. Create a Railway project with two services named exactly **`server`** and **`client`**
2. Set the **Root Directory** for the `server` service to `/server` in Railway dashboard
3. Leave the **Root Directory** for the `client` service as `/` (repo root)
4. Generate a **project token**: Railway dashboard → Project Settings → Tokens → New Token
5. Add the token to GitHub: repo → Settings → Secrets and variables → Actions → New secret → name: `RAILWAY_TOKEN`
6. Set the `INTERNAL_API_URL` environment variable on the `client` Railway service to point to the server's Railway private domain (e.g. `http://server.railway.internal:8000` — Railway dashboard → client service → Variables)

---

## Files Changed

| Action   | Path                                              | Purpose                                      |
|----------|---------------------------------------------------|----------------------------------------------|
| Delete   | `Dockerfile`                                      | HuggingFace combined monolithic build        |
| Delete   | `hf/supervisord.conf`                             | HuggingFace supervisord config               |
| Delete   | `.github/workflows/deploy-huggingface.yaml`       | HuggingFace push workflow                    |
| Modify   | `pnpm-workspace.yaml`                             | Fix stale `app` → `client` directory name    |
| Modify   | `package.json`                                    | Fix stale `api` → `server` in dev script     |
| Modify   | `client/Dockerfile`                               | Fix stale `app/` → `client/` in COPY paths   |
| Modify   | `docker-compose.yaml`                             | Fix service names and paths                  |
| Modify   | `.github/workflows/pull-request-checks.yaml`      | Fix stale `api` → `server` paths             |
| Create   | `server/railway.toml`                             | Railway build/deploy config for server       |
| Create   | `railway.toml`                                    | Railway build/deploy config for client       |
| Create   | `.github/workflows/deploy-railway.yaml`           | CI workflow: deploy both services on merge   |

---

## Task 1: Remove HuggingFace Artifacts

**Files:**
- Delete: `Dockerfile`
- Delete: `hf/supervisord.conf` (and the now-empty `hf/` directory)
- Delete: `.github/workflows/deploy-huggingface.yaml`

- [ ] **Step 1: Delete the three HuggingFace files**

```bash
rm /path/to/repo/Dockerfile
rm -rf /path/to/repo/hf
rm /path/to/repo/.github/workflows/deploy-huggingface.yaml
```

- [ ] **Step 2: Verify they are gone**

```bash
ls Dockerfile hf .github/workflows/deploy-huggingface.yaml 2>&1
```

Expected: `ls: cannot access ...` for all three — none should exist.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "ci: remove HuggingFace deployment artifacts"
```

---

## Task 2: Fix Stale `app` → `client` in Workspace Config

The `app/` directory was renamed to `client/` but `pnpm-workspace.yaml` and `package.json` still reference the old name.

**Files:**
- Modify: `pnpm-workspace.yaml`
- Modify: `package.json`

- [ ] **Step 1: Update pnpm-workspace.yaml**

Replace the `packages` block. The file currently reads:

```yaml
packages:
  - 'app'
```

Change it to:

```yaml
packages:
  - 'client'
```

Full file after change:

```yaml
packages:
  - 'client'

overrides:
  postcss: ^8.5.10

ignoredBuiltDependencies:
  - sharp
  - unrs-resolver
```

- [ ] **Step 2: Update package.json dev scripts**

The `dev:api` script references the old `api` directory (now `server`) and old module path. Also fix the `clean` script.

Change:

```json
"dev:api": "sh -c 'PATH=$HOME/.local/bin:$PATH uv run --project api uvicorn api.index:app --reload --reload-dir api --port 8000'",
"clean": "rm -rf node_modules app/node_modules api/.venv api/__pycache__"
```

To:

```json
"dev:api": "sh -c 'PATH=$HOME/.local/bin:$PATH uv run --project server uvicorn server.index:app --reload --reload-dir server --port 8000'",
"clean": "rm -rf node_modules client/node_modules server/.venv server/__pycache__"
```

The `--filter app` in the `dev` script filters by **package name** (`"name": "app"` in `client/package.json`), not directory name — no change needed there.

- [ ] **Step 3: Verify pnpm can resolve the workspace**

```bash
pnpm install --frozen-lockfile
```

Expected: exits 0, no "workspace package not found" errors.

- [ ] **Step 4: Commit**

```bash
git add pnpm-workspace.yaml package.json
git commit -m "fix: update workspace and dev script references from app/api to client/server"
```

---

## Task 3: Fix `client/Dockerfile` Paths

The Dockerfile still copies from `app/` (old directory name). Since the Dockerfile is built from the repo root as build context, all `app/` paths must become `client/`.

**Files:**
- Modify: `client/Dockerfile`

- [ ] **Step 1: Update all `app/` COPY source paths**

The full corrected `client/Dockerfile`:

```dockerfile
# ---- base: pnpm toolchain (build stages only) ----
FROM node:22-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

# ---- deps: install node_modules ----
FROM base AS deps
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY client/package.json ./client/package.json
RUN pnpm install --frozen-lockfile

# ---- builder: compile Next.js standalone output ----
FROM base AS builder
WORKDIR /workspace
COPY --from=deps /workspace/node_modules ./node_modules
COPY package.json pnpm-workspace.yaml ./
COPY client/ ./client/
RUN pnpm --filter app build

# ---- runtime: minimal — no pnpm, no node_modules, just the standalone server ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0" \
    NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /workspace/client/public ./public
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD wget -qO- http://localhost:3000 || exit 1

CMD ["node", "server.js"]
```

Note: `CMD ["node", "server.js"]` — Next.js standalone output places the entry point at `server.js` in the root of `.next/standalone/`. The old `app/server.js` was a leftover from when the directory was named `app/`.

- [ ] **Step 2: Verify the Dockerfile builds**

From the repo root:

```bash
docker build -f client/Dockerfile -t client-test .
```

Expected: exits 0, produces a runnable image.

- [ ] **Step 3: Commit**

```bash
git add client/Dockerfile
git commit -m "fix: update client Dockerfile paths from app/ to client/"
```

---

## Task 4: Fix `docker-compose.yaml`

Service names `api`/`app` are stale; build paths reference the old directories.

**Files:**
- Modify: `docker-compose.yaml`

- [ ] **Step 1: Rewrite docker-compose.yaml**

Full corrected file:

```yaml
services:
  server:
    build:
      context: ./server
    ports:
      - "8000:8000"
    env_file:
      - .env
    restart: unless-stopped
    develop:
      watch:
        - action: sync
          path: ./server
          target: /app/server

  client:
    build:
      context: .
      dockerfile: client/Dockerfile
    ports:
      - "3000:3000"
    env_file:
      - .env
    environment:
      - INTERNAL_API_URL=http://server:8000
    restart: unless-stopped
    depends_on:
      server:
        condition: service_healthy
```

- [ ] **Step 2: Verify compose config parses**

```bash
docker compose config --quiet
```

Expected: exits 0 with no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yaml
git commit -m "fix: update docker-compose service names and paths from api/app to server/client"
```

---

## Task 5: Fix `pull-request-checks.yaml`

The quality job installs Python deps and runs pre-commit using `cd api` which no longer exists. Also fix stale action versions.

**Files:**
- Modify: `.github/workflows/pull-request-checks.yaml`

- [ ] **Step 1: Update the quality job steps**

Change the two `api` references to `server`:

```yaml
      - name: Install Python dependencies
        run: cd server && uv venv && uv pip install -r requirements-dev.txt

      - name: Run pre-commit on all files
        run: cd server && uv run pre-commit run --all-files
```

Also fix the action versions (v6 does not exist for checkout/setup-node):

```yaml
      - uses: actions/checkout@v4

      - uses: astral-sh/setup-uv@v7

      - uses: actions/setup-node@v4
        with:
          node-version: 22
```

Full corrected file:

```yaml
name: Pull Request Checks

on: [pull_request]

jobs:
  branch-name:
    runs-on: ubuntu-latest
    steps:
      - name: Validate branch name
        run: |
          # Dependabot is exempt — its branch names follow its own convention
          if [[ "${{ github.actor }}" == "dependabot[bot]" ]]; then
            echo "✅ Dependabot branch — skipping name convention check."
            exit 0
          fi
          BRANCH="${{ github.head_ref }}"
          PATTERN="^(feat|fix|docs|refactor|test|ci|chore|perf)/[0-9]+-[a-z0-9-]+$"
          if [[ ! "$BRANCH" =~ $PATTERN ]]; then
            echo "❌ Branch name '$BRANCH' does not follow the convention."
            echo "   Expected: <type>/<issue-number>-<short-description>"
            echo "   Example:  feat/42-agent-streaming"
            exit 1
          fi
          echo "✅ Branch name '$BRANCH' is valid."

  quality:
    runs-on: ubuntu-latest
    needs: branch-name
    steps:
      - uses: actions/checkout@v4

      # --- Toolchain setup ---
      - uses: astral-sh/setup-uv@v7

      - uses: actions/setup-node@v4
        with:
          node-version: 22

      - uses: pnpm/action-setup@v6.0.5
        with:
          version: 9

      # --- Install dependencies ---
      - name: Install Python dependencies
        run: cd server && uv venv && uv pip install -r requirements-dev.txt

      - name: Install Node dependencies
        run: pnpm install

      # --- Static analysis & formatting ---
      - name: Run pre-commit on all files
        run: cd server && uv run pre-commit run --all-files
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/pull-request-checks.yaml
git commit -m "fix: update PR checks workflow paths from api to server"
```

---

## Task 6: Add `server/railway.toml`

Railway reads this file when the `server` service has its root directory set to `/server`.

**Files:**
- Create: `server/railway.toml`

- [ ] **Step 1: Create server/railway.toml**

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/api/docs"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

- [ ] **Step 2: Commit**

```bash
git add server/railway.toml
git commit -m "ci: add Railway config for server service"
```

---

## Task 7: Add Root `railway.toml` (Client)

Railway reads this file when the `client` service has its root directory set to `/` (repo root). The Dockerfile path is relative to the repo root.

**Files:**
- Create: `railway.toml`

- [ ] **Step 1: Create railway.toml at repo root**

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "client/Dockerfile"

[deploy]
healthcheckPath = "/"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

- [ ] **Step 2: Commit**

```bash
git add railway.toml
git commit -m "ci: add Railway config for client service"
```

---

## Task 8: Add `deploy-railway.yaml` GitHub Actions Workflow

This workflow fires on every push to `main` (i.e. after a PR is merged) and deploys both services in parallel. It uses `RAILWAY_TOKEN` — a project-scoped token stored in GitHub repository secrets, so any team member's merge triggers the deploy regardless of whose account owns the Railway project.

**Files:**
- Create: `.github/workflows/deploy-railway.yaml`

- [ ] **Step 1: Create the workflow**

```yaml
name: Deploy to Railway

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy-server:
    name: Deploy server
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy server service
        working-directory: server
        run: railway up --service server --detach
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}

  deploy-client:
    name: Deploy client
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy client service
        run: railway up --service client --detach
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
```

**Why two jobs?** Server and client are independent. Running them as parallel jobs halves total deploy time. Each job checks out the repo fresh and deploys from the correct working directory: `server/` for the server (matching its Railway root dir), repo root for the client.

**Why `--detach`?** Without it, `railway up` streams logs until the deployment finishes, which can take several minutes and ties up the runner. With `--detach`, the command returns as soon as Railway has accepted the build. You can monitor progress in the Railway dashboard.

- [ ] **Step 2: Verify the workflow YAML is valid**

```bash
# Install the GitHub Actions validator if available
npx action-validator .github/workflows/deploy-railway.yaml
# or use yamllint
yamllint .github/workflows/deploy-railway.yaml
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-railway.yaml
git commit -m "ci: add Railway deployment workflow triggered on push to main"
```

---

## Done — Verification Checklist

After all tasks are complete, verify the full setup:

- [ ] `ls Dockerfile hf` fails (HuggingFace artifacts gone)
- [ ] `pnpm install --frozen-lockfile` succeeds from repo root
- [ ] `docker compose config --quiet` exits 0
- [ ] `docker build -f client/Dockerfile -t client-test .` exits 0
- [ ] `docker build -f server/Dockerfile -t server-test ./server` exits 0
- [ ] Both `railway.toml` files exist: `railway.toml` and `server/railway.toml`
- [ ] `.github/workflows/deploy-railway.yaml` exists
- [ ] `.github/workflows/deploy-huggingface.yaml` does not exist
- [ ] `RAILWAY_TOKEN` secret is set in GitHub repository settings (manual step)
- [ ] Railway project has services named exactly `server` and `client` (manual step)

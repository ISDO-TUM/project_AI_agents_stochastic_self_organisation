# Local Development

There are two ways to run the project. Pick the one that fits your situation.

| Mode              | Best for                                                          |
| ----------------- | ----------------------------------------------------------------- |
| [Native](#native) | Day-to-day work — hot reload, fast feedback                       |
| [Docker](#docker) | Testing the production build, onboarding without installing tools |

---

## Native

### First-time setup

You only need **[Node.js 22 LTS](https://nodejs.org/)** pre-installed. The setup script handles everything else:

```bash
./scripts/setup.sh
```

This will:

- Install `uv` (Python toolchain) if missing
- Install `pnpm` if missing
- Install all Python and Node dependencies
- Wire the git pre-commit hooks

### Start the dev server

```bash
pnpm dev
```

Both services start concurrently with hot reload:

| Service          | URL                   | Reload              |
| ---------------- | --------------------- | ------------------- |
| Next.js frontend | http://localhost:3000 | Turbopack (instant) |
| FastAPI backend  | http://localhost:8000 | uvicorn `--reload`  |

### Useful commands

```bash
pnpm dev                                         # start both services
pnpm clean                                       # wipe all artefacts and deps

cd api && uv run pre-commit run --all-files      # run all quality hooks manually
```

### Environment variables

`setup.sh` creates an empty `.env` at the repo root. Add your secrets there — it's gitignored:

```bash
# .env
OPENAI_API_KEY=sk-...
```

Variables prefixed with `NEXT_PUBLIC_` are injected into the browser bundle at build time. Everything else is server-side only and stays out of the client.

---

## Docker

### Prerequisites

[Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose).

### Start the stack

```bash
docker compose up --build   # build images and start everything
```

| Service          | URL                   |
| ---------------- | --------------------- |
| Next.js frontend | http://localhost:3000 |
| FastAPI backend  | http://localhost:8000 |

### Useful commands

```bash
docker compose up --build       # build and start
docker compose up               # start without rebuilding
docker compose down             # stop
docker compose logs -f api      # tail API logs
docker compose logs -f app      # tail frontend logs
docker compose down --volumes   # stop and remove all volumes
```

### How the containers connect

```
docker-compose.yaml
    api  ->  api/Dockerfile        python:3.12-slim, production deps only
    app  ->  app/Dockerfile        node:22-alpine, standalone Next.js build
```

The `app` container reaches the API at `http://api:8000` over Docker's internal network (set via `NEXT_PUBLIC_API_URL`). This differs from native development where both run on `localhost`.

In production (Vercel), API routing goes through the rewrites in `vercel.json` instead.

---

## Port reference

| Port | Service       |
| ---- | ------------- |
| 3000 | Next.js (UI)  |
| 8000 | FastAPI (API) |

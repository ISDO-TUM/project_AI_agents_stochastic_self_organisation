# Local Development

There are two ways to run the project. Pick the one that fits your situation.

| Mode              | Best for                                                          |
| ----------------- | ----------------------------------------------------------------- |
| [Native](#native) | Day-to-day work — hot reload, fast feedback, best DX              |
| [Docker](#docker) | Testing the production build, onboarding without installing tools |

---

## 💻 Native

### 🚀 First-time setup

**Prerequisite:** [Node.js 22 LTS](https://nodejs.org/) — that's the only thing you need to install manually. The setup script handles everything else:

```bash
./scripts/setup.sh
```

This will:

- Install `uv` (Python toolchain) if missing
- Install `pnpm` if missing
- Install all Python and Node dependencies
- Wire up the git pre-commit hooks
- Create an empty `.env` file at the repo root

### ▶️ Start the dev server

```bash
pnpm dev
```

Both services start concurrently with hot reload:

| Service          | URL                                            | Reload              |
| ---------------- | ---------------------------------------------- | ------------------- |
| Next.js frontend | [http://localhost:3000](http://localhost:3000) | Turbopack (instant) |
| FastAPI backend  | [http://localhost:8000](http://localhost:8000) | uvicorn `--reload`  |

> **Is it working?** Open [http://localhost:3000](http://localhost:3000) — if you see the UI, the frontend is up. Open [http://localhost:8000/docs](http://localhost:8000/docs) — if you see the FastAPI Swagger UI, the backend is up. Both should start within a few seconds.

### 🔐 Environment variables

`setup.sh` creates an empty `.env` at the repo root. Add your secrets there — it's gitignored:

```bash
# .env
OPENAI_API_KEY=sk-...
```

Variables prefixed with `NEXT_PUBLIC_` are injected into the browser bundle at build time. Everything else is server-side only and never reaches the client.

### 🛠️ Useful commands

```bash
pnpm dev                                          # start both services
pnpm clean                                        # wipe all artefacts and deps

cd api && uv run pre-commit run --all-files       # run all quality hooks manually
```

---

## 🐳 Docker

> **Works on my machine** — Docker makes it everyone's machine.

<!-- 💡 IMAGE SUGGESTION: The classic "works on my machine" meme goes perfectly here.
     Drop the image in docs/assets/ and uncomment below.
     Example: ![works on my machine](assets/works-on-my-machine.jpg) -->

### 📦 Prerequisites

[Docker Desktop](https://www.docker.com/products/docker-desktop/) (includes Docker Compose).

### ▶️ Start the stack

```bash
docker compose up --build   # build images and start everything
```

| Service          | URL                                            |
| ---------------- | ---------------------------------------------- |
| Next.js frontend | [http://localhost:3000](http://localhost:3000) |
| FastAPI backend  | [http://localhost:8000](http://localhost:8000) |

### 🛠️ Useful commands

```bash
docker compose up --build       # build and start
docker compose up               # start without rebuilding
docker compose down             # stop
docker compose logs -f api      # tail API logs
docker compose logs -f app      # tail frontend logs
docker compose down --volumes   # stop and remove all volumes
```

### 🔗 How the containers connect

```
docker-compose.yaml
    api  →  api/Dockerfile        python:3.12-slim, production deps only
    app  →  app/Dockerfile        node:22-alpine, standalone Next.js build
```

The `app` container reaches the API at `http://api:8000` over Docker's internal network (configured via `NEXT_PUBLIC_API_URL`). This differs from native development where both run on `localhost`.

In production (Vercel), API routing goes through the rewrites in `vercel.json` instead.

---

## 🔌 Port reference

| Port | Service       |
| ---- | ------------- |
| 3000 | Next.js (UI)  |
| 8000 | FastAPI (API) |

---

## 🩺 Troubleshooting

<details>
<summary>🔴 <code>setup.sh</code> fails or exits early</summary>

Check that Node.js 22+ is installed:

```bash
node --version   # should print v22.x.x or higher
```

If you're on Windows, make sure you're running this inside WSL 2, not PowerShell or CMD.

Try running the script again — some failures (e.g. a network timeout while downloading packages) are transient.

</details>

<details>
<summary>🔴 Port 3000 or 8000 is already in use</summary>

Something else is running on that port. Find and stop it:

```bash
# find what's using port 3000
lsof -i :3000
# kill it by PID
kill -9 <PID>
```

</details>

<details>
<summary>🔴 API starts but returns 500 errors</summary>

Check that your `.env` file exists at the repo root and contains the required keys. The API will start without them but will fail on requests that need them.

Tail the API logs to see the actual error:

```bash
# native
pnpm dev   # errors print directly to the terminal

# docker
docker compose logs -f api
```

</details>

<details>
<summary>🔴 Pre-commit hooks not running after setup</summary>

Re-run the setup script to reinstall the git hooks:

```bash
./scripts/setup.sh
```

Or install them manually:

```bash
cd api && uv run pre-commit install
```

</details>

<details>
<summary>🔴 <code>pnpm dev</code> works but changes aren't reflected</summary>

The Next.js dev server uses Turbopack for hot reload. If a change isn't picked up, try a hard refresh in the browser (`Ctrl+Shift+R`). If that doesn't work, restart `pnpm dev`.

</details>

---
title: "TUM Agentic Demo"
sdk: docker
python_version: "3.12"
pinned: false
---

<div align="center">

# 🤖 Self-Organising Agentic System

[![CI](https://github.com/ISDO-TUM/project_AI_agents_stochastic_self_organisation/actions/workflows/pull-request-checks.yaml/badge.svg)](https://github.com/ISDO-TUM/project_AI_agents_stochastic_self_organisation/actions)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-22_LTS-339933?logo=node.js&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-black?logo=next.js&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-latest-009688?logo=fastapi&logoColor=white)

_[One-line project description to be added]_

<!-- 💡 IMAGE SUGGESTION: Add a screenshot or a short GIF demo of the app here.
     Drop the file in docs/assets/ and update the path below.
     Example: ![App demo](docs/assets/demo.gif) -->

</div>

---

## 🔍 What is this?

> [Project description to be added — a few sentences on what the agent does, what problem it solves, and who it's for.]

---

## 🛠️ Tech stack

| Layer       | Stack                                  | Location |
| ----------- | -------------------------------------- | -------- |
| 🖥️ Frontend | Next.js 16 · React 19 · Tailwind CSS 4 | `app/`   |
| ⚙️ Backend  | FastAPI · Python 3.12 · AgentOps       | `api/`   |

---

## ⚡ Quick start

> **On Windows?** Use [WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install) — native Windows is not supported. Install Node.js _inside_ WSL.

**The only prerequisite is [Node.js 22 LTS](https://nodejs.org/).** Everything else (`uv`, `pnpm`, Python deps, git hooks) is installed automatically:

```bash
git clone https://github.com/ISDO-TUM/project_AI_agents_stochastic_self_organisation.git
cd project_AI_agents_stochastic_self_organisation
./scripts/setup.sh   # installs everything
pnpm dev             # start the app
```

Open **[http://localhost:3000](http://localhost:3000)** — you're running. 🎉

> Hitting a snag? The [local development guide](docs/local-development.md) has a troubleshooting section.

---

## 🏃 Running locally

```bash
docker compose up -d postgres # start the database (persists to a Docker volume)
pnpm dev                  # UI → localhost:3000 · API → localhost:8000
docker compose up --build # alternatively, run the full stack (incl. Postgres) in Docker
pnpm clean                # wipe all generated artefacts and deps
```

The API requires a PostgreSQL `DATABASE_URL`; `setup.sh` seeds the bundled-Postgres URL into `.env`, so `docker compose up -d postgres` then `pnpm dev` works out of the box. (Tests use in-memory SQLite — no database needed.)

→ Full guide: [docs/local-development.md](docs/local-development.md)

---

## ☁️ Deployment (Railway)

The server and client deploy to Railway via [`.github/workflows/deploy-railway.yaml`](.github/workflows/deploy-railway.yaml). For persistent storage, the server needs a PostgreSQL database:

1. In the Railway project, add a **PostgreSQL** service (attach a volume for persistence).
2. Railway exposes a `DATABASE_URL` reference variable on that service — set the **server** service's `DATABASE_URL` to it (e.g. `${{ Postgres.DATABASE_URL }}`).

The app normalises Railway's `postgresql://` URL to the asyncpg driver and creates its tables on startup, so no manual migration step is required.

---

## 📁 Project layout

```
.
├── api/                    # FastAPI backend (Python 3.12 + AgentOps)
├── app/                    # Next.js frontend (React 19 + Tailwind CSS 4)
├── docs/                   # Project documentation
├── scripts/setup.sh        # One-time setup — run this first
├── docker-compose.yaml     # Full-stack Docker configuration
├── .github/
│   ├── workflows/          # CI pipelines
│   ├── ISSUE_TEMPLATE/     # Bug & feature issue templates
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── .pre-commit-config.yaml # Automated code quality hooks
└── CONTRIBUTING.md         # How we work together
```

---

## 🤝 Contributing

Read **[CONTRIBUTING.md](CONTRIBUTING.md)** before opening a PR. Quick summary:

| What   | Convention                                                                                         |
| ------ | -------------------------------------------------------------------------------------------------- |
| Branch | `feat/42-my-feature` — always include the issue number                                             |
| Commit | `feat(api): add streaming endpoint` ([Conventional Commits](https://www.conventionalcommits.org/)) |
| Hooks  | Run automatically on `git commit` — no manual formatting needed                                    |

New here? The contributing guide is written to be quick — give it 5 minutes and you'll know everything you need.

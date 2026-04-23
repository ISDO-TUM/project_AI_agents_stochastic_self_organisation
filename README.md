# SAP AI Agent — Stochastic Self-Organisation

> [Project description to be added]

---

## What's inside

| Layer       | Stack                                  | Location |
| ----------- | -------------------------------------- | -------- |
| 🖥️ Frontend | Next.js 16 · React 19 · Tailwind CSS 4 | `app/`   |
| ⚙️ Backend  | FastAPI · Python 3.12                  | `api/`   |

---

## Getting started

> **On Windows?** Use [WSL 2](https://learn.microsoft.com/en-us/windows/wsl/install) (Ubuntu). Native Windows is not supported. Install Node.js _inside_ WSL.

The only thing you need before running setup is **[Node.js 22 LTS](https://nodejs.org/)**. Everything else (`uv`, `pnpm`, Python deps, git hooks) is handled automatically:

```bash
./scripts/setup.sh
```

---

## Running locally

```bash
pnpm dev                  # UI → localhost:3000 · API → localhost:8000
docker compose up --build # alternatively, run the full stack in Docker
pnpm clean                # wipe all generated artefacts and deps
```

→ Full guide: [docs/local-development.md](docs/local-development.md)

---

## Project layout

```
.
├── api/                    # FastAPI backend
├── app/                    # Next.js frontend
├── docs/                   # Project documentation
├── scripts/setup.sh        # One-time setup
├── docker-compose.yaml
├── .github/
│   ├── workflows/          # CI pipelines
│   ├── ISSUE_TEMPLATE/     # Bug & feature templates
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── CODEOWNERS
├── .pre-commit-config.yaml
└── CONTRIBUTING.md
```

---

## Contributing

Before you open a PR, read **[CONTRIBUTING.md](CONTRIBUTING.md)** — it covers branch naming, commit format, and code style. The short version:

- Branch: `feat/42-my-feature` (always include the issue number)
- Commit: `feat(api): add streaming endpoint` ([Conventional Commits](https://www.conventionalcommits.org/))
- Hooks run automatically on commit — no manual formatting needed

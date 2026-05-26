# CI/CD Overview

The pipeline uses GitHub Actions with a **reusable workflow** architecture: two small orchestrator workflows call shared building-block workflows prefixed with `_`. This keeps each file focused, avoids duplication, and makes the pipeline easy to extend.

---

## File layout

```
.github/workflows/
  pr.yml                   ← orchestrator: runs on every pull request
  main.yml                 ← orchestrator: runs on every merge to main
  _quality-server.yml      ← reusable: lint + test (Python/server)
  _quality-client.yml      ← reusable: lint + typecheck + build (Next.js/client)
  _deploy.yml              ← reusable: deploy both services to Railway
```

The `_` prefix signals that a workflow is an internal building block. It has no standalone trigger and is only called by an orchestrator via `workflow_call`.

---

## Trigger map

| Event                  | Workflow   | Jobs                                          |
| ---------------------- | ---------- | --------------------------------------------- |
| PR opened / updated    | `pr.yml`   | branch-name → quality-server + quality-client |
| Push to `main` (merge) | `main.yml` | deploy-server + deploy-client                 |
| Manual via GitHub UI   | `main.yml` | deploy-server + deploy-client                 |

**Quality does not re-run on merge.** Main is protected by a GitHub ruleset that blocks force-pushes and requires PRs to pass CI before merging. The quality guarantee already exists at merge time, so skipping the re-run saves CI minutes.

---

## Minute efficiency decisions

| Decision                              | Rationale                                                                          |
| ------------------------------------- | ---------------------------------------------------------------------------------- |
| No quality re-run on `main`           | Ruleset blocks force-pushes; quality was already verified on the PR                |
| `cancel-in-progress: true` on PRs     | Stale runs from rapid pushes are cancelled immediately                             |
| `cancel-in-progress: false` on deploy | Avoids half-deployed states                                                        |
| Parallel quality jobs                 | Server and client checks run concurrently; wall-clock time ≈ the slower of the two |
| uv + pre-commit caching               | Avoids re-downloading packages on every run                                        |

# Workflow: \_quality-client.yml (Client Quality)

**File:** `.github/workflows/_quality-client.yml`
**Type:** Reusable (`workflow_call`), called by [`pr.yml`](pr.md)

---

## What it checks

| Step       | Tool           | Scope                                             |
| ---------- | -------------- | ------------------------------------------------- |
| Lint       | `eslint`       | Code quality and rule violations across `client/` |
| Type check | `tsc --noEmit` | TypeScript type correctness                       |
| Build      | `next build`   | Full production build                             |

The `next build` step is intentional: type checking alone does not catch all build-time errors (missing env references, invalid page exports, route conflicts). A passing build confirms the app is deployable.

---

## Caching

pnpm store, keyed by the lockfile via `actions/setup-node cache: pnpm`.

---

## Running locally

**Lint:**

```bash
pnpm --filter app run lint
```

**Type check:**

```bash
pnpm --filter app run typecheck
```

**Production build:**

```bash
pnpm --filter app run build
```

---

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for ESLint, tsc, and build failure guidance.

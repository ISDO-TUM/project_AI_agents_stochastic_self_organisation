# Troubleshooting

---

<details>
<summary>❌ Branch-name check failed</summary>

Your branch name doesn't match the required pattern. Rename it:

```bash
git branch -m feat/42-my-correct-name
git push origin -u feat/42-my-correct-name
git push origin --delete old-branch-name
```

**Pattern:** `<type>/<issue-number>-<short-description>`

Valid types: `feat` `fix` `hotfix` `docs` `refactor` `test` `ci` `chore` `perf`

See [CONTRIBUTING.md](../../CONTRIBUTING.md#branch-naming) for the full reference.

</details>

---

<details>
<summary>❌ Lint failed (ruff / prettier)</summary>

Run pre-commit locally to auto-fix:

```bash
cd server && uv run pre-commit run --all-files
git add -A && git commit -m "style: apply formatter fixes"
```

</details>

---

<details>
<summary>❌ Type check failed (mypy)</summary>

```bash
cd server && uv run pre-commit run mypy --all-files
```

The error output includes the file, line, and expected type. Fix the annotation and re-run.

</details>

---

<details>
<summary>❌ Type check failed (tsc)</summary>

```bash
pnpm --filter app run typecheck
```

</details>

---

<details>
<summary>❌ Tests failed (pytest)</summary>

```bash
cd server && uv run pytest -x --tb=short
```

The `-x` flag stops at the first failure. Tests run against an in-memory SQLite database. No external services needed locally.

</details>

---

<details>
<summary>❌ Client build failed (next build)</summary>

```bash
pnpm --filter app run build
```

Common causes: a missing `NEXT_PUBLIC_*` environment variable required at build time, or a type/import error that only surfaces during bundling. The build output points to the exact file and line.

</details>

---

<details>
<summary>❌ CI passed locally but fails on GitHub</summary>

Most likely cause: stale local dependencies. Sync them:

```bash
cd server && uv sync --locked
pnpm install
```

Then re-run the full suite locally.

</details>

---

<details>
<summary>❌ Deploy failed</summary>

`railway up --detach` fails here if the CLI cannot authenticate or queue the deploy. This does not mean the service crashed after deployment. Check:

1. `RAILWAY_TOKEN` and `RAILWAY_PROJECT_ID` are set in the repository's GitHub secrets.
2. The Railway project still exists and the token has access.
3. The Railway dashboard for the specific service for post-deploy build or runtime errors.

</details>

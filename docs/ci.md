# CI/CD

- [Overview](workflows/overview.md): architecture, trigger map, efficiency decisions
- [pr.yml](workflows/pr.md): pull request checks (branch name, server quality, client quality)
- [main.yml](workflows/main.md): deploy on merge to main
- [\_quality-server.yml](workflows/quality-server.md): server lint, type check, and tests
- [\_quality-client.yml](workflows/quality-client.md): client lint, typecheck, and production build
- [\_deploy.yml](workflows/deploy.md): Railway deploy for server and client
- [Troubleshooting](workflows/troubleshooting.md)

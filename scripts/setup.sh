#!/usr/bin/env bash
set -e

if [[ "$OSTYPE" == "msys"* || "$OSTYPE" == "cygwin"* ]]; then
    echo "❌ Error: Native Windows is not supported. Use WSL, Linux, or macOS."
    exit 1
fi

if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
fi

if ! command -v pnpm &> /dev/null; then
    # Install the exact pnpm version pinned in package.json's "packageManager"
    # field (the single source of truth). pnpm then self-manages this version
    # on every run, keeping local installs in lock-step with CI and Docker.
    PNPM_VERSION="$(grep -oE 'pnpm@[0-9]+\.[0-9]+\.[0-9]+' package.json | head -1 | cut -d@ -f2)"
    curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION="$PNPM_VERSION" sh -
    export PATH="$HOME/.local/share/pnpm:$PATH"
    echo ""
    echo "⚠️  pnpm was just installed. Its PATH entry is written to your shell config"
    echo "   (~/.bashrc or ~/.zshrc) but won't be active in your current session."
    echo "   If the script fails below, run:  source ~/.bashrc  (or ~/.zshrc)"
    echo "   then re-run ./scripts/setup.sh"
    echo ""
fi

if [ ! -f .env ]; then
    # Seed the connection string for the bundled docker-compose Postgres so
    # `docker compose up -d postgres` + `pnpm dev` works out of the box.
    echo "DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app" > .env
fi

pnpm install
cd server
# uv sync creates server/.venv and installs everything (prod + dev groups)
# straight from uv.lock — the single source of truth shared with CI and Docker.
uv sync
uv run pre-commit install -t pre-commit -t commit-msg
cd ..

# Replace the pre-commit git hook with our pretty-printing wrapper.
# pre-commit's default output is very verbose; the wrapper suppresses noise
# and shows only a one-line status per hook plus errors for failed hooks.
cat > .git/hooks/pre-commit << 'HOOK'
#!/usr/bin/env bash
# Ensure tools installed in user-local paths (uv, pnpm, etc.) are reachable
# even when git invokes this hook with a stripped PATH.
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.local/share/pnpm:$PATH"
ROOT=$(git rev-parse --show-toplevel)
exec "$ROOT/server/.venv/bin/python" "$ROOT/scripts/pre-commit-formatter.py" "$@"
HOOK
chmod +x .git/hooks/pre-commit

echo "🎉 Setup complete!"

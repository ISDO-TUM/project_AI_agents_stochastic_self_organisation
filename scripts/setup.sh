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
    curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION=9.0.0 sh -
    export PATH="$HOME/.local/share/pnpm:$PATH"
fi

if [ ! -f .env ]; then
    touch .env
fi

pnpm install
cd api
uv venv
uv pip install -r requirements-dev.txt
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
exec "$ROOT/api/.venv/bin/python" "$ROOT/scripts/pre-commit-formatter.py" "$@"
HOOK
chmod +x .git/hooks/pre-commit

echo "🎉 Setup complete!"

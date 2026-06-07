# ---- uv binary ----
FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

# ---- builder: install deps into an isolated venv ----
FROM python:3.12-slim AS builder

COPY --from=uv /uv /usr/local/bin/uv

WORKDIR /app

# Install production dependencies into /opt/venv straight from the lockfile —
# uv.lock is the single source of truth. `--locked` fails the build if uv.lock
# has drifted from pyproject.toml, so a forgotten `uv lock` can never ship a
# half-resolved dependency set. `--no-install-project` installs only the
# locked dependencies (the app itself runs via PYTHONPATH, not as a package).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# ---- runtime: minimal image, no build tools ----
FROM python:3.12-slim AS runtime

# Copy only the pre-built venv — no uv, no pip, no build tools in the final image
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

# Non-root user
RUN useradd --system --uid 1001 --no-create-home appuser && \
    apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --chown=appuser:appuser . server/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -f http://localhost:8000/api/docs || exit 1

CMD ["uvicorn", "server.index:app", "--host", "0.0.0.0", "--port", "8000"]

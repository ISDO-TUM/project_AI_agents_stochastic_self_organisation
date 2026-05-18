# ─── Stage 1: Python venv via uv ────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:0.11.7 AS uv

FROM python:3.12-slim AS api-builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /build
COPY api/requirements.txt .
RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv --no-cache -r requirements.txt

# ─── Stage 2a: pnpm deps ─────────────────────────────────────────────────────
FROM node:22-alpine AS node-base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

FROM node-base AS node-deps
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY app/package.json ./app/package.json

# Allow build scripts to run so sharp compiles successfully
RUN pnpm install --frozen-lockfile --config.dangerously-allow-all-builds=true

# ─── Stage 2b: Next.js standalone build ──────────────────────────────────────
FROM node-base AS node-builder
WORKDIR /workspace
COPY --from=node-deps /workspace/node_modules ./node_modules
COPY package.json pnpm-workspace.yaml ./
COPY app/ ./app/
# Baked in at build time — matches the API's internal port in the combined container
ENV INTERNAL_API_URL=http://localhost:8000
RUN pnpm --filter app build

# ─── Stage 3: Combined runtime ───────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg2 supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# API — mirrors the structure from api/Dockerfile (PYTHONPATH=/app → api.index)
COPY --from=api-builder /opt/venv /opt/venv
WORKDIR /app
COPY api/ api/

# Next.js standalone output
WORKDIR /app/web
COPY --from=node-builder /workspace/app/.next/standalone ./
COPY --from=node-builder /workspace/app/.next/static ./.next/static

COPY hf/supervisord.conf /etc/supervisord.conf

ENV PATH="/opt/venv/bin:$PATH" \
    VIRTUAL_ENV="/opt/venv" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app"

# HuggingFace Spaces expects port 7860
EXPOSE 7860

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisord.conf"]

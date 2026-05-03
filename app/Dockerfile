# ---- base: pnpm toolchain (build stages only) ----
FROM node:22-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

# ---- deps: install node_modules ----
FROM base AS deps
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY app/package.json ./app/package.json
RUN pnpm install --frozen-lockfile

# ---- builder: compile Next.js standalone output ----
FROM base AS builder
WORKDIR /workspace
COPY --from=deps /workspace/node_modules ./node_modules
COPY package.json pnpm-workspace.yaml ./
COPY app/ ./app/
RUN pnpm --filter app build

# ---- runtime: minimal — no pnpm, no node_modules, just the standalone server ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0" \
    NEXT_TELEMETRY_DISABLED=1

# Non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /workspace/app/public ./public
COPY --from=builder --chown=nextjs:nodejs /workspace/app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /workspace/app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD wget -qO- http://localhost:3000 || exit 1

CMD ["node", "app/server.js"]

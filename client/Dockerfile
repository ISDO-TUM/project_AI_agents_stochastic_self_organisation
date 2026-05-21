# ---- base: pnpm toolchain (build stages only) ----
FROM node:22-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# ---- deps: install node_modules ----
FROM base AS deps
WORKDIR /workspace
# Copy monorepo config and client package.json
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY client/package.json ./client/package.json
RUN pnpm install --frozen-lockfile

# ---- builder: compile Next.js standalone output ----
FROM base AS builder
WORKDIR /workspace
COPY --from=deps /workspace/node_modules ./node_modules
COPY package.json pnpm-workspace.yaml ./
COPY client/ ./client/
# Note: Ensure "app" is the actual package name inside client/package.json.
# If the name is "client", change this to: pnpm --filter client build
RUN pnpm --filter app build

# ---- runtime: minimal standalone server ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0" \
    NEXT_TELEMETRY_DISABLED=1

# Non-root user setup
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# 1. Copy the entire standalone structure to preserve monorepo paths
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/standalone ./

# 2. Copy static files to the correct subfolder path
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/static ./client/.next/static

# 3. (Optional but recommended) Copy the public folder if you have one
# COPY --from=builder --chown=nextjs:nodejs /workspace/client/public ./client/public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD wget -qO- http://localhost:3000 || exit 1

# Run the server from its correct monorepo location
CMD ["node", "client/server.js"]

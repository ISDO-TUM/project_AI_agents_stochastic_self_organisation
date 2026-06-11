# ---- base: pnpm toolchain (build stages only) ----
FROM node:22-alpine AS base
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# ---- deps: install node_modules ----
FROM base AS deps
WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY client/package.json ./client/package.json
RUN pnpm install --frozen-lockfile

# ---- builder: compile Next.js standalone output ----
FROM base AS builder
WORKDIR /workspace
COPY --from=deps /workspace/node_modules ./node_modules
COPY package.json pnpm-workspace.yaml ./
COPY client/ ./client/

# Catch the variable from Railway's build environment
ARG INTERNAL_API_URL
# Expose it to the Next.js build process
ENV INTERNAL_API_URL=$INTERNAL_API_URL

RUN pnpm --filter app build

# ---- runtime: minimal standalone server ----
FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME="0.0.0.0" \
    NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy the standalone structure
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/standalone ./

# Copy static files to the correct subfolder
COPY --from=builder --chown=nextjs:nodejs /workspace/client/.next/static ./client/.next/static

# Standalone output omits `public/` — copy it next to server.js so Next.js can serve it
COPY --from=builder --chown=nextjs:nodejs /workspace/client/public ./client/public

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD wget -qO- http://localhost:3000 || exit 1

# Run from the correct monorepo path
CMD ["node", "client/server.js"]

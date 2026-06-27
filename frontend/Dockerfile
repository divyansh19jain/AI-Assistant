# syntax=docker/dockerfile:1
# Multi-stage build for the Next.js 14 frontend (standalone output).

# ---- deps: install node_modules from the lockfile ----
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: hot-reload target used by docker-compose.dev.yml ----
FROM node:20-slim AS dev
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]

# ---- builder: produce the standalone production bundle ----
FROM node:20-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at build time. Leave
# NEXT_PUBLIC_API_BASE_URL empty to call the backend same-origin through the Next
# /api proxy (recommended); set it to an absolute URL for a split-domain setup.
ARG NEXT_PUBLIC_API_BASE_URL=""
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
# Internal address the Next server proxies /api/* to (server-side, same network).
ARG BACKEND_INTERNAL_URL="http://backend:8000"
ENV BACKEND_INTERNAL_URL=$BACKEND_INTERNAL_URL

RUN npm run build

# ---- runner: minimal production image ----
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    BACKEND_INTERNAL_URL="http://backend:8000"

RUN useradd --create-home --uid 10001 nextjs
USER nextjs

# Standalone server + static assets (no public/ dir in this project).
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]

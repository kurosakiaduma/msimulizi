# ── Msimulizi frontend container image ──
# Context: repository root (see azure.yaml `context: ../`). Build with:
#   docker build -f frontend/Dockerfile -t msimulizi-frontend .
#
# NEXT_PUBLIC_* values are inlined at build time. In production the runtime
# `/api/config` route reads BACKEND_URL / WS_URL instead, so one image works
# across environments.

FROM node:24-alpine AS base

# ─── Dependencies ───
FROM base AS deps
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

# ─── Build ───
FROM base AS builder
WORKDIR /app/frontend
COPY --from=deps /app/frontend/node_modules ./node_modules
COPY frontend/ ./

# Build-time defaults are for local/standalone use only. Production reads the
# runtime env vars from the route handler.
ARG NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_BACKEND_URL=$NEXT_PUBLIC_BACKEND_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# ─── Run ───
FROM base AS runner
WORKDIR /app/frontend
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Next.js standalone output is not enabled in next.config.ts, so serve from the
# .next directory produced by `npm run build` (next start).
COPY --from=builder /app/frontend/.next ./.next
COPY --from=builder /app/frontend/public ./public
COPY --from=builder /app/frontend/node_modules ./node_modules
COPY --from=builder /app/frontend/package.json ./package.json
COPY --from=builder /app/frontend/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "start"]

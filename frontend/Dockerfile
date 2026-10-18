# ── Msimulizi frontend container image ──
# Context: repository root; this Dockerfile lives in frontend/ and builds the
# Next.js 16 App Router site, then serves it with `next start` on port 3000.
#
# NEXT_PUBLIC_* values are inlined at build time.  Provide them as Container App
# environment variables (azd wires the backend's default domain into
# NEXT_PUBLIC_BACKEND_URL / NEXT_PUBLIC_WS_URL / NEXT_PUBLIC_API_BASE).

FROM node:24-alpine AS base

# ─── Dependencies ───
FROM base AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# ─── Build ───
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
WORKDIR /app/frontend

# Inlined at build time (Next.js embeds NEXT_PUBLIC_* into the client bundle).
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

# Next.js standalone output is not enabled in next.config.ts, so we serve from
# the .next directory produced by `npm run build` (next start).
COPY --from=builder /app/frontend/.next ./.next
COPY --from=builder /app/frontend/public ./public
COPY --from=builder /app/frontend/node_modules ./node_modules
COPY --from=builder /app/frontend/package.json ./package.json
COPY --from=builder /app/frontend/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "start"]

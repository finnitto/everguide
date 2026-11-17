# syntax=docker/dockerfile:1.7
FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package*.json ./
# Docker Desktop on some Windows/WSL2 setups requires its internal proxy for
# outbound HTTPS. Keep proxy settings build-time-only; never copy them to runtime.
ARG HTTP_PROXY
ARG HTTPS_PROXY
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    if [ -n "${HTTPS_PROXY:-}" ] || [ -n "${HTTP_PROXY:-}" ]; then \
      npm_config_proxy="${HTTP_PROXY:-$HTTPS_PROXY}" \
      npm_config_https_proxy="${HTTPS_PROXY:-$HTTP_PROXY}" \
      npm install; \
    else \
      npm install; \
    fi

FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Next standalone server uses HOSTNAME; Docker otherwise injects the container ID.
# Bind explicitly to all interfaces so loopback health checks and published ports work.
ENV HOSTNAME=0.0.0.0
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
ENV PORT=3000
CMD ["node", "server.js"]

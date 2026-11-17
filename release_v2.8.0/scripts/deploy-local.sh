#!/usr/bin/env bash
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
echo "===== EVERGUIDE LOCAL DEPLOYMENT ====="
command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker CLI not found." >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: Docker engine is not running. Start Docker Desktop." >&2; exit 1; }
if [[ ! -f .env ]]; then cp .env.example .env; echo "Created .env from .env.example."; fi
docker compose config --quiet
docker compose up -d --build
api_port="${API_PORT:-8000}"
web_port="${WEB_PORT:-3000}"
echo "Waiting for API readiness..."
api_ready=0
for attempt in $(seq 1 60); do
  if curl --silent --fail "http://localhost:${api_port}/health/ready" >/dev/null 2>&1; then api_ready=1; break; fi
  sleep 3
done
if [[ "$api_ready" -ne 1 ]]; then docker compose logs --tail=100 api db redis >&2; echo "ERROR: API did not become ready." >&2; exit 1; fi
echo "Waiting for website..."
web_ready=0
for attempt in $(seq 1 60); do
  if curl --silent --fail "http://localhost:${web_port}" >/dev/null 2>&1; then web_ready=1; break; fi
  sleep 3
done
if [[ "$web_ready" -ne 1 ]]; then docker compose logs --tail=100 web >&2; echo "ERROR: Website did not become ready." >&2; exit 1; fi
docker compose ps
echo ""
echo "EVERGUIDE IS RUNNING"
echo "Website:    http://localhost:${web_port}"
echo "Admin:      http://localhost:${web_port}/admin"
echo "API:        http://localhost:${api_port}"
echo "API docs:   http://localhost:${api_port}/docs"
echo "API health: http://localhost:${api_port}/health/ready"

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"
PROJECT="everguide-validation-$BASHPID"
ENV_FILE="$ROOT_DIR/.env.validation.$BASHPID"

command -v docker >/dev/null 2>&1 || { echo "Docker is required." >&2; exit 1; }
docker compose version >/dev/null

# Capture an optional local build proxy, then explicitly control every
# Compose interpolation variable so host exports and the developer's .env
# cannot inject credentials or point this stack at the normal database.
if [[ "${CI:-}" == "true" ]]; then
  BUILD_HTTP_PROXY="${VALIDATION_HTTP_PROXY:-}"
  BUILD_HTTPS_PROXY="${VALIDATION_HTTPS_PROXY:-}"
else
  BUILD_HTTP_PROXY="${VALIDATION_HTTP_PROXY:-${HTTP_PROXY:-http://http.docker.internal:3128}}"
  BUILD_HTTPS_PROXY="${VALIDATION_HTTPS_PROXY:-${HTTPS_PROXY:-http://http.docker.internal:3128}}"
fi

DB_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
APP_VERSION="$(python -c 'from pathlib import Path; print(Path("VERSION").read_text(encoding="utf-8").strip())' )"
API_PORT="$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
WEB_PORT="$(python -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"

cat > "$ENV_FILE" <<EOF
APP_ENV=test
APP_NAME=Everguide
APP_VERSION=$APP_VERSION
POSTGRES_DB=everguide_validation
POSTGRES_USER=everguide_validation
POSTGRES_PASSWORD=$DB_PASSWORD
API_PORT=$API_PORT
WEB_PORT=$WEB_PORT
NEXT_PUBLIC_API_BASE_URL=http://localhost:$API_PORT
COMPANIES_HOUSE_API_KEY=
GOOGLE_PLACES_API_KEY=
BRAVE_SEARCH_API_KEY=
SEARCH_PROVIDER=brave
AUTO_APPROVE_PROVIDERS=false
AUTO_APPROVAL_MIN_CONFIDENCE=0.94
OVERTURE_AUTO_PROCESS=false
OVERTURE_FEED_ENABLED=false
OVERTURE_SCHEDULED_TASKS_ENABLED=false
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=50
IDENTITY_REVIEW_CREDENTIALS={}
ONS_BOUNDARY_CACHE_TTL_HOURS=720
EOF
chmod 600 "$ENV_FILE" 2>/dev/null || true

export APP_ENV=test APP_NAME=Everguide APP_VERSION
export POSTGRES_DB=everguide_validation POSTGRES_USER=everguide_validation POSTGRES_PASSWORD="$DB_PASSWORD"
export API_PORT WEB_PORT NEXT_PUBLIC_API_BASE_URL="http://localhost:$API_PORT"
export COMPANIES_HOUSE_API_KEY= GOOGLE_PLACES_API_KEY= BRAVE_SEARCH_API_KEY=
export SEARCH_PROVIDER=brave AUTO_APPROVE_PROVIDERS=false AUTO_APPROVAL_MIN_CONFIDENCE=0.94
export OVERTURE_AUTO_PROCESS=false OVERTURE_FEED_ENABLED=false OVERTURE_SCHEDULED_TASKS_ENABLED=false
export OVERTURE_FEED_DAILY_HOUR=4 OVERTURE_FEED_DAILY_MINUTE=30 OVERTURE_FEED_BATCH_SIZE=50
export IDENTITY_REVIEW_CREDENTIALS='{}' ONS_BOUNDARY_CACHE_TTL_HOURS=720
export REDIS_URL=redis://redis:6379/0 CELERY_BROKER_URL=redis://redis:6379/1 CELERY_RESULT_BACKEND=redis://redis:6379/2
export COMPANIES_HOUSE_SIC_CODES=96030
export HTTP_PROXY="$BUILD_HTTP_PROXY" HTTPS_PROXY="$BUILD_HTTPS_PROXY"

dc() {
  docker compose --project-name "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  status=$?
  trap - EXIT ERR
  dc down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -f "$ENV_FILE"
  exit "$status"
}
on_error() {
  status=$?
  trap - ERR
  echo "Docker validation failed; collecting disposable environment logs." >&2
  dc logs --no-color --tail=120 >&2 || true
  exit "$status"
}
trap cleanup EXIT
trap on_error ERR

echo "[CHECK] Build and start isolated API, worker, Beat, web, PostgreSQL and Redis"
dc up --build --detach --wait --wait-timeout 240

echo "[CHECK] API readiness and release version"
dc exec -T api python -c 'import json, urllib.request; d=json.load(urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=5)); assert d["status"] == "ready", d; h=json.load(urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5)); assert h["version"] == __import__("os").environ["APP_VERSION"], h; print(h); print(d)'

echo "[CHECK] Complete migration chain reached 0021"
MIGRATION="$(dc exec -T api alembic current)"
printf '%s\n' "$MIGRATION"
printf '%s' "$MIGRATION" | grep -q '0021_overture_company_links' || {
  echo "Expected migration 0021_overture_company_links to be current." >&2
  exit 1
}

echo "[CHECK] Admin route responds from the new web container"
dc exec -T web node -e 'fetch("http://127.0.0.1:3000/admin").then(r=>{console.log("Admin HTTP",r.status); if(r.status!==200) process.exit(1)}).catch(e=>{console.error(e);process.exit(1)})'

echo "[CHECK] Beat schedule remains disabled"
dc exec -T beat python -c 'from app.celery_app import celery_app; schedule=celery_app.conf.beat_schedule; print(schedule); assert schedule == {}, "Scheduled tasks must remain disabled during validation"'

echo "[CHECK] Worker is online and has no active, reserved or ETA tasks"
dc exec -T worker celery -A app.celery_app:celery_app inspect ping --timeout=10
ACTIVE="$(dc exec -T worker celery -A app.celery_app:celery_app inspect active --timeout=10)"
RESERVED="$(dc exec -T worker celery -A app.celery_app:celery_app inspect reserved --timeout=10)"
SCHEDULED="$(dc exec -T worker celery -A app.celery_app:celery_app inspect scheduled --timeout=10)"
printf '%s\n' "$ACTIVE"
printf '%s\n' "$RESERVED"
printf '%s\n' "$SCHEDULED"
printf '%s' "$ACTIVE" | grep -q -- '- empty -' || { echo "Unexpected active worker tasks." >&2; exit 1; }
printf '%s' "$RESERVED" | grep -q -- '- empty -' || { echo "Unexpected reserved worker tasks." >&2; exit 1; }
printf '%s' "$SCHEDULED" | grep -q -- '- empty -' || { echo "Unexpected ETA-scheduled worker tasks." >&2; exit 1; }

echo "[PASS] Disposable Docker stack passed API, migration, admin, worker and Beat checks."
echo "[INFO] The isolated project, containers, network and database volumes will now be removed."

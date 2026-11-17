#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-quick}"

log() { printf '\n[%s] %s\n' "$1" "$2"; }
fail() { log FAIL "$1"; exit 1; }

case "$MODE" in
  quick|full) ;;
  *) fail "Usage: bash scripts/validate.sh [quick|full]" ;;
esac

for command_name in python npm; do
  command -v "$command_name" >/dev/null 2>&1 || fail "Required command not found: $command_name"
done

cd "$ROOT_DIR"

log CHECK "Release version consistency"
VERSION="$(tr -d '\r\n' < VERSION)"
MANIFEST_VERSION="$(python -c 'import json; print(json.load(open("RELEASE-MANIFEST.json", encoding="utf-8"))["version"])')"
WEB_VERSION="$(python -c 'import json; print(json.load(open("apps/web/package.json", encoding="utf-8"))["version"])')"
ENV_EXAMPLE_VERSION="$(sed -n '/^APP_VERSION=/s/^APP_VERSION=//p' .env.example | head -n 1)"
[[ "$VERSION" == "$MANIFEST_VERSION" ]] || fail "VERSION ($VERSION) does not match RELEASE-MANIFEST.json ($MANIFEST_VERSION)"
[[ "$VERSION" == "$WEB_VERSION" ]] || fail "VERSION ($VERSION) does not match web package version ($WEB_VERSION)"
[[ "$VERSION" == "$ENV_EXAMPLE_VERSION" ]] || fail "VERSION ($VERSION) does not match .env.example ($ENV_EXAMPLE_VERSION)"
log PASS "All release version files agree: $VERSION"

log CHECK "Reviewer credentials are forwarded to the API service"
grep -Fq 'IDENTITY_REVIEW_CREDENTIALS: ${IDENTITY_REVIEW_CREDENTIALS:-}' "$ROOT_DIR/docker-compose.yml" || fail "docker-compose.yml must pass the reviewer credential map to the API container"
log PASS "Reviewer credential map is forwarded to the API container"

log CHECK "Shell script syntax"
bash -n "$ROOT_DIR/scripts/validate.sh"
bash -n "$ROOT_DIR/scripts/validate-docker.sh"
log PASS "Validation scripts have valid Bash syntax"

log CHECK "Python compile check"
(
  cd apps/api
  python -m compileall -q app migrations
)
log PASS "Python application and migration sources compile"

log CHECK "Full API test suite"
(
  cd apps/api
  python -m pytest -q
)
log PASS "API test suite"

log CHECK "Frontend ESLint"
(
  cd apps/web
  npm run lint
)
log PASS "Frontend lint"

log CHECK "Frontend TypeScript"
(
  cd apps/web
  npx --no-install tsc --noEmit
)
log PASS "Frontend TypeScript"

if [[ "$MODE" == "full" ]]; then
  log CHECK "Frontend production build"
  (
    cd apps/web
    npm run build
  )
  log PASS "Frontend production build"

  log CHECK "Isolated Docker integration validation"
  bash "$ROOT_DIR/scripts/validate-docker.sh"
  log PASS "Isolated Docker integration validation"
fi

log PASS "Everguide $MODE validation completed"

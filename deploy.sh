#!/usr/bin/env bash
# Deploy Neo-Label on the VPS.
# Pulls latest code, rebuilds, restarts, and health-checks.
#
# Usage:
#   ./deploy.sh                # pull + build + up
#   ./deploy.sh --no-pull      # skip git pull (deploy what's already checked out)
#   BRANCH=staging ./deploy.sh # deploy a different branch

set -euo pipefail

cd "$(dirname "$0")"

BRANCH="${BRANCH:-main}"
PROJECT="neo-label-prod"
ENV_FILE=".env.prod"
COMPOSE_FILE="docker-compose.prod.yml"
PULL=1

for arg in "$@"; do
  case "$arg" in
    --no-pull) PULL=0 ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE (copy .env.prod.example and fill in)" >&2; exit 1; }
[[ -f "seed_users.json" ]] || { echo "missing seed_users.json (copy seed_users.example.json)" >&2; exit 1; }

compose() {
  docker compose -p "$PROJECT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

if [[ "$PULL" -eq 1 ]]; then
  echo "==> git pull origin $BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git reset --hard "origin/$BRANCH"
fi

echo "==> docker compose build + up"
compose up --build -d

echo "==> waiting for backend health..."
HEALTH_PY='import sys,urllib.request; sys.exit(0 if urllib.request.urlopen("http://localhost:8000/health",timeout=2).status==200 else 1)'
for i in {1..30}; do
  if compose exec -T backend python -c "$HEALTH_PY" >/dev/null 2>&1; then
    echo "    backend OK"
    break
  fi
  [[ "$i" -eq 30 ]] && { echo "backend did not become healthy" >&2; compose logs --tail=50 backend; exit 1; }
  sleep 2
done

FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' "$ENV_FILE" | cut -d= -f2)"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"

if curl -sf -o /dev/null "http://127.0.0.1:${FRONTEND_PORT}/"; then
  echo "    frontend OK on 127.0.0.1:${FRONTEND_PORT}"
else
  echo "frontend not responding on 127.0.0.1:${FRONTEND_PORT}" >&2
  compose logs --tail=50 frontend
  exit 1
fi

echo
echo "==> status"
compose ps
echo
echo "deploy done. commit: $(git rev-parse --short HEAD)"

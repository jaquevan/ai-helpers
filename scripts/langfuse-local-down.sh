#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/docker/langfuse"
ENV_FILE="$COMPOSE_DIR/.env"

COMPOSE_BIN=()

if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
  COMPOSE_BIN=(podman compose)
elif command -v podman-compose >/dev/null 2>&1; then
  COMPOSE_BIN=(podman-compose)
elif command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  COMPOSE_BIN=(docker compose)
elif [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
  export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
  COMPOSE_BIN=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_BIN=(docker-compose)
else
  echo "No compose runtime found (podman/docker)" >&2
  exit 1
fi

cd "$COMPOSE_DIR"
"${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" down
echo "Langfuse local stack stopped."

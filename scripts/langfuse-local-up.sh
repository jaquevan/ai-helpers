#!/usr/bin/env bash
# Start Langfuse v4 stack locally via Docker/Podman Compose (http://localhost:3100).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/docker/langfuse"
ENV_FILE="$COMPOSE_DIR/.env"
EXAMPLE_FILE="$COMPOSE_DIR/env.example"
LOCAL_PORT="${LANGFUSE_LOCAL_PORT:-3100}"

COMPOSE_BACKEND=""
COMPOSE_BIN=()

ensure_podman_machine() {
  if podman info >/dev/null 2>&1; then
    return 0
  fi
  if ! podman machine inspect podman-machine-default >/dev/null 2>&1; then
    echo "==> Initializing Podman machine (first run may take a few minutes)"
    podman machine init
  fi
  local state
  state="$(podman machine list --format '{{.LastUp}}' 2>/dev/null | head -1 || true)"
  if [ "$state" = "Currently starting" ]; then
    echo "==> Podman machine is starting — waiting..."
    for _ in $(seq 1 60); do
      podman info >/dev/null 2>&1 && return 0
      sleep 5
    done
    echo "Podman machine stuck starting. Try: podman machine stop && podman machine start" >&2
    exit 1
  fi
  echo "==> Starting Podman machine"
  podman machine start
}

find_compose() {
  if command -v podman >/dev/null 2>&1; then
    ensure_podman_machine
    if podman compose version >/dev/null 2>&1; then
      COMPOSE_BACKEND=podman
      COMPOSE_BIN=(podman compose)
      return 0
    fi
    if command -v podman-compose >/dev/null 2>&1; then
      COMPOSE_BACKEND=podman
      COMPOSE_BIN=(podman-compose)
      return 0
    fi
  fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_BACKEND=docker
    COMPOSE_BIN=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_BACKEND=docker
    COMPOSE_BIN=(docker-compose)
    return 0
  fi
  if [ -x /Applications/Docker.app/Contents/Resources/bin/docker ]; then
    export PATH="/Applications/Docker.app/Contents/Resources/bin:$PATH"
    if docker compose version >/dev/null 2>&1; then
      COMPOSE_BACKEND=docker
      COMPOSE_BIN=(docker compose)
      return 0
    fi
  fi
  return 1
}

if ! find_compose; then
  cat <<'EOF' >&2
Container runtime not found. Install one of:
  - Podman: brew install podman && podman machine init && podman machine start
  - Docker Desktop: https://docs.docker.com/desktop/install/mac-install/
  - OrbStack: https://orbstack.dev/download

Then re-run: make langfuse-local-up
EOF
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "==> Creating $ENV_FILE from env.example"
  cp "$EXAMPLE_FILE" "$ENV_FILE"
  if command -v openssl >/dev/null 2>&1; then
    ENC_KEY="$(openssl rand -hex 32)"
    NEXT_SECRET="$(openssl rand -hex 32)"
    SALT_VAL="$(openssl rand -hex 16)"
    if sed --version 2>/dev/null | grep -q GNU; then
      sed -i "s/^ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${ENC_KEY}/" "$ENV_FILE"
      sed -i "s/^NEXTAUTH_SECRET=.*/NEXTAUTH_SECRET=${NEXT_SECRET}/" "$ENV_FILE"
      sed -i "s/^SALT=.*/SALT=${SALT_VAL}/" "$ENV_FILE"
    else
      sed -i '' "s/^ENCRYPTION_KEY=.*/ENCRYPTION_KEY=${ENC_KEY}/" "$ENV_FILE"
      sed -i '' "s/^NEXTAUTH_SECRET=.*/NEXTAUTH_SECRET=${NEXT_SECRET}/" "$ENV_FILE"
      sed -i '' "s/^SALT=.*/SALT=${SALT_VAL}/" "$ENV_FILE"
    fi
  fi
fi

echo "==> Starting Langfuse via ${COMPOSE_BACKEND} compose (first pull may take 2–3 minutes)"
cd "$COMPOSE_DIR"
LANGFUSE_LOCAL_PORT="$LOCAL_PORT" NEXTAUTH_URL="http://localhost:${LOCAL_PORT}" \
  "${COMPOSE_BIN[@]}" --env-file "$ENV_FILE" up -d

echo "==> Waiting for health at http://localhost:${LOCAL_PORT}/api/public/health"
for i in $(seq 1 60); do
  if curl -sf "http://localhost:${LOCAL_PORT}/api/public/health" >/dev/null 2>&1; then
    echo "Langfuse is up."
    echo ""
    echo "UI:      http://localhost:3000"
    echo "Login:   $(grep LANGFUSE_INIT_USER_EMAIL "$ENV_FILE" | cut -d= -f2) / $(grep LANGFUSE_INIT_USER_PASSWORD "$ENV_FILE" | cut -d= -f2)"
    echo "SDK env: eval \"\$(make langfuse-local-env)\""
    exit 0
  fi
  sleep 5
done

echo "Health check timed out. Check: ${COMPOSE_BIN[*]} -f $COMPOSE_DIR/docker-compose.yml logs langfuse-web" >&2
exit 1

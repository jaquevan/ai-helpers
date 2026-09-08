#!/usr/bin/env bash
# Source this from the ai-helpers repo root:
#   cd ~/Desktop/ai-helpers && source scripts/cluster-setup-env.sh
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="${REPO_ROOT}/.local/node/bin:${PATH}"

if ! command -v oc >/dev/null 2>&1; then
  echo "ERROR: oc not found. Expected at ${REPO_ROOT}/.local/node/bin/oc"
  return 1 2>/dev/null || exit 1
fi

cd "$REPO_ROOT"
echo "Repo:  $REPO_ROOT"
echo "oc:    $(which oc)"
echo "User:  $(oc whoami 2>/dev/null || echo 'not logged in — run: oc login https://api.uxdpoc7.9hji.p3.openshiftapps.com:443')"

#!/usr/bin/env bash
# Shared, gitignored evaluation environment for every worktree of this repository.
# This file must be sourced so its exports reach the caller.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Source this helper: source scripts/eval-env.sh" >&2
  exit 2
fi

_uxd_eval_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_uxd_eval_root="$(cd "${_uxd_eval_script_dir}/.." && pwd)"
_uxd_eval_primary="$(git -C "${_uxd_eval_root}" worktree list --porcelain 2>/dev/null | awk '/^worktree / { sub(/^worktree /, ""); print; exit }')"

if [[ -n "${UXD_EVAL_ENV_FILE:-}" ]]; then
  _uxd_eval_env_file="${UXD_EVAL_ENV_FILE}"
elif [[ -n "${_uxd_eval_primary}" && -f "${_uxd_eval_primary}/.env.local" ]]; then
  _uxd_eval_env_file="${_uxd_eval_primary}/.env.local"
else
  _uxd_eval_env_file="${_uxd_eval_root}/.env.local"
fi

if [[ ! -f "${_uxd_eval_env_file}" ]]; then
  echo "Eval credentials are not configured. Create .env.local in this repository's primary worktree, or set UXD_EVAL_ENV_FILE to an explicit secure file." >&2
  return 2
fi

set -a
# shellcheck disable=SC1090
source "${_uxd_eval_env_file}"
set +a

# LANGFUSE_BASE_URL was used by an early local setup. Preserve it as a
# non-breaking fallback while the evaluator standardizes on LANGFUSE_HOST.
if [[ -z "${LANGFUSE_HOST:-}" && -n "${LANGFUSE_BASE_URL:-}" ]]; then
  export LANGFUSE_HOST="${LANGFUSE_BASE_URL}"
  _uxd_eval_langfuse_alias=1
fi

# New worktrees do not contain ignored dependencies. Reuse only dependencies
# from the same repository's registered primary worktree; never search home
# directories or external plugin caches.
if [[ -n "${_uxd_eval_primary}" && -d "${_uxd_eval_primary}/.venv/bin" ]]; then
  export PATH="${_uxd_eval_primary}/.venv/bin:${PATH}"
fi
_uxd_eval_node_modules="${_uxd_eval_primary}/plugins/uxd-prototype/skills/uxd-prototype-evaluate/node_modules"
if [[ -n "${_uxd_eval_primary}" && -d "${_uxd_eval_node_modules}" ]]; then
  export NODE_PATH="${_uxd_eval_node_modules}${NODE_PATH:+:${NODE_PATH}}"
fi

export UXD_EVAL_ENV_SOURCE="${_uxd_eval_env_file}"
export UXD_EVAL_PRIMARY_WORKTREE="${_uxd_eval_primary:-${_uxd_eval_root}}"

if [[ "${EVAL_ENV_QUIET:-0}" != "1" ]]; then
  echo "Loaded eval credentials from the primary worktree .env.local."
  if [[ "${_uxd_eval_langfuse_alias:-0}" == "1" ]]; then
    echo "Using LANGFUSE_BASE_URL as a compatibility alias for LANGFUSE_HOST."
  fi
fi

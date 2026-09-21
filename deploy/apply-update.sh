#!/usr/bin/env bash
# Explicitly fast-forward to release/3.x and synchronize the locked environment.

set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

emit() {
  printf 'state=%s\n' "$1"
  printf 'local=%s\n' "${2:-}"
  printf 'remote=%s\n' "${3:-}"
  [[ -z "${4:-}" ]] || printf 'reason=%s\n' "$4"
}

exec 9>"$project_dir/.git/digitalframe-update.lock"
if ! flock -n 9; then
  emit error "" "" busy
  exit 2
fi

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  emit error "$(git rev-parse HEAD)" "" dirty
  exit 2
fi

if ! GIT_TERMINAL_PROMPT=0 \
  GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes" \
  timeout --signal=TERM --kill-after=5s 45s git fetch --quiet origin \
  refs/heads/release/3.x:refs/remotes/origin/release/3.x; then
  emit error "$(git rev-parse HEAD)" "" fetch
  exit 1
fi

local_revision="$(git rev-parse HEAD)"
remote_revision="$(git rev-parse refs/remotes/origin/release/3.x)"
if [[ "$local_revision" == "$remote_revision" ]]; then
  emit current "$local_revision" "$remote_revision"
  exit 0
fi
if ! git merge-base --is-ancestor "$local_revision" "$remote_revision"; then
  emit error "$local_revision" "$remote_revision" diverged
  exit 2
fi

uv_bin="${UV_BIN:-}"
if [[ -z "$uv_bin" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_bin="$HOME/.local/bin/uv"
  else
    emit error "$local_revision" "$remote_revision" uv-missing
    exit 1
  fi
fi

# Prove that the fetched revision has a valid lock and can build its complete
# runtime environment before changing the live checkout. The final sync below
# normally reuses this warmed uv cache.
preflight_root="$(mktemp -d "${TMPDIR:-/tmp}/digitalframe-update.XXXXXX")"
preflight_checkout="$preflight_root/checkout"
cleanup_preflight() {
  if [[ -d "$preflight_checkout" ]]; then
    git worktree remove --force "$preflight_checkout" >/dev/null 2>&1 || true
  fi
  rmdir "$preflight_root" >/dev/null 2>&1 || true
}
trap cleanup_preflight EXIT
if ! git worktree add --quiet --detach "$preflight_checkout" "$remote_revision"; then
  emit error "$local_revision" "$remote_revision" preflight
  exit 1
fi
if ! UV_PROJECT_ENVIRONMENT="$preflight_checkout/.venv" \
  "$uv_bin" sync --project "$preflight_checkout" --locked --no-dev; then
  emit error "$local_revision" "$remote_revision" preflight
  exit 1
fi
cleanup_preflight
trap - EXIT

if ! git merge --ff-only "$remote_revision"; then
  emit error "$local_revision" "$remote_revision" merge
  exit 1
fi
if ! "$uv_bin" sync --locked --no-dev; then
  emit error "$local_revision" "$remote_revision" sync
  exit 1
fi

emit updated "$local_revision" "$remote_revision"

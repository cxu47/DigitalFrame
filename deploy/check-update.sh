#!/usr/bin/env bash
# Fetch release metadata without changing checked-out files.

set -euo pipefail

project_dir="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_dir"

emit() {
  printf 'state=%s\n' "$1"
  printf 'dirty=%s\n' "${2:-0}"
  printf 'local=%s\n' "${3:-}"
  printf 'remote=%s\n' "${4:-}"
  [[ -z "${5:-}" ]] || printf 'reason=%s\n' "$5"
}

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  emit error 0 "" "" repository
  exit 1
fi

if ! GIT_TERMINAL_PROMPT=0 \
  GIT_SSH_COMMAND="ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes" \
  timeout --signal=TERM --kill-after=5s 45s git fetch --quiet origin \
  refs/heads/release/2.x:refs/remotes/origin/release/2.x; then
  emit error 0 "" "" fetch
  exit 1
fi

local_revision="$(git rev-parse HEAD)"
remote_revision="$(git rev-parse refs/remotes/origin/release/2.x)"
dirty=0
[[ -z "$(git status --porcelain --untracked-files=normal)" ]] || dirty=1

if [[ "$local_revision" == "$remote_revision" ]]; then
  state=current
elif git merge-base --is-ancestor "$local_revision" "$remote_revision"; then
  state=available
elif git merge-base --is-ancestor "$remote_revision" "$local_revision"; then
  state=ahead
else
  state=diverged
fi

emit "$state" "$dirty" "$local_revision" "$remote_revision"

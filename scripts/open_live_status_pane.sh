#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL="${1:-2}"
PANE_PERCENT="${PANE_PERCENT:-35}"

WATCH_SCRIPT="${ROOT_DIR}/scripts/watch_live_status.sh"
ROOT_Q="$(printf '%q' "${ROOT_DIR}")"
WATCH_Q="$(printf '%q' "${WATCH_SCRIPT}")"
CMD="cd ${ROOT_Q} && ${WATCH_Q} ${INTERVAL}"

if [[ -n "${TMUX:-}" ]]; then
  tmux split-window -v -p "${PANE_PERCENT}" "${CMD}"
  tmux select-pane -U
  echo "opened tmux status pane (interval=${INTERVAL}s, height=${PANE_PERCENT}%)"
  exit 0
fi

echo "tmux pane unavailable outside tmux; running live status in this shell instead."
exec "${WATCH_SCRIPT}" "${INTERVAL}"

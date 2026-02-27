#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INTERVAL="${1:-2}"

if [[ "${INTERVAL}" == "--once" ]]; then
  exec python3 "${ROOT_DIR}/scripts/render_live_status.py" --root "${ROOT_DIR}"
fi

while true; do
  clear
  python3 "${ROOT_DIR}/scripts/render_live_status.py" --root "${ROOT_DIR}"
  sleep "${INTERVAL}"
done

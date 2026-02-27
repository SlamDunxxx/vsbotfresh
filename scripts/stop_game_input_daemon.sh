#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="runtime/pids/game_input.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "game input daemon not running (no pid file)"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  sleep 0.3
fi

rm -f "$PID_FILE"
echo "game input daemon stopped"

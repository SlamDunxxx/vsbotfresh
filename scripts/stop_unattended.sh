#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PID_FILE="runtime/pids/orchestrator.pid"
if [[ ! -f "$PID_FILE" ]]; then
  echo "no pid file"
  exit 0
fi

pid="$(cat "$PID_FILE")"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid"
  sleep 0.5
fi

rm -f "$PID_FILE"
echo "stopped"

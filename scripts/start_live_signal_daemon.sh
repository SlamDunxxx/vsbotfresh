#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SAVE_PATH="${SAVE_PATH:-}"
OUTPUT_PATH="${OUTPUT_PATH:-}"
INTERVAL="${INTERVAL:-2.0}"
FORCE_MANUAL="${FORCE_MANUAL:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --save-path)
      SAVE_PATH="$2"
      shift 2
      ;;
    --output)
      OUTPUT_PATH="$2"
      shift 2
      ;;
    --interval)
      INTERVAL="$2"
      shift 2
      ;;
    --force-manual)
      FORCE_MANUAL="1"
      shift
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -n "$SAVE_PATH" ]] && [[ "$SAVE_PATH" == *"<steam_id>"* ]]; then
  echo "invalid --save-path: replace <steam_id> with numeric Steam user id" >&2
  exit 2
fi

if [[ "$FORCE_MANUAL" != "1" ]] && launchctl print "gui/$UID/com.vsbotfresh.live-signal" >/dev/null 2>&1; then
  echo "launchd live-signal service is active; skipping manual daemon start."
  echo "use --force-manual to override, or manage services via ./scripts/load_launch_agents.sh"
  exit 0
fi

mkdir -p runtime/logs runtime/pids runtime/live
PID_FILE="runtime/pids/live_signal.pid"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "live signal daemon already running (pid=$old_pid)"
    exit 0
  fi
fi

cmd=(env PYTHONPATH="$ROOT_DIR/src" python3 -m vs_overseer.cli --config ./config/settings.toml live-signal --watch --interval "$INTERVAL")
if [[ -n "$SAVE_PATH" ]]; then
  cmd+=(--save-path "$SAVE_PATH")
fi
if [[ -n "$OUTPUT_PATH" ]]; then
  cmd+=(--output "$OUTPUT_PATH")
fi

nohup "${cmd[@]}" > runtime/logs/live_signal_daemon.log 2>&1 &
echo $! > "$PID_FILE"

sleep 0.3
echo "live_signal_pid=$(cat "$PID_FILE")"

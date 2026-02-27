#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

INTERVAL="${INTERVAL:-0}"
STATUS_OUTPUT="${STATUS_OUTPUT:-}"
FORCE="${FORCE:-0}"
DRY_RUN="${DRY_RUN:-0}"
FORCE_MANUAL="${FORCE_MANUAL:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --interval)
      INTERVAL="$2"
      shift 2
      ;;
    --status-output)
      STATUS_OUTPUT="$2"
      shift 2
      ;;
    --force)
      FORCE="1"
      shift
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
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

if [[ "$FORCE_MANUAL" != "1" ]] && launchctl print "gui/$UID/com.vsbotfresh.game-input" >/dev/null 2>&1; then
  echo "launchd game-input service is active; skipping manual daemon start."
  echo "use --force-manual to override, or manage services via ./scripts/load_launch_agents.sh"
  exit 0
fi

mkdir -p runtime/logs runtime/pids runtime/live
PID_FILE="runtime/pids/game_input.pid"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "game input daemon already running (pid=$old_pid)"
    exit 0
  fi
fi

cmd=(env PYTHONUNBUFFERED=1 PYTHONPATH="$ROOT_DIR/src" python3 -u -m vs_overseer.cli --config ./config/settings.toml game-input --watch)
if [[ "$INTERVAL" != "0" ]]; then
  cmd+=(--interval "$INTERVAL")
fi
if [[ -n "$STATUS_OUTPUT" ]]; then
  cmd+=(--status-output "$STATUS_OUTPUT")
fi
if [[ "$FORCE" == "1" ]]; then
  cmd+=(--force)
fi
if [[ "$DRY_RUN" == "1" ]]; then
  cmd+=(--dry-run)
fi

nohup "${cmd[@]}" > runtime/logs/game_input_daemon.log 2>&1 &
echo $! > "$PID_FILE"

sleep 0.8
pid="$(cat "$PID_FILE")"
if [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
  echo "game input daemon failed to stay alive; tailing log:" >&2
  tail -n 80 runtime/logs/game_input_daemon.log >&2 || true
  rm -f "$PID_FILE"
  exit 1
fi
echo "game_input_pid=$pid"

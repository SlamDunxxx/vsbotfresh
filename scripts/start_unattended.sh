#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MAX_GENERATIONS="${MAX_GENERATIONS:-0}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"
NO_API="${NO_API:-0}"
WITH_LIVE_SIGNAL="${WITH_LIVE_SIGNAL:-0}"
WITH_GAME_INPUT="${WITH_GAME_INPUT:-0}"
LIVE_SAVE_PATH="${LIVE_SAVE_PATH:-}"
FORCE_MANUAL="${FORCE_MANUAL:-0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --max-generations)
      MAX_GENERATIONS="$2"
      shift 2
      ;;
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --no-api)
      NO_API="1"
      shift
      ;;
    --with-live-signal)
      WITH_LIVE_SIGNAL="1"
      shift
      ;;
    --with-game-input)
      WITH_GAME_INPUT="1"
      shift
      ;;
    --save-path)
      LIVE_SAVE_PATH="$2"
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

if [[ -n "$LIVE_SAVE_PATH" ]] && [[ "$LIVE_SAVE_PATH" == *"<steam_id>"* ]]; then
  echo "invalid --save-path: replace <steam_id> with numeric Steam user id" >&2
  exit 2
fi

mkdir -p runtime/logs runtime/pids site/data

launchd_label_active() {
  local label="$1"
  launchctl print "gui/$UID/$label" >/dev/null 2>&1
}

if [[ "$FORCE_MANUAL" != "1" ]] && launchd_label_active "com.vsbotfresh.orchestrator"; then
  echo "launchd orchestrator service is active; skipping manual start."
  echo "use --force-manual to override, or manage services via ./scripts/load_launch_agents.sh"
  exit 0
fi

export CARGO_HOME="$ROOT_DIR/.cargo"
export RUSTUP_HOME="$ROOT_DIR/.rustup"
if [[ -d "$CARGO_HOME/bin" ]]; then
  export PATH="$CARGO_HOME/bin:$PATH"
fi

if [[ -f runtime/pids/orchestrator.pid ]]; then
  old_pid="$(cat runtime/pids/orchestrator.pid || true)"
  if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
    echo "orchestrator already running (pid=${old_pid})"
    exit 0
  fi
fi

if [[ "$WITH_LIVE_SIGNAL" == "1" ]]; then
  if [[ "$FORCE_MANUAL" != "1" ]] && launchd_label_active "com.vsbotfresh.live-signal"; then
    echo "launchd live-signal service is active; skipping manual live-signal daemon start."
  else
    if [[ -n "$LIVE_SAVE_PATH" ]]; then
      ./scripts/start_live_signal_daemon.sh --save-path "$LIVE_SAVE_PATH"
    else
      ./scripts/start_live_signal_daemon.sh
    fi
  fi
fi

if [[ "$WITH_GAME_INPUT" == "1" ]]; then
  if [[ "$FORCE_MANUAL" != "1" ]] && launchd_label_active "com.vsbotfresh.game-input"; then
    echo "launchd game-input service is active; skipping manual game-input daemon start."
  else
    ./scripts/start_game_input_daemon.sh
  fi
fi

cmd=(env PYTHONPATH="$ROOT_DIR/src" python3 -m vs_overseer.cli --config ./config/settings.toml run \
  --max-generations "$MAX_GENERATIONS" \
  --host "$HOST" \
  --port "$PORT")
if [[ "$NO_API" == "1" ]]; then
  cmd+=(--no-api)
fi

nohup "${cmd[@]}" > runtime/logs/orchestrator.log 2>&1 &

echo $! > runtime/pids/orchestrator.pid

sleep 0.3

echo "orchestrator_pid=$(cat runtime/pids/orchestrator.pid)"
echo "health_file=${ROOT_DIR}/site/data/health.json"
echo "summary_file=${ROOT_DIR}/site/data/latest_summary.json"

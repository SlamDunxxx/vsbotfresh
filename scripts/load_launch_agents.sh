#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$HOME/Library/LaunchAgents"
ORCH_PLIST="$DEST_DIR/com.vsbotfresh.orchestrator.plist"
LIVE_PLIST="$DEST_DIR/com.vsbotfresh.live-signal.plist"
INPUT_PLIST="$DEST_DIR/com.vsbotfresh.game-input.plist"

# Ensure launchd takes single ownership before bootstrap.
"$ROOT_DIR/scripts/stop_unattended.sh" >/dev/null 2>&1 || true
"$ROOT_DIR/scripts/stop_live_signal_daemon.sh" >/dev/null 2>&1 || true
"$ROOT_DIR/scripts/stop_game_input_daemon.sh" >/dev/null 2>&1 || true

"$ROOT_DIR/scripts/install_launch_agent.sh"

# Refresh services if already loaded.
launchctl bootout "gui/$UID" "$ORCH_PLIST" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$LIVE_PLIST" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$INPUT_PLIST" >/dev/null 2>&1 || true

launchctl bootstrap "gui/$UID" "$ORCH_PLIST"
launchctl bootstrap "gui/$UID" "$LIVE_PLIST"
launchctl bootstrap "gui/$UID" "$INPUT_PLIST"

launchctl kickstart -k "gui/$UID/com.vsbotfresh.orchestrator"
launchctl kickstart -k "gui/$UID/com.vsbotfresh.live-signal"
launchctl kickstart -k "gui/$UID/com.vsbotfresh.game-input"

echo "launch agents loaded and started"

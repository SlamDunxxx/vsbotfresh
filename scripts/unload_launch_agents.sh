#!/usr/bin/env bash
set -euo pipefail

DEST_DIR="$HOME/Library/LaunchAgents"
ORCH_PLIST="$DEST_DIR/com.vsbotfresh.orchestrator.plist"
LIVE_PLIST="$DEST_DIR/com.vsbotfresh.live-signal.plist"
INPUT_PLIST="$DEST_DIR/com.vsbotfresh.game-input.plist"

launchctl bootout "gui/$UID" "$ORCH_PLIST" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$LIVE_PLIST" >/dev/null 2>&1 || true
launchctl bootout "gui/$UID" "$INPUT_PLIST" >/dev/null 2>&1 || true

echo "launch agents unloaded"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="$HOME/Library/LaunchAgents"
ORCH_TEMPLATE="$ROOT_DIR/launchd/com.vsbotfresh.orchestrator.plist.template"
LIVE_TEMPLATE="$ROOT_DIR/launchd/com.vsbotfresh.live-signal.plist.template"
INPUT_TEMPLATE="$ROOT_DIR/launchd/com.vsbotfresh.game-input.plist.template"
ORCH_DEST="$DEST_DIR/com.vsbotfresh.orchestrator.plist"
LIVE_DEST="$DEST_DIR/com.vsbotfresh.live-signal.plist"
INPUT_DEST="$DEST_DIR/com.vsbotfresh.game-input.plist"

mkdir -p "$DEST_DIR" "$ROOT_DIR/runtime/logs"

sed "s|__ROOT__|$ROOT_DIR|g" "$ORCH_TEMPLATE" > "$ORCH_DEST"
sed "s|__ROOT__|$ROOT_DIR|g" "$LIVE_TEMPLATE" > "$LIVE_DEST"
sed "s|__ROOT__|$ROOT_DIR|g" "$INPUT_TEMPLATE" > "$INPUT_DEST"

echo "wrote: $ORCH_DEST"
echo "wrote: $LIVE_DEST"
echo "wrote: $INPUT_DEST"
echo "load all three with:"
echo "  launchctl load -w '$ORCH_DEST'"
echo "  launchctl load -w '$LIVE_DEST'"
echo "  launchctl load -w '$INPUT_DEST'"
echo "unload all three with:"
echo "  launchctl unload -w '$ORCH_DEST'"
echo "  launchctl unload -w '$LIVE_DEST'"
echo "  launchctl unload -w '$INPUT_DEST'"
echo "or use helpers:"
echo "  ./scripts/load_launch_agents.sh"
echo "  ./scripts/unload_launch_agents.sh"

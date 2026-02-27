#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p runtime/logs runtime/pids
LOG_FILE="runtime/logs/autotune_shadow_watch.log"
PID_FILE="runtime/pids/autotune_shadow_watch.pid"

echo "$$" > "$PID_FILE"

while true; do
  python3 - <<'PY' >> "$LOG_FILE" 2>&1
import json
from datetime import datetime, timezone
from pathlib import Path

row = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "error": "",
}
try:
    health = json.loads(Path("site/data/health.json").read_text(encoding="utf-8"))
    summary = json.loads(Path("site/data/latest_summary.json").read_text(encoding="utf-8"))
    auto_h = health.get("autotune") or {}
    auto_s = summary.get("autotune") or {}

    row.update(
        {
            "generation": health.get("generation"),
            "shadow_ready": auto_h.get("shadow_ready"),
            "last_action": auto_h.get("last_action"),
            "last_decision_at": auto_h.get("last_decision_at"),
            "cooldown_remaining_seconds": auto_h.get("cooldown_remaining_seconds"),
            "cpu_normalized_usage": (auto_h.get("cpu_snapshot") or {}).get("normalized_usage"),
            "summary_action": auto_s.get("action"),
            "summary_reason": auto_s.get("reason"),
            "guardrail_state": auto_s.get("guardrail_state"),
        }
    )
except Exception as exc:  # noqa: BLE001
    row["error"] = str(exc)

print(json.dumps(row, separators=(",", ":")))
PY
  sleep 60
done

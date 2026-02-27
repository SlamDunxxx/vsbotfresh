#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${ROOT_DIR}/runtime/logs/overseer_update_5m.log"

mkdir -p "${ROOT_DIR}/runtime/logs"

while true; do
  python3 - "${ROOT_DIR}" <<'PY' >> "${LOG_FILE}" 2>&1
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


root = Path(sys.argv[1])


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


health = read_json(root / "site/data/health.json")
summary = read_json(root / "site/data/latest_summary.json")
signal = read_json(root / "runtime/live/memory_signal.json")

payload = {
    "ts": datetime.now(timezone.utc).isoformat(),
    "stack": {
        "state": health.get("state"),
        "mode": health.get("mode"),
        "generation": health.get("generation"),
        "sim_backend": health.get("sim_backend"),
        "safe_pause": health.get("safe_pause"),
        "recoveries_30m": health.get("recoveries_30m"),
        "active_policy_id": health.get("active_policy_id"),
    },
    "training": {
        "promotion_state": summary.get("promotion_state"),
        "decision_reason": (summary.get("decision") or {}).get("reason"),
        "improvement": (summary.get("decision") or {}).get("improvement"),
        "stability_regression": (summary.get("decision") or {}).get("stability_regression"),
        "baseline_live_objective_rate": (summary.get("baseline_live") or {}).get("objective_rate"),
        "candidate_live_objective_rate": (summary.get("candidate_live") or {}).get("objective_rate"),
        "baseline_live_stability_rate": (summary.get("baseline_live") or {}).get("stability_rate"),
        "candidate_live_stability_rate": (summary.get("candidate_live") or {}).get("stability_rate"),
    },
    "goal_progress": {
        "objective_hit": summary.get("objective_hit"),
        "signal_blocked": signal.get("blocked"),
        "objective_hint": signal.get("objective_hint"),
        "stability_hint": signal.get("stability_hint"),
        "signal_confidence": signal.get("confidence"),
    },
}

print(json.dumps(payload, separators=(",", ":")))
PY

  sleep 300
done

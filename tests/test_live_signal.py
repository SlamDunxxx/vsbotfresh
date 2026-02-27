from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from vs_overseer.config import load_config
from vs_overseer.live_signal import generate_signal_once


class LiveSignalTests(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
        config_dir = root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        source_objectives = Path(__file__).resolve().parents[1] / "config" / "objectives.json"
        shutil.copy2(source_objectives, config_dir / "objectives.json")

        settings = """
[runtime]
state_dir = "runtime"
log_dir = "runtime/logs"
events_file = "runtime/events/run_events.jsonl"
database_path = "runtime/state.db"
checkpoint_interval_seconds = 5
max_parallel_workers = 2
loop_sleep_seconds = 0.01

[automation]
run_forever = true
default_mode = "unattended"
max_candidates_per_generation = 4
keep_top_k = 2
batch_sim_episodes = 4
canary_sim_episodes = 6
canary_live_runs = 3
required_improvement = 0.03
max_stability_regression = 0.02
regression_windows_before_rollback = 2

[safety]
crash_loop_limit = 6
crash_loop_window_minutes = 30
backoff_seconds = [1, 1, 1]
allow_destructive_actions = false

[live]
enabled = true
memory_backend = "auto"
memory_signal_file = "runtime/live/memory_signal.json"
memory_signal_max_age_seconds = 120
save_data_path = "runtime/save_data.json"

[reporting]
summary_dir = "runtime/summaries"
site_dir = "site"
site_data_dir = "site/data"
status_file = "site/data/health.json"
latest_summary_file = "site/data/latest_summary.json"

[scoring]
objective_completion_weight = 0.6
time_to_unlock_weight = 0.25
stability_weight = 0.15
""".strip()
        cfg_path = config_dir / "settings.toml"
        cfg_path.write_text(settings + "\n", encoding="utf-8")
        return cfg_path

    def test_generate_signal_once_success(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-signal-") as td:
            root = Path(td)
            cfg = load_config(self._write_config(root))
            save_path = root / "runtime" / "save_data.json"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(
                json.dumps(
                    {
                        "UnlockedCharacters": ["A", "B"],
                        "UnlockedWeapons": ["W1", "W2", "W3"],
                        "UnlockedArcanas": ["AR1"],
                        "UnlockedRelics": ["R1"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            out = generate_signal_once(cfg)
            self.assertTrue(out["ok"])
            signal_path = root / "runtime" / "live" / "memory_signal.json"
            payload = json.loads(signal_path.read_text(encoding="utf-8"))
            self.assertFalse(bool(payload.get("blocked", True)))
            self.assertIn("objective_hint", payload)
            self.assertIn("stability_hint", payload)
            self.assertIn("unlocked_stages_count", payload)
            self.assertIn("save_data_age_seconds", payload)

    def test_generate_signal_once_blocked_writes_reason(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-signal-") as td:
            root = Path(td)
            cfg = load_config(self._write_config(root))

            out = generate_signal_once(cfg)
            self.assertFalse(out["ok"])
            signal_path = root / "runtime" / "live" / "memory_signal.json"
            payload = json.loads(signal_path.read_text(encoding="utf-8"))
            self.assertTrue(bool(payload.get("blocked", False)))
            self.assertIn("reason", payload)


if __name__ == "__main__":
    unittest.main()

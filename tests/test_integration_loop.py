from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from vs_overseer.config import load_config
from vs_overseer.orchestrator import Orchestrator


class IntegrationLoopTests(unittest.TestCase):
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
enabled = false
memory_backend = "auto"

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

    def test_resume_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-test-") as td:
            root = Path(td)
            cfg_path = self._write_config(root)

            cfg = load_config(cfg_path)
            orch = Orchestrator(cfg)
            first = orch.run(max_generations=2, api_port=0, enable_api=False)
            self.assertEqual(first.generations_completed, 2)

            latest_summary = cfg.resolve(cfg.reporting.latest_summary_file)
            self.assertTrue(latest_summary.exists())
            payload = json.loads(latest_summary.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("generation"), 2)
            self.assertIn("runtime_knobs", payload)
            self.assertIn("autotune", payload)
            self.assertIn("unlock_progress", payload)
            self.assertIn("unlock_trend", payload)
            self.assertIn("scoring_profile", payload)
            self.assertIn("progress_watchdog", payload)
            self.assertIn("objective_planner", payload)
            self.assertIn("wiki_sync", payload)
            self.assertIn("game_input", payload)

            cfg2 = load_config(cfg_path)
            orch2 = Orchestrator(cfg2)
            second = orch2.run(max_generations=3, api_port=0, enable_api=False)
            self.assertEqual(second.generations_completed, 3)


if __name__ == "__main__":
    unittest.main()

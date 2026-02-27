from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from vs_overseer.config import load_config


class ConfigPathTests(unittest.TestCase):
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
save_data_path = "$HOME/runtime/save_data.json"

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

    def test_resolve_expands_env_and_user(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-config-") as td:
            root = Path(td)
            cfg = load_config(self._write_config(root))

            env_path = cfg.resolve("$HOME/tmp/example.json")
            self.assertTrue(str(env_path).startswith(str(Path(os.environ["HOME"]))))

            user_path = cfg.resolve("~/tmp/example2.json")
            self.assertTrue(str(user_path).startswith(str(Path(os.environ["HOME"]))))

            rel_path = cfg.resolve("runtime/one.json")
            self.assertTrue(rel_path.is_relative_to(root.resolve()))
            self.assertFalse(cfg.autotune.enabled)
            self.assertEqual(cfg.autotune.mode, "off")
            self.assertFalse(cfg.game_input.enabled)
            self.assertEqual(cfg.game_input.app_name, "Vampire Survivors")
            self.assertGreater(cfg.game_input.watch_interval_seconds, 0.0)

    def test_project_root_detection_from_non_config_location(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-config-") as td:
            root = Path(td)
            cfg_path = self._write_config(root)

            alt_path = root / "runtime" / "tmp" / "alt_settings.toml"
            alt_path.parent.mkdir(parents=True, exist_ok=True)
            alt_path.write_text(cfg_path.read_text(encoding="utf-8"), encoding="utf-8")

            src_dir = root / "src" / "vs_overseer"
            src_dir.mkdir(parents=True, exist_ok=True)

            cfg = load_config(alt_path)
            resolved = cfg.resolve("runtime/live/memory_signal.json")
            self.assertTrue(resolved.is_relative_to(root.resolve()))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from vs_overseer.config import load_config
from vs_overseer.live_runner import LiveRunner
from vs_overseer.models import PolicyParameters


class LiveRunnerTests(unittest.TestCase):
    def _write_config(
        self,
        root: Path,
        *,
        live_enabled: bool,
        backend: str,
        signal_file: str = "runtime/live/memory_signal.json",
        save_data_path: str = "",
        progress_training_mode: bool = False,
        save_data_stale_minutes: float = 30.0,
    ) -> Path:
        config_dir = root / "config"
        config_dir.mkdir(parents=True, exist_ok=True)

        source_objectives = Path(__file__).resolve().parents[1] / "config" / "objectives.json"
        shutil.copy2(source_objectives, config_dir / "objectives.json")

        settings = f"""
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
enabled = {str(live_enabled).lower()}
memory_backend = "{backend}"
memory_signal_file = "{signal_file}"
memory_signal_max_age_seconds = 120
save_data_path = "{save_data_path}"
progress_training_mode = {str(progress_training_mode).lower()}
save_data_stale_minutes = {save_data_stale_minutes}
progress_stale_pause_minutes = 30

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

    def test_live_disabled_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            cfg = load_config(self._write_config(root, live_enabled=False, backend="auto"))
            runner = LiveRunner(cfg)
            out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.5, 0.5), runs=5, seed=11)
            self.assertTrue(out.blocked)
            self.assertEqual(out.reason, "live_disabled_by_config")

    def test_signal_file_backend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            signal_path = root / "runtime" / "live" / "memory_signal.json"
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text(
                json.dumps({"objective_rate": 0.75, "stability_rate": 0.72, "confidence": 0.9}) + "\n",
                encoding="utf-8",
            )

            cfg = load_config(self._write_config(root, live_enabled=True, backend="signal_file"))
            runner = LiveRunner(cfg)
            out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.6, 0.6), runs=8, seed=12)
            self.assertFalse(out.blocked)
            self.assertGreater(out.objective_rate, 0.0)
            self.assertTrue(out.reason.startswith("ok:signal_file:"))

    def test_save_data_backend(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            save_path = root / "runtime" / "save_data.json"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(
                json.dumps(
                    {
                        "UnlockedCharacters": ["A", "B", "C"],
                        "UnlockedWeapons": ["W1", "W2", "W3", "W4"],
                        "UnlockedArcanas": ["AR1"],
                        "UnlockedRelics": ["R1", "R2"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            cfg = load_config(
                self._write_config(
                    root,
                    live_enabled=True,
                    backend="save_data",
                    save_data_path="runtime/save_data.json",
                )
            )
            runner = LiveRunner(cfg)
            out = runner.canary(parameters=PolicyParameters(0.6, 0.55, 0.7, 0.5), runs=6, seed=13)
            self.assertFalse(out.blocked)
            self.assertTrue(out.reason.startswith("ok:save_data:"))

    def test_auto_falls_back_to_env_gate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            cfg = load_config(self._write_config(root, live_enabled=True, backend="auto"))
            runner = LiveRunner(cfg)

            old_ready = os.environ.get("VSBOT_MEMORY_BACKEND_READY")
            old_obj = os.environ.get("VSBOT_MEMORY_OBJECTIVE_HINT")
            old_stab = os.environ.get("VSBOT_MEMORY_STABILITY_HINT")
            old_conf = os.environ.get("VSBOT_MEMORY_CONFIDENCE")
            try:
                os.environ["VSBOT_MEMORY_BACKEND_READY"] = "1"
                os.environ["VSBOT_MEMORY_OBJECTIVE_HINT"] = "0.61"
                os.environ["VSBOT_MEMORY_STABILITY_HINT"] = "0.66"
                os.environ["VSBOT_MEMORY_CONFIDENCE"] = "0.58"

                out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.5, 0.5), runs=7, seed=14)
                self.assertFalse(out.blocked)
                self.assertEqual(out.runs, 7)
                self.assertEqual(out.reason, "ok:env_gate")
            finally:
                if old_ready is None:
                    os.environ.pop("VSBOT_MEMORY_BACKEND_READY", None)
                else:
                    os.environ["VSBOT_MEMORY_BACKEND_READY"] = old_ready
                if old_obj is None:
                    os.environ.pop("VSBOT_MEMORY_OBJECTIVE_HINT", None)
                else:
                    os.environ["VSBOT_MEMORY_OBJECTIVE_HINT"] = old_obj
                if old_stab is None:
                    os.environ.pop("VSBOT_MEMORY_STABILITY_HINT", None)
                else:
                    os.environ["VSBOT_MEMORY_STABILITY_HINT"] = old_stab
                if old_conf is None:
                    os.environ.pop("VSBOT_MEMORY_CONFIDENCE", None)
                else:
                    os.environ["VSBOT_MEMORY_CONFIDENCE"] = old_conf

    def test_signal_file_blocked_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            signal_path = root / "runtime" / "live" / "memory_signal.json"
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            signal_path.write_text(
                json.dumps({"blocked": True, "reason": "upstream_missing_save"}) + "\n",
                encoding="utf-8",
            )

            cfg = load_config(self._write_config(root, live_enabled=True, backend="signal_file"))
            runner = LiveRunner(cfg)
            out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.6, 0.6), runs=5, seed=15)
            self.assertTrue(out.blocked)
            self.assertIn("blocked:upstream_missing_save", out.reason)

    def test_progress_training_mode_disables_env_fallback(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            cfg = load_config(
                self._write_config(
                    root,
                    live_enabled=True,
                    backend="auto",
                    progress_training_mode=True,
                )
            )
            runner = LiveRunner(cfg)

            old_ready = os.environ.get("VSBOT_MEMORY_BACKEND_READY")
            try:
                os.environ["VSBOT_MEMORY_BACKEND_READY"] = "1"
                out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.5, 0.5), runs=5, seed=16)
                self.assertTrue(out.blocked)
                self.assertIn("memory_backend_unavailable", out.reason)
            finally:
                if old_ready is None:
                    os.environ.pop("VSBOT_MEMORY_BACKEND_READY", None)
                else:
                    os.environ["VSBOT_MEMORY_BACKEND_READY"] = old_ready

    def test_save_data_backend_blocks_stale_save(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-live-") as td:
            root = Path(td)
            save_path = root / "runtime" / "save_data.json"
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps({"UnlockedCharacters": ["A"]}) + "\n", encoding="utf-8")
            os.utime(save_path, (1, 1))

            cfg = load_config(
                self._write_config(
                    root,
                    live_enabled=True,
                    backend="save_data",
                    save_data_path="runtime/save_data.json",
                    save_data_stale_minutes=0.0001,
                )
            )
            runner = LiveRunner(cfg)
            out = runner.canary(parameters=PolicyParameters(0.5, 0.5, 0.5, 0.5), runs=5, seed=17)
            self.assertTrue(out.blocked)
            self.assertIn("stale_save_data:", out.reason)


if __name__ == "__main__":
    unittest.main()

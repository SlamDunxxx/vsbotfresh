from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest

from vs_overseer.config import load_config
from vs_overseer.runtime_autotuner import RuntimeAutoTuner, RuntimeKnobs


class _FakeClock:
    def __init__(self, *, cpu_count: int = 10) -> None:
        self.t = 0.0
        self.cpu = 0.0
        self.cpu_count = cpu_count

    def monotonic(self) -> float:
        return self.t

    def cpu_time(self) -> float:
        return self.cpu

    def advance(self, *, seconds: float, normalized_usage: float) -> None:
        self.t += float(seconds)
        self.cpu += float(seconds) * float(normalized_usage) * float(self.cpu_count)


def _summary(
    generation: int,
    *,
    promotion_state: str = "REJECTED",
    improvement: float = 0.05,
    baseline_live_obj: float = 0.8,
    candidate_live_obj: float = 0.9,
    baseline_live_stab: float = 0.74,
    candidate_live_stab: float = 0.75,
) -> dict:
    return {
        "generation": generation,
        "promotion_state": promotion_state,
        "decision": {
            "improvement": improvement,
            "stability_regression": 0.0,
            "reason": "ok",
        },
        "baseline_live": {
            "objective_rate": baseline_live_obj,
            "stability_rate": baseline_live_stab,
        },
        "candidate_live": {
            "objective_rate": candidate_live_obj,
            "stability_rate": candidate_live_stab,
        },
    }


class RuntimeAutotunerTests(unittest.TestCase):
    def _write_config(
        self,
        root: Path,
        *,
        mode: str,
        cooldown_minutes: int = 10,
        max_workers_cap: int = 8,
        episode_cap_batch: int = 96,
        episode_cap_canary_sim: int = 160,
        episode_cap_canary_live: int = 40,
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
loop_sleep_seconds = 0.5

[automation]
run_forever = true
default_mode = "unattended"
max_candidates_per_generation = 4
keep_top_k = 2
batch_sim_episodes = 24
canary_sim_episodes = 50
canary_live_runs = 10
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

[autotune]
enabled = true
mode = "{mode}"
interval_seconds = 10
cpu_target_min = 0.70
cpu_target_max = 0.85
max_workers_cap = {max_workers_cap}
min_workers_floor = 2
quality_guardrail_mode = "protect_quality"
shadow_min_minutes = 0
shadow_min_generations = 0
cooldown_minutes = {cooldown_minutes}
episode_floor_batch = 8
episode_floor_canary_sim = 30
episode_floor_canary_live = 5
episode_cap_batch = {episode_cap_batch}
episode_cap_canary_sim = {episode_cap_canary_sim}
episode_cap_canary_live = {episode_cap_canary_live}

[scoring]
objective_completion_weight = 0.6
time_to_unlock_weight = 0.25
stability_weight = 0.15
""".strip()
        cfg_path = config_dir / "settings.toml"
        cfg_path.write_text(settings + "\n", encoding="utf-8")
        return cfg_path

    def test_shadow_recommends_without_applying(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-autotune-") as td:
            cfg = load_config(self._write_config(Path(td), mode="shadow"))
            fake = _FakeClock(cpu_count=10)
            initial = RuntimeKnobs(
                max_parallel_workers=2,
                batch_sim_episodes=24,
                canary_sim_episodes=50,
                canary_live_runs=10,
                loop_sleep_seconds=0.5,
            )
            tuner = RuntimeAutoTuner(
                cfg,
                initial,
                monotonic_fn=fake.monotonic,
                cpu_time_fn=fake.cpu_time,
                cpu_count=10,
            )

            decision = {}
            knobs = initial
            for gen in range(1, 19):
                fake.advance(seconds=1.0, normalized_usage=0.2)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=0)

            self.assertEqual(knobs.max_parallel_workers, 2)
            self.assertEqual(decision.get("mode"), "shadow")
            self.assertEqual(decision.get("action"), "recommend")
            self.assertEqual(decision.get("recommended_knobs", {}).get("max_parallel_workers"), 3)
            self.assertIsNone(decision.get("applied_knobs"))

    def test_enforce_applies_worker_scale_up(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-autotune-") as td:
            cfg = load_config(self._write_config(Path(td), mode="enforce"))
            fake = _FakeClock(cpu_count=10)
            tuner = RuntimeAutoTuner(
                cfg,
                RuntimeKnobs(2, 24, 50, 10, 0.5),
                monotonic_fn=fake.monotonic,
                cpu_time_fn=fake.cpu_time,
                cpu_count=10,
            )

            decision = {}
            knobs = tuner.current_knobs()
            for gen in range(1, 19):
                fake.advance(seconds=1.0, normalized_usage=0.2)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=0)

            self.assertEqual(decision.get("mode"), "enforce")
            self.assertEqual(decision.get("action"), "apply")
            self.assertEqual(knobs.max_parallel_workers, 3)
            self.assertEqual(decision.get("applied_knobs", {}).get("max_parallel_workers"), 3)

    def test_guardrail_rolls_back_and_cooldown_holds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-autotune-") as td:
            cfg = load_config(self._write_config(Path(td), mode="enforce", cooldown_minutes=2))
            fake = _FakeClock(cpu_count=10)
            tuner = RuntimeAutoTuner(
                cfg,
                RuntimeKnobs(3, 24, 50, 10, 0.5),
                monotonic_fn=fake.monotonic,
                cpu_time_fn=fake.cpu_time,
                cpu_count=10,
            )

            decision = {}
            knobs = tuner.current_knobs()

            # First interval: good and under target, should scale up.
            for gen in range(1, 19):
                fake.advance(seconds=1.0, normalized_usage=0.2)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=0)
            self.assertEqual(knobs.max_parallel_workers, 4)
            self.assertEqual(decision.get("action"), "apply")

            # Next interval: guardrail trigger via recoveries, should rollback.
            for gen in range(19, 36):
                fake.advance(seconds=1.0, normalized_usage=0.2)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=1)
            self.assertEqual(knobs.max_parallel_workers, 3)
            self.assertEqual(decision.get("action"), "rollback")
            self.assertTrue(decision.get("guardrail_state", {}).get("triggered"))

            # During cooldown it should hold rather than scale up.
            for gen in range(36, 53):
                fake.advance(seconds=1.0, normalized_usage=0.2)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=0)
            self.assertEqual(knobs.max_parallel_workers, 3)
            self.assertEqual(decision.get("reason"), "cooldown_active_hold")

    def test_cpu_below_target_at_limits_increases_episode_budget(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-autotune-") as td:
            cfg = load_config(
                self._write_config(
                    Path(td),
                    mode="enforce",
                    max_workers_cap=2,
                    episode_cap_batch=40,
                    episode_cap_canary_sim=60,
                    episode_cap_canary_live=12,
                )
            )
            fake = _FakeClock(cpu_count=10)
            tuner = RuntimeAutoTuner(
                cfg,
                RuntimeKnobs(2, 24, 50, 10, 0.2),
                monotonic_fn=fake.monotonic,
                cpu_time_fn=fake.cpu_time,
                cpu_count=10,
            )

            decision = {}
            knobs = tuner.current_knobs()
            for gen in range(1, 19):
                fake.advance(seconds=1.0, normalized_usage=0.1)
                knobs, decision = tuner.observe_generation(summary=_summary(gen), recoveries_30m=0)

            self.assertEqual(decision.get("action"), "apply")
            self.assertEqual(decision.get("reason"), "cpu_below_target_increase_episode_budget")
            self.assertGreaterEqual(knobs.batch_sim_episodes, 28)
            self.assertGreaterEqual(knobs.canary_sim_episodes, 54)
            self.assertGreaterEqual(knobs.canary_live_runs, 11)


if __name__ == "__main__":
    unittest.main()

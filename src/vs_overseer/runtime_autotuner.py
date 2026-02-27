from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import os
import resource
import time
from typing import Any, Callable

from .config import AppConfig


@dataclass(frozen=True)
class RuntimeKnobs:
    max_parallel_workers: int
    batch_sim_episodes: int
    canary_sim_episodes: int
    canary_live_runs: int
    loop_sleep_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_parallel_workers": int(self.max_parallel_workers),
            "batch_sim_episodes": int(self.batch_sim_episodes),
            "canary_sim_episodes": int(self.canary_sim_episodes),
            "canary_live_runs": int(self.canary_live_runs),
            "loop_sleep_seconds": float(self.loop_sleep_seconds),
        }


def _default_cpu_time() -> float:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return float(self_usage.ru_utime + self_usage.ru_stime + child_usage.ru_utime + child_usage.ru_stime)


class RuntimeAutoTuner:
    def __init__(
        self,
        cfg: AppConfig,
        initial_knobs: RuntimeKnobs,
        *,
        monotonic_fn: Callable[[], float] | None = None,
        cpu_time_fn: Callable[[], float] | None = None,
        cpu_count: int | None = None,
    ) -> None:
        self.cfg = cfg
        self.enabled = bool(cfg.autotune.enabled)
        self.mode = str(cfg.autotune.mode or "off").strip().lower()
        if self.mode not in {"off", "shadow", "enforce"}:
            self.mode = "off"
        if self.mode == "off":
            self.enabled = False

        self._mono = monotonic_fn or time.monotonic
        self._cpu_time = cpu_time_fn or _default_cpu_time
        self._cpu_count = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))

        self._history: deque[dict[str, Any]] = deque(maxlen=2400)
        self._knobs = initial_knobs
        self._last_safe_knobs = initial_knobs
        self._last_decision: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "action": "none",
            "reason": "autotune_disabled" if not self.enabled else "waiting_for_interval",
            "recommended_knobs": initial_knobs.to_dict(),
            "applied_knobs": None,
            "guardrail_state": {"triggered": False, "reasons": []},
            "cpu_snapshot": {"normalized_usage": 0.0, "target_min": cfg.autotune.cpu_target_min, "target_max": cfg.autotune.cpu_target_max},
            "quality_snapshot": {},
            "shadow_ready": False,
            "cooldown_remaining_seconds": 0.0,
            "current_knobs": initial_knobs.to_dict(),
        }

        self._started_mono = self._mono()
        self._last_eval_mono = self._started_mono
        self._last_cpu_mono = self._started_mono
        self._last_cpu_total = self._cpu_time()
        self._cpu_normalized_usage = 0.0
        self._cooldown_until_mono = 0.0

    def current_knobs(self) -> RuntimeKnobs:
        return self._knobs

    def status_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "enabled": bool(self.enabled),
            "last_decision_at": self._last_decision.get("ts"),
            "last_action": self._last_decision.get("action", "none"),
            "guardrail_state": self._last_decision.get("guardrail_state", {"triggered": False, "reasons": []}),
            "current_knobs": self._knobs.to_dict(),
            "cpu_snapshot": self._last_decision.get("cpu_snapshot", {}),
            "shadow_ready": bool(self._last_decision.get("shadow_ready", False)),
            "cooldown_remaining_seconds": float(self._last_decision.get("cooldown_remaining_seconds", 0.0)),
        }

    def observe_generation(self, *, summary: dict[str, Any], recoveries_30m: int) -> tuple[RuntimeKnobs, dict[str, Any]]:
        now_mono = self._mono()
        self._refresh_cpu(now_mono)
        self._record_summary(summary)

        decision = self._last_decision
        if not self.enabled:
            decision = self._decision_payload(
                action="none",
                reason="autotune_disabled",
                recommended=self._knobs,
                applied=None,
                guardrail_reasons=[],
                quality_snapshot={},
                now_mono=now_mono,
            )
        elif (now_mono - self._last_eval_mono) >= float(self.cfg.autotune.interval_seconds):
            decision = self._evaluate(now_mono=now_mono, recoveries_30m=recoveries_30m)
            self._last_eval_mono = now_mono

        self._last_decision = decision
        return self._knobs, dict(decision)

    def _refresh_cpu(self, now_mono: float) -> None:
        cpu_total = self._cpu_time()
        wall_delta = max(1e-9, now_mono - self._last_cpu_mono)
        cpu_delta = max(0.0, cpu_total - self._last_cpu_total)
        usage = cpu_delta / (wall_delta * float(self._cpu_count))
        self._cpu_normalized_usage = max(0.0, min(1.5, float(usage)))
        self._last_cpu_mono = now_mono
        self._last_cpu_total = cpu_total

    def _record_summary(self, summary: dict[str, Any]) -> None:
        decision = summary.get("decision") or {}
        baseline_live = summary.get("baseline_live") or {}
        candidate_live = summary.get("candidate_live") or {}
        unlock_trend = summary.get("unlock_trend") or {}
        row = {
            "generation": int(summary.get("generation", 0)),
            "promotion_state": str(summary.get("promotion_state", "")),
            "improvement": float(decision.get("improvement", 0.0)),
            "live_obj_delta": float(candidate_live.get("objective_rate", 0.0)) - float(baseline_live.get("objective_rate", 0.0)),
            "live_stab_delta": float(candidate_live.get("stability_rate", 0.0)) - float(baseline_live.get("stability_rate", 0.0)),
            "stability_regression": float(decision.get("stability_regression", 0.0)),
            "decision_reason": str(decision.get("reason", "")),
            "unlock_delta_score": (
                float(unlock_trend.get("triad_progress_delta_score"))
                if unlock_trend.get("triad_progress_delta_score") is not None
                else None
            ),
        }
        self._history.append(row)

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return float(sum(values) / len(values))

    def _quality_snapshot(self) -> dict[str, Any]:
        rows = list(self._history)[-300:]
        if not rows:
            return {
                "window_size": 0,
                "recent": {},
                "previous": {},
            }

        half = max(1, len(rows) // 2)
        prev = rows[:half]
        recent = rows[half:]

        def _summarize(part: list[dict[str, Any]]) -> dict[str, Any]:
            promotions = sum(1 for r in part if str(r.get("promotion_state", "")).startswith("PROMOTED_ACTIVE"))
            unlock_values = [float(r.get("unlock_delta_score")) for r in part if r.get("unlock_delta_score") is not None]
            return {
                "count": len(part),
                "promotion_rate": promotions / max(1.0, float(len(part))),
                "mean_improvement": self._mean([float(r.get("improvement", 0.0)) for r in part]),
                "mean_live_obj_delta": self._mean([float(r.get("live_obj_delta", 0.0)) for r in part]),
                "mean_live_stab_delta": self._mean([float(r.get("live_stab_delta", 0.0)) for r in part]),
                "mean_unlock_delta_score": self._mean(unlock_values),
                "unlock_delta_samples": len(unlock_values),
            }

        recent_summary = _summarize(recent)
        previous_summary = _summarize(prev)
        return {
            "window_size": len(rows),
            "recent": recent_summary,
            "previous": previous_summary,
        }

    def _guardrail_reasons(self, quality: dict[str, Any], recoveries_30m: int) -> list[str]:
        reasons: list[str] = []
        recent = quality.get("recent") or {}
        previous = quality.get("previous") or {}
        recent_count = int(recent.get("count", 0))

        if recoveries_30m > 0:
            reasons.append("recoveries_present")

        if recent_count < 40:
            return reasons

        recent_live_obj = float(recent.get("mean_live_obj_delta", 0.0))
        recent_live_stab = float(recent.get("mean_live_stab_delta", 0.0))
        recent_improvement = float(recent.get("mean_improvement", 0.0))
        prev_improvement = float(previous.get("mean_improvement", 0.0))
        recent_promotion_rate = float(recent.get("promotion_rate", 0.0))
        prev_promotion_rate = float(previous.get("promotion_rate", 0.0))
        recent_unlock_delta = float(recent.get("mean_unlock_delta_score", 0.0))
        recent_unlock_samples = int(recent.get("unlock_delta_samples", 0))

        if recent_live_obj < -0.03:
            reasons.append("live_objective_trend_negative")
        if recent_live_stab < -0.02:
            reasons.append("live_stability_trend_negative")
        if recent_unlock_samples >= 10 and recent_unlock_delta <= 0.0:
            reasons.append("real_unlock_progress_flat")
        if recent_improvement < (prev_improvement - 0.02):
            reasons.append("sim_improvement_trend_degraded")
        if recent_improvement < 0.0 and recent_promotion_rate < (prev_promotion_rate - 0.05):
            reasons.append("promotion_rate_trend_degraded")
        return reasons

    def _episode_caps(self) -> tuple[int, int, int]:
        return (
            max(int(self.cfg.autotune.episode_floor_batch), int(self.cfg.autotune.episode_cap_batch)),
            max(int(self.cfg.autotune.episode_floor_canary_sim), int(self.cfg.autotune.episode_cap_canary_sim)),
            max(int(self.cfg.autotune.episode_floor_canary_live), int(self.cfg.autotune.episode_cap_canary_live)),
        )

    def _recommend(self, *, quality: dict[str, Any], guardrail_reasons: list[str], now_mono: float) -> tuple[RuntimeKnobs, str]:
        current = self._knobs
        target_min = min(self.cfg.autotune.cpu_target_min, self.cfg.autotune.cpu_target_max)
        target_max = max(self.cfg.autotune.cpu_target_min, self.cfg.autotune.cpu_target_max)
        worker_floor = min(self.cfg.autotune.min_workers_floor, self.cfg.autotune.max_workers_cap)
        worker_cap = max(self.cfg.autotune.min_workers_floor, self.cfg.autotune.max_workers_cap)
        cooldown_active = now_mono < self._cooldown_until_mono

        if guardrail_reasons:
            return self._last_safe_knobs, "guardrail_triggered_revert_to_last_safe"

        recent = quality.get("recent") or {}
        recent_improvement = float(recent.get("mean_improvement", 0.0))
        recent_live_obj = float(recent.get("mean_live_obj_delta", 0.0))
        recent_live_stab = float(recent.get("mean_live_stab_delta", 0.0))
        recent_unlock_delta = float(recent.get("mean_unlock_delta_score", 0.0))
        quality_strong = (
            recent_improvement >= 0.01
            and recent_live_obj >= 0.0
            and recent_live_stab >= -0.01
            and recent_unlock_delta > 0.0
        )

        cap_batch, cap_canary_sim, cap_canary_live = self._episode_caps()

        if cooldown_active:
            if self._cpu_normalized_usage > target_max and current.max_parallel_workers > worker_floor:
                return replace(current, max_parallel_workers=current.max_parallel_workers - 1), "cooldown_cpu_above_target_scale_down_workers"
            return current, "cooldown_active_hold"

        if self._cpu_normalized_usage < target_min:
            if current.max_parallel_workers < worker_cap:
                return replace(current, max_parallel_workers=current.max_parallel_workers + 1), "cpu_below_target_scale_up_workers"
            if current.loop_sleep_seconds > 0.2:
                return replace(current, loop_sleep_seconds=max(0.2, current.loop_sleep_seconds - 0.1)), "cpu_below_target_reduce_loop_sleep"
            if (
                current.batch_sim_episodes < cap_batch
                or current.canary_sim_episodes < cap_canary_sim
                or current.canary_live_runs < cap_canary_live
            ):
                return replace(
                    current,
                    batch_sim_episodes=min(cap_batch, current.batch_sim_episodes + 4),
                    canary_sim_episodes=min(cap_canary_sim, current.canary_sim_episodes + 4),
                    canary_live_runs=min(cap_canary_live, current.canary_live_runs + 1),
                ), "cpu_below_target_increase_episode_budget"
            return current, "cpu_below_target_at_limits"

        if self._cpu_normalized_usage > target_max:
            floor_batch = int(self.cfg.autotune.episode_floor_batch)
            floor_canary_sim = int(self.cfg.autotune.episode_floor_canary_sim)
            floor_canary_live = int(self.cfg.autotune.episode_floor_canary_live)
            if (
                current.batch_sim_episodes > floor_batch
                or current.canary_sim_episodes > floor_canary_sim
                or current.canary_live_runs > floor_canary_live
            ):
                return replace(
                    current,
                    batch_sim_episodes=max(floor_batch, current.batch_sim_episodes - 4),
                    canary_sim_episodes=max(floor_canary_sim, current.canary_sim_episodes - 4),
                    canary_live_runs=max(floor_canary_live, current.canary_live_runs - 1),
                ), "cpu_above_target_reduce_episode_budget"
            if current.max_parallel_workers > worker_floor:
                return replace(current, max_parallel_workers=current.max_parallel_workers - 1), "cpu_above_target_scale_down_workers"
            return replace(current, loop_sleep_seconds=min(2.0, current.loop_sleep_seconds + 0.1)), "cpu_above_target_increase_loop_sleep"

        if not quality_strong:
            return replace(
                current,
                canary_sim_episodes=min(max(current.canary_sim_episodes + 2, current.canary_sim_episodes), max(current.canary_sim_episodes, self.cfg.automation.canary_sim_episodes * 2)),
                canary_live_runs=min(max(current.canary_live_runs + 1, current.canary_live_runs), max(current.canary_live_runs, self.cfg.automation.canary_live_runs * 2)),
            ), "quality_soft_guard_increase_canary_budget"

        floor_canary_sim = max(1, int(self.cfg.autotune.episode_floor_canary_sim))
        floor_canary_live = max(1, int(self.cfg.autotune.episode_floor_canary_live))
        if current.canary_sim_episodes > floor_canary_sim:
            return replace(current, canary_sim_episodes=max(floor_canary_sim, current.canary_sim_episodes - 2)), "quality_strong_reduce_canary_sim_cost"
        if current.canary_live_runs > floor_canary_live:
            return replace(current, canary_live_runs=max(floor_canary_live, current.canary_live_runs - 1)), "quality_strong_reduce_canary_live_cost"
        return current, "cpu_within_target_quality_stable"

    def _evaluate(self, *, now_mono: float, recoveries_30m: int) -> dict[str, Any]:
        quality = self._quality_snapshot()
        guardrail_reasons = self._guardrail_reasons(quality, recoveries_30m)
        recommended, reason = self._recommend(quality=quality, guardrail_reasons=guardrail_reasons, now_mono=now_mono)

        if guardrail_reasons:
            self._cooldown_until_mono = now_mono + (float(self.cfg.autotune.cooldown_minutes) * 60.0)
        elif len(quality.get("recent") or {}) > 0:
            self._last_safe_knobs = self._knobs

        shadow_elapsed = max(0.0, now_mono - self._started_mono)
        shadow_ready = (
            shadow_elapsed >= float(self.cfg.autotune.shadow_min_minutes) * 60.0
            and len(self._history) >= int(self.cfg.autotune.shadow_min_generations)
        )

        action = "recommend"
        applied: RuntimeKnobs | None = None
        if self.mode == "enforce":
            if recommended != self._knobs:
                self._knobs = self._apply_bounds(recommended)
                applied = self._knobs
                action = "rollback" if guardrail_reasons else "apply"
            else:
                action = "none"
        elif self.mode == "shadow":
            action = "recommend" if recommended != self._knobs else "none"
        else:
            action = "none"

        return self._decision_payload(
            action=action,
            reason=reason,
            recommended=recommended,
            applied=applied,
            guardrail_reasons=guardrail_reasons,
            quality_snapshot=quality,
            now_mono=now_mono,
            shadow_ready=shadow_ready,
        )

    def _apply_bounds(self, knobs: RuntimeKnobs) -> RuntimeKnobs:
        floor_workers = min(self.cfg.autotune.min_workers_floor, self.cfg.autotune.max_workers_cap)
        cap_workers = max(self.cfg.autotune.min_workers_floor, self.cfg.autotune.max_workers_cap)
        cap_batch, cap_canary_sim, cap_canary_live = self._episode_caps()
        return RuntimeKnobs(
            max_parallel_workers=min(cap_workers, max(floor_workers, int(knobs.max_parallel_workers))),
            batch_sim_episodes=min(cap_batch, max(int(self.cfg.autotune.episode_floor_batch), int(knobs.batch_sim_episodes))),
            canary_sim_episodes=min(cap_canary_sim, max(int(self.cfg.autotune.episode_floor_canary_sim), int(knobs.canary_sim_episodes))),
            canary_live_runs=min(cap_canary_live, max(int(self.cfg.autotune.episode_floor_canary_live), int(knobs.canary_live_runs))),
            loop_sleep_seconds=max(0.2, float(knobs.loop_sleep_seconds)),
        )

    def _decision_payload(
        self,
        *,
        action: str,
        reason: str,
        recommended: RuntimeKnobs,
        applied: RuntimeKnobs | None,
        guardrail_reasons: list[str],
        quality_snapshot: dict[str, Any],
        now_mono: float,
        shadow_ready: bool = False,
    ) -> dict[str, Any]:
        cooldown_remaining = max(0.0, self._cooldown_until_mono - now_mono)
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": self.mode,
            "action": action,
            "reason": reason,
            "recommended_knobs": recommended.to_dict(),
            "applied_knobs": applied.to_dict() if applied is not None else None,
            "guardrail_state": {
                "triggered": bool(guardrail_reasons),
                "reasons": list(guardrail_reasons),
            },
            "cpu_snapshot": {
                "normalized_usage": float(self._cpu_normalized_usage),
                "target_min": float(self.cfg.autotune.cpu_target_min),
                "target_max": float(self.cfg.autotune.cpu_target_max),
                "cpu_count": int(self._cpu_count),
            },
            "quality_snapshot": quality_snapshot,
            "shadow_ready": bool(shadow_ready),
            "cooldown_remaining_seconds": float(cooldown_remaining),
            "current_knobs": self._knobs.to_dict(),
        }

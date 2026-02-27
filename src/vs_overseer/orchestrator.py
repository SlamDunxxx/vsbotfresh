from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import threading
import time
from typing import Any

from .api import ControlBridge, start_api_server
from .config import AppConfig
from .dashboard import ensure_site, write_daily_summary, write_json
from .live_runner import LiveRunner
from .models import CanaryDecision, LiveBatchMetrics, PolicyParameters, SimBatchMetrics, utc_now_iso
from .objective_graph import Objective, ObjectiveGraph
from .objective_planner import ObjectivePlanner, PlannedObjective
from .policy_registry import CheckpointState, PolicyRecord, PolicyRegistry
from .runtime_autotuner import RuntimeAutoTuner, RuntimeKnobs
from .safety import SafetyManager
from .scoring import improvement_ratio, objective_biased_scoring, weighted_score
from .simulator import Simulator
from .tuner import PopulationTuner
from .wiki_sync import WikiSyncer


@dataclass(frozen=True)
class OrchestratorRunResult:
    generations_completed: int
    stop_reason: str
    active_policy_id: str
    safe_pause: bool


def _to_float(raw: Any) -> float | None:
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return None


def _token_in_list(payload: dict[str, Any], key: str, token: str) -> bool | None:
    raw = payload.get(key)
    if not isinstance(raw, list):
        return None
    target = str(token).strip().upper()
    if not target:
        return None
    values = {str(item).strip().upper() for item in raw if str(item).strip()}
    return target in values


def objective_unlock_met(unlock_signal: str, signal_payload: dict[str, Any]) -> bool | None:
    raw = str(unlock_signal or "").strip()
    if not raw or ":" not in raw:
        return None

    kind, value = raw.split(":", 1)
    kind = kind.strip().lower()
    value = value.strip().lower()

    if kind == "collection_ratio":
        current = _to_float(signal_payload.get("collection_ratio"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "collection_entries":
        current = _to_float(signal_payload.get("collection_entries"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "bestiary_ratio":
        current = _to_float(signal_payload.get("bestiary_ratio"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "bestiary_entries":
        current = _to_float(signal_payload.get("bestiary_entries"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "steam_achievements_ratio":
        current = _to_float(signal_payload.get("steam_achievements_ratio"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "steam_achievements":
        current = _to_float(signal_payload.get("steam_achievements"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "unlocked_characters_count":
        current = _to_float(signal_payload.get("unlocked_characters_count"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "unlocked_arcanas_count":
        current = _to_float(signal_payload.get("unlocked_arcanas_count"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "unlocked_weapons_count":
        current = _to_float(signal_payload.get("unlocked_weapons_count"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "unlocked_passives_count":
        current = _to_float(signal_payload.get("unlocked_passives_count"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "unlocked_stages_count":
        current = _to_float(signal_payload.get("unlocked_stages_count"))
        target = _to_float(value)
        if current is None or target is None:
            return None
        return current >= target

    if kind == "has_character":
        return _token_in_list(signal_payload, "unlocked_characters", value)

    if kind == "has_arcana":
        return _token_in_list(signal_payload, "unlocked_arcanas", value)

    if kind == "has_weapon":
        return _token_in_list(signal_payload, "unlocked_weapons", value)

    if kind == "has_passive":
        return _token_in_list(signal_payload, "unlocked_passives", value)

    if kind == "has_stage":
        return _token_in_list(signal_payload, "unlocked_stages", value)

    if kind == "completion" and value == "full_triad":
        collection = _to_float(signal_payload.get("collection_ratio"))
        bestiary = _to_float(signal_payload.get("bestiary_ratio"))
        steam = _to_float(signal_payload.get("steam_achievements_ratio"))
        if collection is None or bestiary is None or steam is None:
            return None
        return collection >= 1.0 and bestiary >= 1.0 and steam >= 1.0

    return None


def strict_canary_decision(
    *,
    candidate_metrics: SimBatchMetrics,
    baseline_metrics: SimBatchMetrics,
    candidate_live: LiveBatchMetrics,
    baseline_live: LiveBatchMetrics,
    required_improvement: float,
    max_stability_regression: float,
    candidate_score: float,
    baseline_score: float,
) -> CanaryDecision:
    improvement = improvement_ratio(candidate_score, baseline_score)
    stability_regression = max(0.0, baseline_metrics.stability_rate - candidate_metrics.stability_rate)

    if improvement < required_improvement:
        return CanaryDecision(
            promote=False,
            reason=f"sim_improvement_below_threshold:{improvement:.4f}",
            improvement=improvement,
            stability_regression=stability_regression,
            live_deferred=False,
        )

    if stability_regression > max_stability_regression:
        return CanaryDecision(
            promote=False,
            reason=f"sim_stability_regression_too_high:{stability_regression:.4f}",
            improvement=improvement,
            stability_regression=stability_regression,
            live_deferred=False,
        )

    if candidate_live.blocked or baseline_live.blocked:
        return CanaryDecision(
            promote=True,
            reason="live_deferred_memory_backend_unavailable",
            improvement=improvement,
            stability_regression=stability_regression,
            live_deferred=True,
        )

    live_obj_improvement = candidate_live.objective_rate - baseline_live.objective_rate
    live_stability_regression = max(0.0, baseline_live.stability_rate - candidate_live.stability_rate)

    if live_obj_improvement < 0.0:
        return CanaryDecision(
            promote=False,
            reason=f"live_objective_regression:{live_obj_improvement:.4f}",
            improvement=improvement,
            stability_regression=max(stability_regression, live_stability_regression),
            live_deferred=False,
        )

    if live_stability_regression > max_stability_regression:
        return CanaryDecision(
            promote=False,
            reason=f"live_stability_regression_too_high:{live_stability_regression:.4f}",
            improvement=improvement,
            stability_regression=max(stability_regression, live_stability_regression),
            live_deferred=False,
        )

    return CanaryDecision(
        promote=True,
        reason="strict_canary_pass",
        improvement=improvement,
        stability_regression=max(stability_regression, live_stability_regression),
        live_deferred=False,
    )


class Orchestrator:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg
        self.events_file = cfg.resolve(cfg.runtime.events_file)
        self.db_path = cfg.resolve(cfg.runtime.database_path)
        self.policies_root = cfg.resolve("policies")
        self.objective_graph_path = cfg.resolve("config/objectives.json")
        self.objective_planner_path = cfg.resolve(cfg.objective_planner.mapping_file)
        self.objective_planner_heartbeat_path = cfg.resolve(cfg.objective_planner.heartbeat_log_file)
        self.wiki_sources_path = cfg.resolve(cfg.wiki_sync.sources_file)
        self.wiki_mapping_path = cfg.resolve(cfg.wiki_sync.mapping_file)
        self.summary_dir = cfg.resolve(cfg.reporting.summary_dir)
        self.site_dir = cfg.resolve(cfg.reporting.site_dir)
        self.site_data_dir = cfg.resolve(cfg.reporting.site_data_dir)
        self.status_file = cfg.resolve(cfg.reporting.status_file)
        self.latest_summary_file = cfg.resolve(cfg.reporting.latest_summary_file)
        self.game_input_status_file = cfg.resolve(cfg.game_input.status_file)

        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        self.site_data_dir.mkdir(parents=True, exist_ok=True)
        ensure_site(self.site_dir)

        self.registry = PolicyRegistry(self.db_path, self.policies_root)
        self.objectives = ObjectiveGraph.load(self.objective_graph_path)
        self.objective_planner: ObjectivePlanner | None = None
        self._objective_planner_error = ""
        if bool(self.cfg.objective_planner.enabled):
            try:
                self.objective_planner = ObjectivePlanner.load(
                    self.objective_planner_path,
                    rolling_window_size=self.cfg.objective_planner.rolling_window_size,
                )
            except Exception as exc:  # noqa: BLE001
                self._objective_planner_error = f"planner_load_error:{exc}"
        self.simulator = Simulator(cfg.project_root)
        self.tuner = PopulationTuner(cfg, self.simulator)
        self.live_runner = LiveRunner(cfg)
        self.safety = SafetyManager(cfg.safety)
        self.bridge = ControlBridge()

        self._state_lock = threading.Lock()
        self._checkpoint = self.registry.load_checkpoint()
        self._heartbeat_stop = threading.Event()
        self._api_server = None
        self._api_thread = None
        self._generation = 0
        self._last_backend = "python"
        self._last_error = ""
        self._runtime_knobs = RuntimeKnobs(
            max_parallel_workers=self.cfg.runtime.max_parallel_workers,
            batch_sim_episodes=self.cfg.automation.batch_sim_episodes,
            canary_sim_episodes=self.cfg.automation.canary_sim_episodes,
            canary_live_runs=self.cfg.automation.canary_live_runs,
            loop_sleep_seconds=self.cfg.runtime.loop_sleep_seconds,
        )
        self._autotuner = RuntimeAutoTuner(self.cfg, self._runtime_knobs)
        self._autotune_status = self._autotuner.status_payload()
        self._last_unlock_metrics: dict[str, float] | None = None
        self._planned_queue_cache: list[PlannedObjective] = self._planned_from_checkpoint()
        self._planned_queue_last_refresh_generation = -1
        self._planner_heartbeat_last_mono = 0.0
        self._planner_heartbeat_last_signature = ""
        self._wiki_syncer: WikiSyncer | None = None
        self._wiki_sync_status: dict[str, Any] = {
            "enabled": bool(self.cfg.wiki_sync.enabled),
            "active": False,
            "ok": False,
            "changed": False,
            "reason": "disabled",
            "last_synced_at": "",
            "sources_file": str(self.wiki_sources_path),
            "mapping_file": str(self.wiki_mapping_path),
        }
        if bool(self.cfg.wiki_sync.enabled):
            self._wiki_syncer = WikiSyncer(
                sources_path=self.wiki_sources_path,
                mapping_path=self.wiki_mapping_path,
                timeout_seconds=self.cfg.wiki_sync.request_timeout_seconds,
            )
            self._wiki_sync_status = {
                "enabled": True,
                "active": True,
                "ok": False,
                "changed": False,
                "reason": "pending_first_sync",
                "last_synced_at": "",
                "sources_file": str(self.wiki_sources_path),
                "mapping_file": str(self.wiki_mapping_path),
            }
        self._wiki_sync_last_mono = 0.0

    def _append_event(self, *, phase: str, event_type: str, severity: str, payload: dict[str, Any]) -> None:
        row = {
            "ts": utc_now_iso(),
            "phase": phase,
            "event_type": event_type,
            "severity": severity,
            "payload": payload,
        }
        self.events_file.parent.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")

    def _checkpoint_episode_increment(self) -> None:
        with self._state_lock:
            counters = dict(self._checkpoint.failure_counters)
            counters["episodes_completed"] = int(counters.get("episodes_completed", 0)) + 1
            self._checkpoint.failure_counters = counters
            self.registry.save_checkpoint(self._checkpoint)

    def _heartbeat_loop(self) -> None:
        interval = max(5, int(self.cfg.runtime.checkpoint_interval_seconds))
        while not self._heartbeat_stop.wait(timeout=interval):
            with self._state_lock:
                self.registry.save_checkpoint(self._checkpoint)

    def _update_health(self, *, state: str, note: str = "") -> None:
        snapshot = self.bridge.snapshot()
        watchdog = self._progress_watchdog_status()
        payload = {
            "generated_at": utc_now_iso(),
            "mode": self.cfg.automation.default_mode,
            "state": state,
            "generation": self._checkpoint.loop_cursor,
            "active_policy_id": self._checkpoint.active_policy_id,
            "safe_pause": bool(self._checkpoint.safe_pause or snapshot["safe_pause"]),
            "safe_pause_reason": self._checkpoint.safe_pause_reason or snapshot["safe_pause_reason"],
            "recoveries_30m": self.safety.recovery_count(),
            "sim_backend": self._last_backend,
            "last_error": self._last_error,
            "note": note,
            "autotune": dict(self._autotune_status),
            "progress_watchdog": watchdog,
            "objective_planner": self._objective_planner_status(),
            "wiki_sync": self._wiki_sync_status_payload(),
            "game_input": self._game_input_status_payload(),
        }
        write_json(self.status_file, payload)
        self.bridge.update_health(payload)

    def _update_summary(self, payload: dict[str, Any]) -> None:
        write_json(self.latest_summary_file, payload)
        self.bridge.update_summary(payload)
        write_daily_summary(self.summary_dir, payload)

    @staticmethod
    def _extract_unlock_metrics(payload: dict[str, Any]) -> dict[str, float]:
        keys = [
            "collection_entries",
            "bestiary_entries",
            "steam_achievements",
            "unlocked_characters_count",
            "unlocked_arcanas_count",
            "unlocked_weapons_count",
            "unlocked_passives_count",
            "unlocked_stages_count",
            "collection_ratio",
            "bestiary_ratio",
            "steam_achievements_ratio",
        ]
        out: dict[str, float] = {}
        for key in keys:
            value = _to_float(payload.get(key))
            if value is not None:
                out[key] = float(value)
        return out

    def _augment_signal_with_unlock_deltas(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {}
        enriched = dict(payload)
        current = self._extract_unlock_metrics(enriched)
        previous = self._last_unlock_metrics or {}

        for key in [
            "collection_entries",
            "bestiary_entries",
            "steam_achievements",
            "unlocked_characters_count",
            "unlocked_arcanas_count",
            "unlocked_weapons_count",
            "unlocked_passives_count",
            "unlocked_stages_count",
            "collection_ratio",
            "bestiary_ratio",
            "steam_achievements_ratio",
        ]:
            cur = current.get(key)
            prev = previous.get(key)
            delta_key = f"{key}_delta"
            if cur is None or prev is None:
                enriched[delta_key] = None
            else:
                enriched[delta_key] = float(cur - prev)

        collection_gain = max(0.0, float(enriched.get("collection_entries_delta") or 0.0))
        bestiary_gain = max(0.0, float(enriched.get("bestiary_entries_delta") or 0.0))
        achievement_gain = max(0.0, float(enriched.get("steam_achievements_delta") or 0.0))

        collection_target = max(1.0, float(enriched.get("collection_target") or 470.0))
        bestiary_target = max(1.0, float(enriched.get("bestiary_target") or 360.0))
        achievement_target = max(1.0, float(enriched.get("steam_achievements_target") or 243.0))

        wc = max(0.0, float(self.cfg.scoring.collection_gain_weight))
        wb = max(0.0, float(self.cfg.scoring.bestiary_gain_weight))
        wa = max(0.0, float(self.cfg.scoring.achievement_gain_weight))
        wsum = wc + wb + wa
        if wsum > 0.0:
            triad_delta_score = (
                (wc * (collection_gain / collection_target))
                + (wb * (bestiary_gain / bestiary_target))
                + (wa * (achievement_gain / achievement_target))
            ) / wsum
        else:
            triad_delta_score = 0.0

        enriched["triad_progress_delta_score"] = float(triad_delta_score)
        enriched["triad_progress_any_gain"] = bool(
            collection_gain > 0.0 or bestiary_gain > 0.0 or achievement_gain > 0.0
        )
        self._last_unlock_metrics = current
        return enriched

    def _planned_from_checkpoint(self) -> list[PlannedObjective]:
        rows = self._checkpoint.population_state.get("planned_objectives", [])
        if not isinstance(rows, list):
            return []
        out: list[PlannedObjective] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                out.append(PlannedObjective.from_dict(row))
            except Exception:  # noqa: BLE001
                continue
        return out

    def _refresh_objective_queue(self, *, signal_payload: dict[str, Any], force: bool = False) -> list[PlannedObjective]:
        if self.objective_planner is None:
            self._planned_queue_cache = self._planned_from_checkpoint()
            return list(self._planned_queue_cache)

        refresh_every = max(1, int(self.cfg.objective_planner.refresh_every_generations))
        if (
            (not force)
            and self._planned_queue_cache
            and self._planned_queue_last_refresh_generation >= 0
            and (self._checkpoint.loop_cursor - self._planned_queue_last_refresh_generation) < refresh_every
        ):
            return list(self._planned_queue_cache)

        completed = set(self._checkpoint.population_state.get("completed_objectives", []))
        planned = self.objective_planner.plan(signal_payload=signal_payload, completed_ids=completed)
        self._planned_queue_cache = planned
        self._planned_queue_last_refresh_generation = self._checkpoint.loop_cursor
        self._checkpoint.population_state["planned_objectives"] = [item.to_dict() for item in planned]
        return list(planned)

    def _reload_objective_planner(self) -> None:
        if not bool(self.cfg.objective_planner.enabled):
            self.objective_planner = None
            self._objective_planner_error = "disabled_by_config"
            return
        try:
            self.objective_planner = ObjectivePlanner.load(
                self.objective_planner_path,
                rolling_window_size=self.cfg.objective_planner.rolling_window_size,
            )
            self._objective_planner_error = ""
        except Exception as exc:  # noqa: BLE001
            self.objective_planner = None
            self._objective_planner_error = f"planner_load_error:{exc}"

    def _objective_planner_status(self, *, signal_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        queue = self._planned_queue_cache or self._planned_from_checkpoint()
        payload: dict[str, Any] = {
            "enabled": bool(self.cfg.objective_planner.enabled),
            "active": bool(self.objective_planner is not None),
            "error": self._objective_planner_error,
            "mapping_file": str(self.objective_planner_path),
            "rolling_window_size": int(self.cfg.objective_planner.rolling_window_size),
            "queue_size": len(queue),
            "queue": [item.to_dict() for item in queue],
        }
        if signal_payload:
            payload["signal_available"] = True
        else:
            payload["signal_available"] = False
        return payload

    def _wiki_sync_status_payload(self) -> dict[str, Any]:
        return dict(self._wiki_sync_status)

    def _game_input_status_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": bool(self.cfg.game_input.enabled),
            "active": False,
            "ok": bool(self.cfg.game_input.enabled),
            "reason": "disabled_by_config" if not bool(self.cfg.game_input.enabled) else "status_unavailable",
            "status_file": str(self.game_input_status_file),
        }
        if not bool(self.cfg.game_input.enabled):
            return payload
        if not self.game_input_status_file.exists():
            return payload
        try:
            row = json.loads(self.game_input_status_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            payload["ok"] = False
            payload["reason"] = f"status_parse_error:{exc}"
            return payload
        if not isinstance(row, dict):
            payload["ok"] = False
            payload["reason"] = "status_invalid_type"
            return payload

        merged = dict(payload)
        merged.update(row)
        merged["enabled"] = bool(self.cfg.game_input.enabled)
        merged["active"] = True
        agent_error = merged.get("error") or merged.get("last_error")
        if agent_error:
            merged["ok"] = False
            merged["reason"] = f"agent_error:{agent_error}"
        elif merged.get("decision_reason"):
            merged["reason"] = str(merged.get("decision_reason"))
        else:
            merged["reason"] = "ok" if bool(merged.get("ok", True)) else "agent_reported_not_ok"
        if "status_file" not in merged:
            merged["status_file"] = str(self.game_input_status_file)
        return merged

    def _maybe_wiki_sync(self) -> None:
        if self._wiki_syncer is None:
            return
        now_mono = time.monotonic()
        interval_s = max(1, int(self.cfg.wiki_sync.interval_minutes)) * 60.0
        if self._wiki_sync_last_mono > 0.0 and (now_mono - self._wiki_sync_last_mono) < interval_s:
            return

        self._wiki_sync_last_mono = now_mono
        try:
            result = self._wiki_syncer.sync()
            status = result.to_dict()
            status["enabled"] = True
            status["active"] = True
            status["last_synced_at"] = status.get("synced_at", "")
            status["sources_file"] = str(self.wiki_sources_path)
            status["mapping_file"] = str(self.wiki_mapping_path)
            self._wiki_sync_status = status

            if bool(result.changed):
                self._reload_objective_planner()
                self._planned_queue_cache = []
                self._planned_queue_last_refresh_generation = -1
                self._append_event(
                    phase="objective_planner",
                    event_type="wiki_sync_refreshed",
                    severity="info",
                    payload={
                        "changed": True,
                        "synced_at": result.synced_at,
                        "totals": result.totals,
                    },
                )
        except Exception as exc:  # noqa: BLE001
            self._wiki_sync_status = {
                "enabled": True,
                "active": True,
                "ok": False,
                "changed": False,
                "reason": f"sync_error:{exc}",
                "last_synced_at": utc_now_iso(),
                "sources_file": str(self.wiki_sources_path),
                "mapping_file": str(self.wiki_mapping_path),
            }

    def _planner_heartbeat_signature(self) -> str:
        queue = self._planned_queue_cache or self._planned_from_checkpoint()
        parts = [item.objective.id for item in queue]
        return "|".join(parts)

    def _emit_objective_planner_heartbeat(self, *, signal_payload: dict[str, Any] | None = None) -> None:
        if not bool(self.cfg.objective_planner.enabled):
            return
        now_mono = time.monotonic()
        interval = max(5, int(self.cfg.objective_planner.heartbeat_interval_seconds))
        signature = self._planner_heartbeat_signature()
        if (now_mono - self._planner_heartbeat_last_mono) < interval and signature == self._planner_heartbeat_last_signature:
            return

        queue = self._planned_queue_cache or self._planned_from_checkpoint()
        completed = set(self._checkpoint.population_state.get("completed_objectives", []))
        next_obj = self._next_objective(completed=completed, planned_queue=queue)

        row = {
            "ts": utc_now_iso(),
            "generation": int(self._checkpoint.loop_cursor),
            "safe_pause": bool(self._checkpoint.safe_pause),
            "safe_pause_reason": str(self._checkpoint.safe_pause_reason),
            "signal_available": bool(signal_payload),
            "queue_size": len(queue),
            "queue_ids": [item.objective.id for item in queue],
            "next_objective_id": (next_obj.id if next_obj is not None else None),
            "next_objective_signal": (next_obj.unlock_signal if next_obj is not None else None),
            "progress_watchdog": self._progress_watchdog_status(),
            "wiki_sync": self._wiki_sync_status_payload(),
        }
        self.objective_planner_heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        with self.objective_planner_heartbeat_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")

        self._planner_heartbeat_last_mono = now_mono
        self._planner_heartbeat_last_signature = signature

    def _next_objective(
        self,
        *,
        completed: set[str],
        planned_queue: list[PlannedObjective],
    ) -> Objective | None:
        for item in planned_queue:
            if item.objective.id not in completed:
                return item.objective
        return self.objectives.next_objective(completed)

    def _progress_watchdog_status(self) -> dict[str, Any]:
        status = {
            "enabled": bool(self.cfg.live.enabled and self.cfg.live.progress_training_mode),
            "ok": True,
            "stale": False,
            "reason": "disabled",
            "save_data_path": "",
            "save_data_age_seconds": None,
            "pause_threshold_seconds": None,
        }
        if not status["enabled"]:
            return status

        raw = str(self.cfg.live.save_data_path or "").strip()
        if not raw:
            status["ok"] = False
            status["reason"] = "save_data_path_unset"
            return status

        path = self.cfg.resolve(raw)
        status["save_data_path"] = str(path)
        if not path.exists():
            status["ok"] = False
            status["reason"] = "save_data_missing"
            return status

        age_s = max(0.0, time.time() - path.stat().st_mtime)
        pause_threshold_s = max(0.0, float(self.cfg.live.progress_stale_pause_minutes) * 60.0)
        stale = pause_threshold_s > 0.0 and age_s > pause_threshold_s
        status["save_data_age_seconds"] = float(age_s)
        status["pause_threshold_seconds"] = float(pause_threshold_s)
        status["stale"] = bool(stale)
        status["ok"] = not bool(stale)
        status["reason"] = "ok" if not stale else f"save_data_stale:{age_s:.1f}s>{pause_threshold_s:.1f}s"
        return status

    def _set_safe_pause(self, reason: str) -> None:
        with self._state_lock:
            self._checkpoint.safe_pause = True
            self._checkpoint.safe_pause_reason = reason
            self.registry.save_checkpoint(self._checkpoint)
        self.bridge.request_pause(reason)
        self._append_event(
            phase="safety",
            event_type="safe_pause_set",
            severity="critical",
            payload={"reason": reason},
        )

    def _clear_safe_pause(self) -> None:
        with self._state_lock:
            self._checkpoint.safe_pause = False
            self._checkpoint.safe_pause_reason = ""
            self.registry.save_checkpoint(self._checkpoint)
        self.bridge.request_resume()

    def _bootstrap(self) -> PolicyRecord:
        baseline = self.registry.bootstrap_baseline()
        if not self._checkpoint.active_policy_id:
            self._checkpoint.active_policy_id = baseline.policy_id
            self.registry.save_checkpoint(self._checkpoint)
        self._append_event(
            phase="bootstrap",
            event_type="initialized",
            severity="info",
            payload={"active_policy_id": self._checkpoint.active_policy_id},
        )
        return baseline

    def _update_objective_progress(
        self,
        champion: SimBatchMetrics,
        *,
        signal_payload: dict[str, Any] | None = None,
        planned_queue: list[PlannedObjective] | None = None,
    ) -> str | None:
        completed = set(self._checkpoint.population_state.get("completed_objectives", []))
        if planned_queue is None:
            planned_queue = self._planned_queue_cache or self._planned_from_checkpoint()
        next_obj = self._next_objective(completed=completed, planned_queue=planned_queue)
        if next_obj is None:
            return None
        if signal_payload is None:
            signal_payload = self._objective_signal_payload()
        signal_match = objective_unlock_met(next_obj.unlock_signal, signal_payload)
        objective_met = signal_match if signal_match is not None else (champion.objective_rate >= 0.65)
        if objective_met:
            completed.add(next_obj.id)
            self._checkpoint.population_state["completed_objectives"] = sorted(completed)
            return next_obj.id
        return None

    def _objective_signal_payload(self) -> dict[str, Any]:
        path = self.cfg.resolve(self.cfg.live.memory_signal_file)
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        if not isinstance(payload, dict):
            return {}
        if bool(payload.get("blocked", False)):
            return {}
        return payload

    def _unlock_progress_snapshot(self, *, signal_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = signal_payload if signal_payload is not None else self._objective_signal_payload()
        if not payload:
            return {}
        return {
            "collection_entries": payload.get("collection_entries"),
            "collection_target": payload.get("collection_target"),
            "collection_ratio": payload.get("collection_ratio"),
            "collection_entries_delta": payload.get("collection_entries_delta"),
            "collection_ratio_delta": payload.get("collection_ratio_delta"),
            "bestiary_entries": payload.get("bestiary_entries"),
            "bestiary_target": payload.get("bestiary_target"),
            "bestiary_ratio": payload.get("bestiary_ratio"),
            "bestiary_entries_delta": payload.get("bestiary_entries_delta"),
            "bestiary_ratio_delta": payload.get("bestiary_ratio_delta"),
            "steam_achievements": payload.get("steam_achievements"),
            "steam_achievements_target": payload.get("steam_achievements_target"),
            "steam_achievements_ratio": payload.get("steam_achievements_ratio"),
            "steam_achievements_delta": payload.get("steam_achievements_delta"),
            "steam_achievements_ratio_delta": payload.get("steam_achievements_ratio_delta"),
            "unlocked_characters_count": payload.get("unlocked_characters_count"),
            "unlocked_characters": payload.get("unlocked_characters"),
            "unlocked_characters_count_delta": payload.get("unlocked_characters_count_delta"),
            "unlocked_arcanas_count": payload.get("unlocked_arcanas_count"),
            "unlocked_arcanas": payload.get("unlocked_arcanas"),
            "unlocked_arcanas_count_delta": payload.get("unlocked_arcanas_count_delta"),
            "unlocked_weapons_count": payload.get("unlocked_weapons_count"),
            "unlocked_weapons": payload.get("unlocked_weapons"),
            "unlocked_weapons_count_delta": payload.get("unlocked_weapons_count_delta"),
            "unlocked_passives_count": payload.get("unlocked_passives_count"),
            "unlocked_passives": payload.get("unlocked_passives"),
            "unlocked_passives_count_delta": payload.get("unlocked_passives_count_delta"),
            "unlocked_stages_count": payload.get("unlocked_stages_count"),
            "unlocked_stages": payload.get("unlocked_stages"),
            "unlocked_stages_count_delta": payload.get("unlocked_stages_count_delta"),
            "triad_progress_delta_score": payload.get("triad_progress_delta_score"),
            "triad_progress_any_gain": payload.get("triad_progress_any_gain"),
            "save_data_age_seconds": payload.get("save_data_age_seconds"),
            "save_data_stale": payload.get("save_data_stale"),
            "save_data_path": payload.get("save_data_path"),
        }

    def _active_policy(self) -> PolicyRecord:
        active = self.registry.get_policy(self._checkpoint.active_policy_id)
        if active is None:
            active = self.registry.bootstrap_baseline()
            self._checkpoint.active_policy_id = active.policy_id
        return active

    def _handle_regression_window(self, active_score: float) -> tuple[bool, str]:
        counters = dict(self._checkpoint.failure_counters)
        prev = float(counters.get("last_active_score", 0.0))
        windows = int(counters.get("regression_windows", 0))

        regressed = False
        if prev > 0.0:
            regressed = active_score < (prev * 0.90)

        if regressed:
            windows += 1
        else:
            windows = 0

        counters["regression_windows"] = windows
        counters["last_active_score"] = float(active_score)
        self._checkpoint.failure_counters = counters

        limit = self.cfg.automation.regression_windows_before_rollback
        if windows >= limit:
            last_stable = self.registry.get_last_stable_policy()
            if last_stable and last_stable != self._checkpoint.active_policy_id:
                self._checkpoint.active_policy_id = last_stable
                self.registry.set_active_policy(last_stable)
                counters["regression_windows"] = 0
                self._checkpoint.failure_counters = counters
                return True, f"rollback_to_{last_stable}"
        return False, "no_rollback"

    def _run_generation(self, *, seed: int) -> dict[str, Any]:
        active = self._active_policy()
        objective_signal = self._augment_signal_with_unlock_deltas(self._objective_signal_payload())
        planned_queue = self._refresh_objective_queue(signal_payload=objective_signal)
        effective_scoring, scoring_profile = objective_biased_scoring(self.cfg.scoring, objective_signal)
        population = self.tuner.generate_population(active.parameters, generation_seed=seed)

        eval_results = self.tuner.evaluate_population(
            population,
            episodes=self._runtime_knobs.batch_sim_episodes,
            seed_base=seed,
            max_workers=self._runtime_knobs.max_parallel_workers,
            scoring=effective_scoring,
            on_episode=self._checkpoint_episode_increment,
        )
        self._last_backend = eval_results[0].backend if eval_results else self._last_backend

        top_k = eval_results[: self.cfg.automation.keep_top_k]
        champion = top_k[0]
        baseline_result = next((x for x in eval_results if x.candidate_id == "baseline"), champion)

        baseline_canary_metrics, _, _ = self.simulator.run_batch(
            parameters=active.parameters,
            episodes=self._runtime_knobs.canary_sim_episodes,
            seed=seed + 100000,
            on_episode=lambda _ep: self._checkpoint_episode_increment(),
        )
        candidate_canary_metrics, _, _ = self.simulator.run_batch(
            parameters=champion.parameters,
            episodes=self._runtime_knobs.canary_sim_episodes,
            seed=seed + 200000,
            on_episode=lambda _ep: self._checkpoint_episode_increment(),
        )

        baseline_canary_score = weighted_score(baseline_canary_metrics, effective_scoring).total
        candidate_canary_score = weighted_score(candidate_canary_metrics, effective_scoring).total

        baseline_live = self.live_runner.canary(
            parameters=active.parameters,
            runs=self._runtime_knobs.canary_live_runs,
            seed=seed + 300000,
        )
        candidate_live = self.live_runner.canary(
            parameters=champion.parameters,
            runs=self._runtime_knobs.canary_live_runs,
            seed=seed + 400000,
        )

        decision = strict_canary_decision(
            candidate_metrics=candidate_canary_metrics,
            baseline_metrics=baseline_canary_metrics,
            candidate_live=candidate_live,
            baseline_live=baseline_live,
            required_improvement=self.cfg.automation.required_improvement,
            max_stability_regression=self.cfg.automation.max_stability_regression,
            candidate_score=candidate_canary_score,
            baseline_score=baseline_canary_score,
        )

        promotion_state = "REJECTED"
        promoted_policy_id = active.policy_id
        if decision.promote:
            promotion_state = "SIM_PROMOTED_LIVE_DEFERRED" if decision.live_deferred else "PROMOTED_ACTIVE"
            promoted = self.registry.save_policy(
                parameters=champion.parameters,
                parent_policy_id=active.policy_id,
                sim_metrics=candidate_canary_metrics.to_dict(),
                promotion_state=promotion_state,
                score=candidate_canary_score,
                live_metrics=candidate_live.to_dict(),
            )
            self.registry.set_active_policy(promoted.policy_id)
            self._checkpoint.active_policy_id = promoted.policy_id
            promoted_policy_id = promoted.policy_id
            if not decision.live_deferred:
                self.registry.set_last_stable_policy(promoted.policy_id)
        else:
            self.registry.save_policy(
                parameters=champion.parameters,
                parent_policy_id=active.policy_id,
                sim_metrics=candidate_canary_metrics.to_dict(),
                promotion_state="REJECTED",
                score=candidate_canary_score,
                live_metrics=candidate_live.to_dict(),
            )

        rollback, rollback_reason = self._handle_regression_window(baseline_result.score)
        if rollback:
            promotion_state = f"{promotion_state}|{rollback_reason}"

        objective_hit = self._update_objective_progress(
            candidate_canary_metrics,
            signal_payload=objective_signal,
            planned_queue=planned_queue,
        )

        self._checkpoint.loop_cursor += 1
        self._checkpoint.last_success_ts = utc_now_iso()
        self.registry.save_checkpoint(self._checkpoint)

        summary = {
            "generated_at": utc_now_iso(),
            "generation": self._checkpoint.loop_cursor,
            "active_policy_id": self._checkpoint.active_policy_id,
            "promoted_policy_id": promoted_policy_id,
            "promotion_state": promotion_state,
            "decision": decision.to_dict(),
            "objective_hit": objective_hit,
            "unlock_progress": self._unlock_progress_snapshot(signal_payload=objective_signal),
            "unlock_trend": {
                "collection_entries_delta": objective_signal.get("collection_entries_delta"),
                "bestiary_entries_delta": objective_signal.get("bestiary_entries_delta"),
                "steam_achievements_delta": objective_signal.get("steam_achievements_delta"),
                "triad_progress_delta_score": objective_signal.get("triad_progress_delta_score"),
                "triad_progress_any_gain": objective_signal.get("triad_progress_any_gain"),
            },
            "scoring_profile": scoring_profile,
            "sim_backend": self._last_backend,
            "population_size": len(population),
            "top_k": [
                {
                    "candidate_id": r.candidate_id,
                    "score": r.score,
                    "parameters": r.parameters.to_dict(),
                    "metrics": r.metrics.to_dict(),
                    "backend": r.backend,
                }
                for r in top_k
            ],
            "baseline_canary": baseline_canary_metrics.to_dict(),
            "candidate_canary": candidate_canary_metrics.to_dict(),
            "baseline_live": baseline_live.to_dict(),
            "candidate_live": candidate_live.to_dict(),
            "rollback": rollback,
            "rollback_reason": rollback_reason,
            "safe_pause": self._checkpoint.safe_pause,
            "safe_pause_reason": self._checkpoint.safe_pause_reason,
            "runtime_knobs": self._runtime_knobs.to_dict(),
            "progress_watchdog": self._progress_watchdog_status(),
            "objective_planner": self._objective_planner_status(signal_payload=objective_signal),
            "wiki_sync": self._wiki_sync_status_payload(),
            "game_input": self._game_input_status_payload(),
        }
        return summary

    def run(
        self,
        *,
        max_generations: int = 0,
        api_host: str = "127.0.0.1",
        api_port: int = 8787,
        enable_api: bool = True,
    ) -> OrchestratorRunResult:
        self._bootstrap()
        self._heartbeat_stop.clear()
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="checkpoint-heartbeat", daemon=True)
        heartbeat_thread.start()

        if enable_api:
            self._api_server, self._api_thread = start_api_server(self.bridge, host=api_host, port=api_port)
        else:
            self._api_server, self._api_thread = None, None

        stop_reason = "unknown"
        attempt = 0

        try:
            while True:
                if self.bridge.consume_stop():
                    stop_reason = "api_stop"
                    break
                if max_generations > 0 and self._checkpoint.loop_cursor >= max_generations:
                    stop_reason = "max_generations_reached"
                    break

                snapshot = self.bridge.snapshot()
                self._maybe_wiki_sync()
                signal_payload = self._objective_signal_payload()
                if signal_payload:
                    self._refresh_objective_queue(signal_payload=signal_payload, force=True)
                self._emit_objective_planner_heartbeat(signal_payload=signal_payload)
                watchdog = self._progress_watchdog_status()

                # Auto-hold progression training when save data is stale to avoid optimizing against stale state.
                if bool(watchdog.get("enabled")) and not bool(watchdog.get("ok", True)):
                    reason = f"SAFE_PAUSE:{watchdog.get('reason', 'save_data_stale')}"
                    if not self._checkpoint.safe_pause:
                        self._set_safe_pause(reason)
                    self._update_health(state="SAFE_PAUSE", note=str(watchdog.get("reason", "save_data_stale")))
                    time.sleep(max(0.2, self._runtime_knobs.loop_sleep_seconds))
                    continue

                if (
                    bool(watchdog.get("enabled"))
                    and bool(watchdog.get("ok", True))
                    and self._checkpoint.safe_pause
                    and str(self._checkpoint.safe_pause_reason).startswith("SAFE_PAUSE:save_data_stale")
                    and (not snapshot["safe_pause"])
                ):
                    self._clear_safe_pause()

                if snapshot["safe_pause"] and not self._checkpoint.safe_pause:
                    self._set_safe_pause(snapshot["safe_pause_reason"] or "manual_pause")
                elif (not snapshot["safe_pause"]) and self._checkpoint.safe_pause:
                    self._clear_safe_pause()

                if self._checkpoint.safe_pause:
                    self._update_health(state="SAFE_PAUSE", note=self._checkpoint.safe_pause_reason)
                    time.sleep(max(0.2, self._runtime_knobs.loop_sleep_seconds))
                    continue

                self._generation += 1
                seed = int(time.time() * 1000) + self._generation

                try:
                    summary = self._run_generation(seed=seed)
                    recoveries = self.safety.recovery_count()
                    self._runtime_knobs, autotune_decision = self._autotuner.observe_generation(
                        summary=summary,
                        recoveries_30m=recoveries,
                    )
                    self._autotune_status = self._autotuner.status_payload()
                    summary["runtime_knobs"] = self._runtime_knobs.to_dict()
                    summary["autotune"] = autotune_decision
                    attempt = 0
                    self._last_error = ""
                    self._update_summary(summary)
                    if autotune_decision.get("action") not in {"none"}:
                        self._append_event(
                            phase="autotune",
                            event_type=str(autotune_decision.get("action", "none")),
                            severity="info",
                            payload={
                                "reason": autotune_decision.get("reason", ""),
                                "current_knobs": autotune_decision.get("current_knobs", {}),
                                "guardrail_state": autotune_decision.get("guardrail_state", {}),
                                "cpu_snapshot": autotune_decision.get("cpu_snapshot", {}),
                            },
                        )
                    self._append_event(
                        phase="generation",
                        event_type="completed",
                        severity="info",
                        payload={
                            "generation": self._checkpoint.loop_cursor,
                            "active_policy_id": self._checkpoint.active_policy_id,
                            "promotion_state": summary.get("promotion_state", ""),
                        },
                    )
                    self._update_health(state="RUNNING", note="generation_complete")
                except Exception as exc:  # noqa: BLE001
                    attempt += 1
                    self._last_error = str(exc)
                    self.safety.record_recovery()
                    recoveries = self.safety.recovery_count()
                    self._append_event(
                        phase="generation",
                        event_type="recovery",
                        severity="warning",
                        payload={
                            "attempt": attempt,
                            "error": str(exc),
                            "recoveries_30m": recoveries,
                        },
                    )

                    if self.safety.crash_loop_triggered():
                        self._set_safe_pause("SAFE_PAUSE:crash_loop_threshold_exceeded")
                        self._update_health(state="SAFE_PAUSE", note="crash_loop_threshold_exceeded")
                        continue

                    backoff = self.safety.backoff_seconds(attempt - 1)
                    self._update_health(state="RECOVERING", note=f"retry_in_{backoff}s")
                    time.sleep(max(1, backoff))
                    continue

                time.sleep(max(0.2, float(self._runtime_knobs.loop_sleep_seconds)))
        finally:
            self._heartbeat_stop.set()
            heartbeat_thread.join(timeout=2.0)
            if self._api_server is not None:
                try:
                    self._api_server.shutdown()
                    self._api_server.server_close()
                except Exception:
                    pass
            self._update_health(state="STOPPED", note=stop_reason)

        return OrchestratorRunResult(
            generations_completed=self._checkpoint.loop_cursor,
            stop_reason=stop_reason,
            active_policy_id=self._checkpoint.active_policy_id,
            safe_pause=self._checkpoint.safe_pause,
        )

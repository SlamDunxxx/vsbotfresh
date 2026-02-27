from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class RuntimeConfig:
    state_dir: str
    log_dir: str
    events_file: str
    database_path: str
    checkpoint_interval_seconds: int
    max_parallel_workers: int
    loop_sleep_seconds: float


@dataclass(frozen=True)
class AutomationConfig:
    run_forever: bool
    default_mode: str
    max_candidates_per_generation: int
    keep_top_k: int
    batch_sim_episodes: int
    canary_sim_episodes: int
    canary_live_runs: int
    required_improvement: float
    max_stability_regression: float
    regression_windows_before_rollback: int


@dataclass(frozen=True)
class SafetyConfig:
    crash_loop_limit: int
    crash_loop_window_minutes: int
    backoff_seconds: list[int]
    allow_destructive_actions: bool


@dataclass(frozen=True)
class LiveConfig:
    enabled: bool
    memory_backend: str
    memory_signal_file: str
    memory_signal_max_age_seconds: float
    save_data_path: str
    progress_training_mode: bool
    save_data_stale_minutes: float
    progress_stale_pause_minutes: float


@dataclass(frozen=True)
class ReportingConfig:
    summary_dir: str
    site_dir: str
    site_data_dir: str
    status_file: str
    latest_summary_file: str


@dataclass(frozen=True)
class ScoringConfig:
    objective_completion_weight: float
    time_to_unlock_weight: float
    stability_weight: float
    objective_bias_enabled: bool = True
    objective_bias_strength: float = 0.75
    collection_gain_weight: float = 0.45
    bestiary_gain_weight: float = 0.30
    achievement_gain_weight: float = 0.25


@dataclass(frozen=True)
class AutotuneConfig:
    enabled: bool
    mode: str
    interval_seconds: int
    cpu_target_min: float
    cpu_target_max: float
    max_workers_cap: int
    min_workers_floor: int
    quality_guardrail_mode: str
    shadow_min_minutes: int
    shadow_min_generations: int
    cooldown_minutes: int
    episode_floor_batch: int
    episode_floor_canary_sim: int
    episode_floor_canary_live: int
    episode_cap_batch: int
    episode_cap_canary_sim: int
    episode_cap_canary_live: int


@dataclass(frozen=True)
class ObjectivePlannerConfig:
    enabled: bool
    mapping_file: str
    rolling_window_size: int
    refresh_every_generations: int
    heartbeat_log_file: str
    heartbeat_interval_seconds: int


@dataclass(frozen=True)
class WikiSyncConfig:
    enabled: bool
    interval_minutes: int
    sources_file: str
    mapping_file: str
    request_timeout_seconds: float


@dataclass(frozen=True)
class GameInputConfig:
    enabled: bool
    app_name: str
    watch_interval_seconds: float
    pause_when_unfocused: bool
    require_arm_file: bool
    arm_file: str
    gameplay_enabled: bool
    gameplay_interval_seconds: float
    gameplay_hold_seconds: float
    gameplay_sequence: list[str]
    gameplay_confirm_enabled: bool
    gameplay_confirm_interval_seconds: float
    gameplay_confirm_key: str
    menu_detection_enabled: bool
    menu_scan_interval_seconds: float
    fsm_transition_confirm_seconds: float
    min_save_data_age_seconds: float
    nudge_cooldown_seconds: float
    stuck_watchdog_enabled: bool
    stuck_window_seconds: float
    stuck_min_save_data_age_seconds: float
    stuck_recovery_interval_seconds: float
    max_nudges_per_session: int
    key_delay_seconds: float
    title_nudge_sequence: list[str]
    auto_launch_when_not_running: bool
    auto_launch_cooldown_seconds: float
    auto_launch_command: str
    objective_stale_threshold_seconds: float
    status_file: str
    dry_run: bool


@dataclass(frozen=True)
class AppConfig:
    project_root: Path
    runtime: RuntimeConfig
    automation: AutomationConfig
    safety: SafetyConfig
    live: LiveConfig
    reporting: ReportingConfig
    scoring: ScoringConfig
    autotune: AutotuneConfig
    objective_planner: ObjectivePlannerConfig
    wiki_sync: WikiSyncConfig
    game_input: GameInputConfig

    def resolve(self, rel_or_abs: str) -> Path:
        expanded = os.path.expandvars(str(rel_or_abs))
        path = Path(expanded).expanduser()
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()


def _int_list(raw: object) -> list[int]:
    if not isinstance(raw, list):
        return [5, 15, 45, 120, 300]
    out: list[int] = []
    for item in raw:
        try:
            out.append(int(item))
        except Exception:
            continue
    return out or [5, 15, 45, 120, 300]


def _str_list(raw: object, *, default: list[str]) -> list[str]:
    if not isinstance(raw, list):
        return list(default)
    out: list[str] = []
    for item in raw:
        token = str(item).strip().lower()
        if token:
            out.append(token)
    return out or list(default)


def _detect_project_root(cfg_path: Path) -> Path:
    direct_parent = cfg_path.parent
    if direct_parent.name == "config":
        return direct_parent.parent.resolve()

    for candidate in [direct_parent, *direct_parent.parents]:
        if (candidate / "src" / "vs_overseer").exists():
            return candidate.resolve()
    return direct_parent.resolve()


def load_config(path: str | Path) -> AppConfig:
    cfg_path = Path(path).expanduser().resolve()
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config file not found: {cfg_path}")

    with cfg_path.open("rb") as fh:
        payload = tomllib.load(fh)

    runtime = payload.get("runtime", {})
    automation = payload.get("automation", {})
    safety = payload.get("safety", {})
    live = payload.get("live", {})
    reporting = payload.get("reporting", {})
    scoring = payload.get("scoring", {})
    autotune = payload.get("autotune", {})
    objective_planner = payload.get("objective_planner", {})
    wiki_sync = payload.get("wiki_sync", {})
    game_input = payload.get("game_input", {})

    project_root = _detect_project_root(cfg_path)

    return AppConfig(
        project_root=project_root,
        runtime=RuntimeConfig(
            state_dir=str(runtime.get("state_dir", "runtime")),
            log_dir=str(runtime.get("log_dir", "runtime/logs")),
            events_file=str(runtime.get("events_file", "runtime/events/run_events.jsonl")),
            database_path=str(runtime.get("database_path", "runtime/state.db")),
            checkpoint_interval_seconds=int(runtime.get("checkpoint_interval_seconds", 30)),
            max_parallel_workers=max(1, int(runtime.get("max_parallel_workers", 4))),
            loop_sleep_seconds=float(runtime.get("loop_sleep_seconds", 1.0)),
        ),
        automation=AutomationConfig(
            run_forever=bool(automation.get("run_forever", True)),
            default_mode=str(automation.get("default_mode", "unattended")),
            max_candidates_per_generation=max(2, int(automation.get("max_candidates_per_generation", 16))),
            keep_top_k=max(1, int(automation.get("keep_top_k", 8))),
            batch_sim_episodes=max(4, int(automation.get("batch_sim_episodes", 24))),
            canary_sim_episodes=max(10, int(automation.get("canary_sim_episodes", 50))),
            canary_live_runs=max(1, int(automation.get("canary_live_runs", 10))),
            required_improvement=float(automation.get("required_improvement", 0.03)),
            max_stability_regression=float(automation.get("max_stability_regression", 0.02)),
            regression_windows_before_rollback=max(1, int(automation.get("regression_windows_before_rollback", 2))),
        ),
        safety=SafetyConfig(
            crash_loop_limit=max(1, int(safety.get("crash_loop_limit", 6))),
            crash_loop_window_minutes=max(1, int(safety.get("crash_loop_window_minutes", 30))),
            backoff_seconds=_int_list(safety.get("backoff_seconds", [5, 15, 45, 120, 300])),
            allow_destructive_actions=bool(safety.get("allow_destructive_actions", False)),
        ),
        live=LiveConfig(
            enabled=bool(live.get("enabled", False)),
            memory_backend=str(live.get("memory_backend", "auto")),
            memory_signal_file=str(live.get("memory_signal_file", "runtime/live/memory_signal.json")),
            memory_signal_max_age_seconds=float(live.get("memory_signal_max_age_seconds", 20.0)),
            save_data_path=str(live.get("save_data_path", "")),
            progress_training_mode=bool(live.get("progress_training_mode", False)),
            save_data_stale_minutes=max(0.0, float(live.get("save_data_stale_minutes", 30.0))),
            progress_stale_pause_minutes=max(0.0, float(live.get("progress_stale_pause_minutes", 30.0))),
        ),
        reporting=ReportingConfig(
            summary_dir=str(reporting.get("summary_dir", "runtime/summaries")),
            site_dir=str(reporting.get("site_dir", "site")),
            site_data_dir=str(reporting.get("site_data_dir", "site/data")),
            status_file=str(reporting.get("status_file", "site/data/health.json")),
            latest_summary_file=str(reporting.get("latest_summary_file", "site/data/latest_summary.json")),
        ),
        scoring=ScoringConfig(
            objective_completion_weight=float(scoring.get("objective_completion_weight", 0.6)),
            time_to_unlock_weight=float(scoring.get("time_to_unlock_weight", 0.25)),
            stability_weight=float(scoring.get("stability_weight", 0.15)),
            objective_bias_enabled=bool(scoring.get("objective_bias_enabled", True)),
            objective_bias_strength=max(0.0, float(scoring.get("objective_bias_strength", 0.75))),
            collection_gain_weight=max(0.0, float(scoring.get("collection_gain_weight", 0.45))),
            bestiary_gain_weight=max(0.0, float(scoring.get("bestiary_gain_weight", 0.30))),
            achievement_gain_weight=max(0.0, float(scoring.get("achievement_gain_weight", 0.25))),
        ),
        autotune=AutotuneConfig(
            enabled=bool(autotune.get("enabled", False)),
            mode=str(autotune.get("mode", "off")).strip().lower(),
            interval_seconds=max(15, int(autotune.get("interval_seconds", 120))),
            cpu_target_min=max(0.0, min(1.0, float(autotune.get("cpu_target_min", 0.7)))),
            cpu_target_max=max(0.0, min(1.0, float(autotune.get("cpu_target_max", 0.85)))),
            max_workers_cap=max(1, int(autotune.get("max_workers_cap", 8))),
            min_workers_floor=max(1, int(autotune.get("min_workers_floor", 2))),
            quality_guardrail_mode=str(autotune.get("quality_guardrail_mode", "protect_quality")),
            shadow_min_minutes=max(0, int(autotune.get("shadow_min_minutes", 60))),
            shadow_min_generations=max(0, int(autotune.get("shadow_min_generations", 1000))),
            cooldown_minutes=max(0, int(autotune.get("cooldown_minutes", 10))),
            episode_floor_batch=max(4, int(autotune.get("episode_floor_batch", 8))),
            episode_floor_canary_sim=max(10, int(autotune.get("episode_floor_canary_sim", 30))),
            episode_floor_canary_live=max(1, int(autotune.get("episode_floor_canary_live", 5))),
            episode_cap_batch=max(4, int(autotune.get("episode_cap_batch", 96))),
            episode_cap_canary_sim=max(10, int(autotune.get("episode_cap_canary_sim", 160))),
            episode_cap_canary_live=max(1, int(autotune.get("episode_cap_canary_live", 40))),
        ),
        objective_planner=ObjectivePlannerConfig(
            enabled=bool(objective_planner.get("enabled", False)),
            mapping_file=str(objective_planner.get("mapping_file", "config/wiki_progression.json")),
            rolling_window_size=max(1, int(objective_planner.get("rolling_window_size", 6))),
            refresh_every_generations=max(1, int(objective_planner.get("refresh_every_generations", 1))),
            heartbeat_log_file=str(
                objective_planner.get("heartbeat_log_file", "runtime/logs/objective_planner_heartbeat.log")
            ),
            heartbeat_interval_seconds=max(5, int(objective_planner.get("heartbeat_interval_seconds", 30))),
        ),
        wiki_sync=WikiSyncConfig(
            enabled=bool(wiki_sync.get("enabled", False)),
            interval_minutes=max(1, int(wiki_sync.get("interval_minutes", 120))),
            sources_file=str(wiki_sync.get("sources_file", "config/wiki_sources.json")),
            mapping_file=str(wiki_sync.get("mapping_file", "config/wiki_progression.json")),
            request_timeout_seconds=max(1.0, float(wiki_sync.get("request_timeout_seconds", 8.0))),
        ),
        game_input=GameInputConfig(
            enabled=bool(game_input.get("enabled", False)),
            app_name=str(game_input.get("app_name", "Vampire Survivors")),
            watch_interval_seconds=max(0.2, float(game_input.get("watch_interval_seconds", 10.0))),
            pause_when_unfocused=bool(game_input.get("pause_when_unfocused", True)),
            require_arm_file=bool(game_input.get("require_arm_file", True)),
            arm_file=str(game_input.get("arm_file", "runtime/live/game_input_arm.json")),
            gameplay_enabled=bool(game_input.get("gameplay_enabled", True)),
            gameplay_interval_seconds=max(0.2, float(game_input.get("gameplay_interval_seconds", 1.0))),
            gameplay_hold_seconds=max(0.05, float(game_input.get("gameplay_hold_seconds", 0.35))),
            gameplay_sequence=_str_list(
                game_input.get("gameplay_sequence", ["left", "up", "right", "down"]),
                default=["left", "up", "right", "down"],
            ),
            gameplay_confirm_enabled=bool(game_input.get("gameplay_confirm_enabled", True)),
            gameplay_confirm_interval_seconds=max(
                0.2, float(game_input.get("gameplay_confirm_interval_seconds", 2.5))
            ),
            gameplay_confirm_key=str(game_input.get("gameplay_confirm_key", "return")).strip().lower() or "return",
            menu_detection_enabled=bool(game_input.get("menu_detection_enabled", True)),
            menu_scan_interval_seconds=max(0.5, float(game_input.get("menu_scan_interval_seconds", 2.0))),
            fsm_transition_confirm_seconds=max(0.0, float(game_input.get("fsm_transition_confirm_seconds", 0.35))),
            min_save_data_age_seconds=max(0.0, float(game_input.get("min_save_data_age_seconds", 90.0))),
            nudge_cooldown_seconds=max(0.0, float(game_input.get("nudge_cooldown_seconds", 2700.0))),
            stuck_watchdog_enabled=bool(game_input.get("stuck_watchdog_enabled", True)),
            stuck_window_seconds=max(30.0, float(game_input.get("stuck_window_seconds", 300.0))),
            stuck_min_save_data_age_seconds=max(
                0.0, float(game_input.get("stuck_min_save_data_age_seconds", 180.0))
            ),
            stuck_recovery_interval_seconds=max(
                30.0, float(game_input.get("stuck_recovery_interval_seconds", 300.0))
            ),
            max_nudges_per_session=max(1, int(game_input.get("max_nudges_per_session", 8))),
            key_delay_seconds=max(0.05, float(game_input.get("key_delay_seconds", 0.55))),
            title_nudge_sequence=_str_list(
                game_input.get("title_nudge_sequence", ["return", "return", "return", "return", "return"]),
                default=["return", "return", "return", "return", "return"],
            ),
            auto_launch_when_not_running=bool(game_input.get("auto_launch_when_not_running", True)),
            auto_launch_cooldown_seconds=max(5.0, float(game_input.get("auto_launch_cooldown_seconds", 30.0))),
            auto_launch_command=str(game_input.get("auto_launch_command", "")),
            objective_stale_threshold_seconds=max(
                60.0, float(game_input.get("objective_stale_threshold_seconds", 900.0))
            ),
            status_file=str(game_input.get("status_file", "runtime/live/game_input_status.json")),
            dry_run=bool(game_input.get("dry_run", False)),
        ),
    )

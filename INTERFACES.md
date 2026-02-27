# Public Interfaces

## ObjectiveGraph (`config/objectives.json`)
Each objective object uses:
- `id`
- `name`
- `category`
- `prerequisites[]`
- `unlock_signal`
- `weight`
- `estimated_time_s`

## PolicyBundle (`policies/<policy_id>/manifest.json`)
- `policy_id`
- `parent_policy_id`
- `created_at`
- `parameters`
- `sim_metrics`
- `promotion_state`
- `score`
- `live_metrics`

## RunEvent (`runtime/events/run_events.jsonl`)
Each row:
- `ts`
- `phase`
- `event_type`
- `severity`
- `payload`

## Checkpoint (SQLite `checkpoints` table)
Columns:
- `loop_cursor`
- `active_policy_id`
- `population_state_json`
- `failure_counters_json`
- `last_success_ts`
- `safe_pause`
- `safe_pause_reason`

## Control API
- `POST /control/stop`
- `POST /control/pause`
- `POST /control/resume`
- `GET /health`
- `GET /summary/latest`

## Objective Planner
Summary/health payloads expose planner state:
- `objective_planner.enabled`
- `objective_planner.active`
- `objective_planner.error`
- `objective_planner.queue[]` (rolling achievable objectives from wiki mapping)
- `objective_planner.queue_size`
- heartbeat log rows in `runtime/logs/objective_planner_heartbeat.log`

## Wiki Sync
Summary/health payloads expose sync state:
- `wiki_sync.enabled`
- `wiki_sync.active`
- `wiki_sync.ok`
- `wiki_sync.changed`
- `wiki_sync.reason`
- `wiki_sync.totals`
- `wiki_sync.sources`

## Game Input
Summary/health payloads expose game-input daemon state:
- `game_input.enabled`
- `game_input.active`
- `game_input.ok`
- `game_input.action`
- `game_input.decision_reason`
- `game_input.safety_armed`
- `game_input.safety_reason`
- `game_input.effective_input_enabled`
- `game_input.pause_when_unfocused`
- `game_input.game_focused`
- `game_input.focus_state_reason`
- `game_input.focus_pause_active`
- `game_input.input_paused_reason`
- `game_input.frontmost_app_name`
- `game_input.frontmost_app_pid`
- `game_input.auto_launch_when_not_running`
- `game_input.auto_launch_cooldown_seconds`
- `game_input.auto_launch_action`
- `game_input.auto_launch_due`
- `game_input.auto_launch_error`
- `game_input.last_auto_launch_at`
- `game_input.last_auto_launch_error`
- `game_input.auto_launch_attempts`
- `game_input.fsm_state`
- `game_input.fsm_previous_state`
- `game_input.fsm_last_transition_reason`
- `game_input.fsm_last_transition_at`
- `game_input.fsm_blocked_transitions`
- `game_input.menu_state`
- `game_input.menu_state_reason`
- `game_input.in_run_recent`
- `game_input.last_in_run_seen_at`
- `game_input.unknown_in_run_grace_seconds`
- `game_input.menu_target_stage_key`
- `game_input.menu_target_stage_index`
- `game_input.menu_target_stage_reason`
- `game_input.menu_target_character_key`
- `game_input.menu_target_character_index`
- `game_input.menu_target_character_reason`
- `game_input.menu_unknown_has_menu_keywords`
- `game_input.menu_unknown_confirm_allowed`
- `game_input.menu_action`
- `game_input.nudges_sent`
- `game_input.last_nudge_at`
- `game_input.gameplay_action`
- `game_input.gameplay_direction`
- `game_input.last_gameplay_direction`
- `game_input.gameplay_allowed_state`
- `game_input.gameplay_unknown_run_candidate`
- `game_input.gameplay_pulses_sent`
- `game_input.last_gameplay_at`
- `game_input.gameplay_error`
- `game_input.stuck_watchdog_active`
- `game_input.stuck_watchdog_reason`
- `game_input.recovery_tier`
- `game_input.recovery_reason`
- `game_input.recovery_cooldown_remaining_seconds`
- `game_input.objective_stale_threshold_seconds`
- `game_input.objective_staleness_seconds`
- `game_input.objective_stale`
- `game_input.last_objective_id`
- `game_input.last_objective_change_at`
- `game_input.next_objective_candidate_source`
- `game_input.memory_context`
- `game_input.objective_context.next_objective_category`
- `game_input.objective_context.next_objective_metric`
- `game_input.objective_context.next_objective_target`
- `game_input.objective_context.next_objective_current`
- `game_input.status_file`

## Replay OCR Fixtures (`tests/fixtures/replay_ocr/scenarios.json`)
Replay scenario contract:
- `id`
- `steps[]`
  - `ocr_text`
  - `expected_observed`
  - `expected_effective`
  - `expected_action`

## Memory Signal File (`runtime/live/memory_signal.json`)
Optional v2 live backend feed:
- `objective_rate` or `objective_hint`
- `stability_rate` or `stability_hint`
- `confidence`
- unlock snapshots:
  - `unlocked_characters*`, `unlocked_arcanas*`, `unlocked_weapons*`, `unlocked_passives*`, `unlocked_stages*`
- save freshness metadata:
  - `save_data_age_seconds`
  - `save_data_stale`
  - `save_data_path`

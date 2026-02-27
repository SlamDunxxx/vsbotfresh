# VSBotFresh

Fresh unattended Vampire Survivors objective-speed bot scaffold.

## What it implements
- Simulation-first continuous orchestration loop (never-stop default).
- Population-based policy tuning.
- Strict canary gate with promotion/rollback policy.
- SQLite-backed policy registry + checkpoint history.
- Safety pauses for destructive actions and crash-loop threshold.
- Local control API:
  - `POST /control/stop`
  - `POST /control/pause`
  - `POST /control/resume`
  - `GET /health`
  - `GET /summary/latest`
- Local dashboard at `site/index.html` (reads `site/data/*.json`).
- Rust `sim-core` crate plus Python fallback when Rust toolchain is absent.
- Native macOS game-input daemon (osascript) for menu nudges plus continuous gameplay movement/confirm pulses.

## Layout
- `config/objectives.json`
- `config/settings.toml`
- `src/vs_overseer/*`
- `sim-core/*`
- `scripts/install_rust_local.sh`
- `scripts/start_unattended.sh`
- `scripts/start_live_signal_daemon.sh`
- `scripts/stop_live_signal_daemon.sh`
- `scripts/start_game_input_daemon.sh`
- `scripts/stop_game_input_daemon.sh`
- `scripts/install_launch_agent.sh`
- `scripts/load_launch_agents.sh`
- `scripts/unload_launch_agents.sh`
- `scripts/run_tests.sh`
- `launchd/com.vsbotfresh.orchestrator.plist.template`
- `launchd/com.vsbotfresh.live-signal.plist.template`
- `launchd/com.vsbotfresh.game-input.plist.template`

## Quick start
```bash
cd "$HOME/Library/Application Support/Steam/steamapps/VSBotFresh"
PYTHONPATH=./src python3 -m unittest discover -s tests -p 'test_*.py'
./scripts/start_unattended.sh --max-generations 3
```

## CI/CD and releases
- GitHub Actions CI workflow: `.github/workflows/ci.yml`
- SemVer release/tag workflow: `.github/workflows/release.yml`
- GitHub Pages status publish workflow: `.github/workflows/pages-status.yml`

Release behavior:
- Conventional commits drive version bumps.
- `feat:` -> minor, breaking change -> major, everything else -> patch.
- Tags are created as `vX.Y.Z`.
- Release workflow tags the validated `main` commit after CI success.

Local release dry run:
```bash
python3 scripts/release/semver_bump.py --pyproject pyproject.toml
```

## Run continuously
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml run
```

Install local Rust toolchain (one-time, recommended):
```bash
./scripts/install_rust_local.sh
```

If local Rust is installed:
```bash
export CARGO_HOME="$PWD/.cargo"
export RUSTUP_HOME="$PWD/.rustup"
export PATH="$CARGO_HOME/bin:$PATH"
```

## API control examples
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml control health
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml control pause --reason "maintenance"
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml control resume
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml control stop
```

## Live status pane
Render a one-shot human-readable snapshot:
```bash
./scripts/watch_live_status.sh --once
```

Auto-refresh status in a pane (if running inside `tmux`) or in the current shell:
```bash
./scripts/open_live_status_pane.sh 2
```

## Memory-backed live probe (v2)
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml live-probe
```

Generate one signal snapshot from save data:
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml live-signal --save-path "$HOME/Library/Application Support/Steam/userdata/<steam_id>/1794680/remote/SaveData"
```

Run continuous memory-signal daemon:
```bash
./scripts/start_live_signal_daemon.sh --save-path "$HOME/Library/Application Support/Steam/userdata/<steam_id>/1794680/remote/SaveData"
```

Or start unattended orchestrator and memory-signal daemon together:
```bash
./scripts/start_unattended.sh --with-live-signal --save-path "$HOME/Library/Application Support/Steam/userdata/<steam_id>/1794680/remote/SaveData"
```

Run native game-input daemon (macOS):
```bash
./scripts/start_game_input_daemon.sh
```

One-shot nudge (manual):
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml game-input --force
```

Safety switch (required when `require_arm_file = true`):
```bash
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml game-input-safety status
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml game-input-safety arm --minutes 10
PYTHONPATH=./src python3 -m vs_overseer.cli --config ./config/settings.toml game-input-safety disarm
```

When LaunchAgents are active, manual start scripts skip by default to avoid duplicate API/process ownership.
Use `--force-manual` only for temporary debugging runs.

`[live].memory_backend` modes:
- `auto` (default): `signal_file` -> `save_data` -> `env_gate`
- `signal_file`
- `save_data`
- `env_gate`

Signal file schema (default path `runtime/live/memory_signal.json`):
```json
{
  "objective_hint": 0.62,
  "stability_hint": 0.71,
  "confidence": 0.85,
  "blocked": false,
  "collection_entries": 121,
  "collection_target": 470,
  "collection_ratio": 0.257,
  "bestiary_entries": 64,
  "bestiary_target": 360,
  "bestiary_ratio": 0.178,
  "steam_achievements": 52,
  "steam_achievements_target": 243,
  "steam_achievements_ratio": 0.214,
  "unlocked_characters_count": 18,
  "unlocked_arcanas_count": 9,
  "unlocked_weapons_count": 121,
  "unlocked_passives_count": 16,
  "unlocked_stages_count": 7,
  "save_data_age_seconds": 2.4,
  "save_data_stale": false,
  "save_data_path": "/.../SaveData",
  "unlocked_characters": ["ANTONIO", "IMELDA", "..."],
  "unlocked_arcanas": ["GEMINI", "..."],
  "unlocked_weapons": ["WHIP", "MAGIC_MISSILE", "..."],
  "unlocked_passives": ["POWER", "ARMOR", "CLOVER", "..."],
  "unlocked_stages": ["FOREST", "LIBRARY", "..."]
}
```

`config/objectives.json` now tracks long-horizon completion for:
- Collection completion (`470` total entries target).
- Bestiary completion (`360` unique entries target).
- Steam 100% achievements (`243` required achievements target).
- Early wiki-informed micro-routes (stage/character/arcana/passive/weapon ramps) before 10% collection.

Objective unlock signals can use metric thresholds:
- `collection_ratio:<0..1>`
- `collection_entries:<count>`
- `bestiary_ratio:<0..1>`
- `bestiary_entries:<count>`
- `steam_achievements_ratio:<0..1>`
- `steam_achievements:<count>`
- `unlocked_characters_count:<count>`
- `unlocked_arcanas_count:<count>`
- `unlocked_weapons_count:<count>`
- `unlocked_passives_count:<count>`
- `unlocked_stages_count:<count>`
- `has_character:<token>`
- `has_arcana:<token>`
- `has_weapon:<token>`
- `has_passive:<token>`
- `has_stage:<token>`
- `completion:full_triad` (all three ratios at 100%)

## Rust simulator backend
If `cargo` is installed, `sim-core` is built automatically on first use.
If `cargo` is unavailable, the orchestrator continues using Python simulation backend and records that backend in health/summary.

## Runtime auto-tuning
Auto-tuning can adjust runtime knobs (`max_parallel_workers`, canary budgets, loop sleep) using CPU and quality guardrails.

Defaults in `config/settings.toml` are:
- enabled in `enforce` mode (recommendations are applied automatically)
- CPU target `0.70-0.85` normalized host usage
- worker cap `8`, worker floor `2`
- under low CPU at worker/sleep limits, it can increase episode budgets up to configured caps
- quality-first guardrails with cooldown

`[live]` watchdog options:
- `progress_training_mode = true` disables env-gate fallback for unattended progress training
- `save_data_stale_minutes` blocks stale SaveData probes
- `progress_stale_pause_minutes` hard-pauses orchestrator when SaveData is stale

## Objective-biased scoring
Scoring can dynamically emphasize objective gain when Collection/Bestiary/Achievement progress is low.

`[scoring]` supports:
- `objective_bias_enabled` (`true`/`false`)
- `objective_bias_strength` (bias intensity)
- `collection_gain_weight`
- `bestiary_gain_weight`
- `achievement_gain_weight`

The effective per-generation scoring weights are written to summary as `scoring_profile`.

## Dynamic Objective Planner
The dynamic planner can generate a rolling queue of wiki-informed, near-term objectives based on current unlocks.

Configuration:
- `[objective_planner].enabled`
- `[objective_planner].mapping_file` (default `config/wiki_progression.json`)
- `[objective_planner].rolling_window_size`
- `[objective_planner].refresh_every_generations`
- `[objective_planner].heartbeat_log_file`
- `[objective_planner].heartbeat_interval_seconds`

Runtime output:
- `summary.objective_planner.queue` contains generated achievable objectives
- `health.objective_planner` reports planner status/load errors
- heartbeat rows are appended to `runtime/logs/objective_planner_heartbeat.log`

## Wiki Sync
The wiki sync step periodically refreshes target milestones in `config/wiki_progression.json` from curated wiki pages.

Configuration:
- `[wiki_sync].enabled`
- `[wiki_sync].interval_minutes`
- `[wiki_sync].sources_file` (default `config/wiki_sources.json`)
- `[wiki_sync].mapping_file` (default `config/wiki_progression.json`)
- `[wiki_sync].request_timeout_seconds`

Runtime output:
- `health.wiki_sync` and `summary.wiki_sync` contain sync status, totals, and source fetch state.

## Native Game Input
The game-input daemon sends continuous movement/confirm pulses during runs and also sends configurable rescue sequences when the save appears idle long enough.

Configuration:
- `[game_input].enabled`
- `[game_input].app_name`
- `[game_input].watch_interval_seconds`
- `[game_input].pause_when_unfocused`
- `[game_input].require_arm_file`
- `[game_input].arm_file`
- `[game_input].gameplay_enabled`
- `[game_input].gameplay_interval_seconds`
- `[game_input].gameplay_hold_seconds`
- `[game_input].gameplay_sequence`
- `[game_input].gameplay_confirm_enabled`
- `[game_input].gameplay_confirm_interval_seconds`
- `[game_input].gameplay_confirm_key`
- `[game_input].menu_detection_enabled`
- `[game_input].menu_scan_interval_seconds`
- `[game_input].min_save_data_age_seconds`
- `[game_input].nudge_cooldown_seconds`
- `[game_input].stuck_watchdog_enabled`
- `[game_input].stuck_window_seconds`
- `[game_input].stuck_min_save_data_age_seconds`
- `[game_input].stuck_recovery_interval_seconds`
- `[game_input].max_nudges_per_session`
- `[game_input].key_delay_seconds`
- `[game_input].title_nudge_sequence`
- `[game_input].status_file`
- `[game_input].dry_run`

Runtime output:
- `runtime/live/game_input_status.json`
- `health.game_input` and `summary.game_input`

Notes:
- Playwright is for browser automation; this uses native macOS `osascript`.
- macOS Accessibility/Automation permissions are required for key injection.
- Menu detection is OCR-based via local `tesseract`.

## LaunchAgent
Install all launch agents (orchestrator + live-signal + game-input):
```bash
./scripts/install_launch_agent.sh
```

Load/start all now and auto-start on login:
```bash
./scripts/load_launch_agents.sh
```

Unload all:
```bash
./scripts/unload_launch_agents.sh
```

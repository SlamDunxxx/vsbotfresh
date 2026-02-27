#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100.0:.2f}%"
    except Exception:
        return "-"


def _num(value: Any, *, digits: int = 0) -> str:
    try:
        if digits <= 0:
            return str(int(float(value)))
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def _signed(value: Any, *, digits: int = 4) -> str:
    try:
        return f"{float(value):+.{digits}f}"
    except Exception:
        return "-"


def _yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds(raw: Any) -> str:
    value = str(raw or "").strip()
    if not value:
        return "-"
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
        return f"{age:.1f}s"
    except Exception:
        return "-"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render human-readable VSBotFresh live status")
    parser.add_argument("--root", default="", help="Project root (defaults to repo root)")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve() if str(args.root).strip() else Path(__file__).resolve().parents[1]
    health = _read_json(root / "site/data/health.json")
    summary = _read_json(root / "site/data/latest_summary.json")
    game_input = _read_json(root / "runtime/live/game_input_status.json")
    signal = _read_json(root / "runtime/live/memory_signal.json")

    decision = summary.get("decision") or {}
    objective = (health.get("objective_planner") or {}).get("queue") or []
    next_objective = objective[0] if isinstance(objective, list) and objective else {}
    unlock = summary.get("unlock_progress") or {}
    trend = summary.get("unlock_trend") or {}
    autotune = summary.get("autotune") or {}

    baseline_live = summary.get("baseline_live") or {}
    candidate_live = summary.get("candidate_live") or {}
    live_obj_delta = None
    live_stab_delta = None
    try:
        live_obj_delta = float(candidate_live.get("objective_rate")) - float(baseline_live.get("objective_rate"))
    except Exception:
        pass
    try:
        live_stab_delta = float(candidate_live.get("stability_rate")) - float(baseline_live.get("stability_rate"))
    except Exception:
        pass

    print(f"VSBotFresh Live Status  {_iso_now()}")
    print("-" * 96)
    print(
        "Stack      "
        f"state={health.get('state', '-')} generation={health.get('generation', '-')} "
        f"policy={health.get('active_policy_id', '-')}"
    )
    print(
        "Objective  "
        f"id={next_objective.get('id', '-')} cat={next_objective.get('category', '-')} "
        f"metric={next_objective.get('metric', '-')} "
        f"{_num(next_objective.get('current'))}/{_num(next_objective.get('target'))} "
        f"gap={_num(next_objective.get('gap'), digits=2)}"
    )
    print(
        "Progress   "
        f"collection={_num(unlock.get('collection_entries'))}/{_num(unlock.get('collection_target'))} "
        f"({_pct(unlock.get('collection_ratio'))}, d{_signed(unlock.get('collection_entries_delta'), digits=1)}) | "
        f"bestiary={_num(unlock.get('bestiary_entries'))}/{_num(unlock.get('bestiary_target'))} "
        f"({_pct(unlock.get('bestiary_ratio'))}, d{_signed(unlock.get('bestiary_entries_delta'), digits=1)}) | "
        f"achievements={_num(unlock.get('steam_achievements'))}/{_num(unlock.get('steam_achievements_target'))} "
        f"({_pct(unlock.get('steam_achievements_ratio'))}, d{_signed(unlock.get('steam_achievements_delta'), digits=1)})"
    )
    print(
        "Unlocks    "
        f"chars={_num(unlock.get('unlocked_characters_count'))} "
        f"arcanas={_num(unlock.get('unlocked_arcanas_count'))} "
        f"weapons={_num(unlock.get('unlocked_weapons_count'))} "
        f"passives={_num(unlock.get('unlocked_passives_count'))} "
        f"stages={_num(unlock.get('unlocked_stages_count'))}"
    )
    print(
        "Trend      "
        f"triad_delta={_num(trend.get('triad_progress_delta_score'), digits=4)} "
        f"any_gain={_yes_no(trend.get('triad_progress_any_gain'))} "
        f"promotion={summary.get('promotion_state', '-')}"
    )
    print(
        "Training   "
        f"decision={decision.get('reason', '-')} "
        f"sim_improvement={_signed(decision.get('improvement'), digits=4)} "
        f"live_obj_delta={_signed(live_obj_delta, digits=4)} "
        f"live_stability_delta={_signed(live_stab_delta, digits=4)}"
    )
    print(
        "Input      "
        f"focused={_yes_no(game_input.get('game_focused'))} "
        f"armed={_yes_no(game_input.get('safety_armed'))} "
        f"menu={game_input.get('menu_state', '-')} ({game_input.get('menu_state_reason', '-')}) "
        f"capture={game_input.get('menu_capture_mode', '-')}"
    )
    print(
        "Gameplay   "
        f"allowed={_yes_no(game_input.get('gameplay_allowed_state'))} "
        f"action={game_input.get('gameplay_action', '-')} "
        f"pulses={_num(game_input.get('gameplay_pulses_sent'))} "
        f"last_dir={game_input.get('last_gameplay_direction') or '-'}"
    )
    print(
        "MenuTarget "
        f"character={game_input.get('menu_target_character_key', '-')}@{_num(game_input.get('menu_target_character_index'))} "
        f"stage={game_input.get('menu_target_stage_key', '-')}@{_num(game_input.get('menu_target_stage_index'))}"
    )
    print(
        "Watchdogs  "
        f"progress={((health.get('progress_watchdog') or {}).get('reason') or '-')} "
        f"save_age={_num((health.get('progress_watchdog') or {}).get('save_data_age_seconds'), digits=1)}s "
        f"stuck={game_input.get('stuck_watchdog_reason', '-')}"
    )
    print(
        "Freshness  "
        f"health={_age_seconds(health.get('generated_at'))} "
        f"summary={_age_seconds(summary.get('generated_at'))} "
        f"game_input={_age_seconds(game_input.get('generated_at'))} "
        f"signal={_age_seconds(signal.get('generated_at'))}"
    )
    menu_ocr_error = str(game_input.get("menu_ocr_error", "")).strip()
    if menu_ocr_error:
        print(f"Alert      menu_ocr_error={menu_ocr_error}")
    auto_reason = str(autotune.get("reason", "")).strip()
    if auto_reason:
        print(f"Autotune   action={autotune.get('action', '-')} reason={auto_reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

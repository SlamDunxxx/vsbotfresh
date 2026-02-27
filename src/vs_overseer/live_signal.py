from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

from .config import AppConfig
from .memory_backend import SaveDataProvider


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def generate_signal_once(
    cfg: AppConfig,
    *,
    save_path_override: str = "",
    output_override: str = "",
) -> dict[str, Any]:
    provider = SaveDataProvider(cfg, save_path_override=save_path_override)
    result = provider.probe()
    out_path = cfg.resolve(output_override or cfg.live.memory_signal_file)

    if not result.ok or result.signal is None:
        payload = {
            "generated_at": _utc_now_iso(),
            "blocked": True,
            "reason": result.reason,
            "source": provider.name,
        }
        _write_json_atomic(out_path, payload)
        return {
            "ok": False,
            "reason": result.reason,
            "output": str(out_path),
            "payload": payload,
        }

    signal = result.signal
    payload = {
        "generated_at": _utc_now_iso(),
        "blocked": False,
        "objective_hint": signal.objective_hint,
        "stability_hint": signal.stability_hint,
        "confidence": signal.confidence,
        "source": signal.source,
        "collection_entries": signal.collection_entries,
        "collection_target": signal.collection_target,
        "collection_ratio": signal.collection_ratio,
        "bestiary_entries": signal.bestiary_entries,
        "bestiary_target": signal.bestiary_target,
        "bestiary_ratio": signal.bestiary_ratio,
        "steam_achievements": signal.steam_achievements,
        "steam_achievements_target": signal.steam_achievements_target,
        "steam_achievements_ratio": signal.steam_achievements_ratio,
        "unlocked_characters": signal.unlocked_characters,
        "unlocked_characters_count": signal.unlocked_characters_count,
        "unlocked_arcanas": signal.unlocked_arcanas,
        "unlocked_arcanas_count": signal.unlocked_arcanas_count,
        "unlocked_weapons": signal.unlocked_weapons,
        "unlocked_weapons_count": signal.unlocked_weapons_count,
        "unlocked_passives": signal.unlocked_passives,
        "unlocked_passives_count": signal.unlocked_passives_count,
        "unlocked_stages": signal.unlocked_stages,
        "unlocked_stages_count": signal.unlocked_stages_count,
        "save_data_age_seconds": signal.save_data_age_seconds,
        "save_data_stale": signal.save_data_stale,
        "save_data_path": signal.save_data_path,
    }
    _write_json_atomic(out_path, payload)
    return {
        "ok": True,
        "reason": "ok",
        "output": str(out_path),
        "payload": payload,
    }


def run_signal_daemon(
    cfg: AppConfig,
    *,
    save_path_override: str = "",
    output_override: str = "",
    interval_s: float = 2.0,
) -> None:
    wait = max(0.2, float(interval_s))
    while True:
        _ = generate_signal_once(
            cfg,
            save_path_override=save_path_override,
            output_override=output_override,
        )
        time.sleep(wait)

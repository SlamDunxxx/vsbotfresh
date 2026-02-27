from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Protocol

from .config import AppConfig


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _is_truthy(raw: str) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "ready", "on"}


COLLECTION_TARGET_ENTRIES = 470
BESTIARY_TARGET_ENTRIES = 360
STEAM_ACHIEVEMENTS_TARGET = 243

# Known passive item IDs used by SaveData payloads.
PASSIVE_ITEM_IDS = {
    "POWER",
    "ARMOR",
    "MAXHP",
    "RECOVERY",
    "COOLDOWN",
    "AREA",
    "SPEED",
    "DURATION",
    "AMOUNT",
    "MOVE",
    "MAGNET",
    "LUCK",
    "GROWTH",
    "GREED",
    "CURSE",
    "REVIVAL",
    "TORRONA_BOX",
    "TIRAGISU",
    "CLOVER",
    "SPINACH",
    "HOLLOW_HEART",
    "PUMMAROLA",
    "EMPTY_TOME",
    "CANDELABRADOR",
    "BRACER",
    "SPELLBINDER",
    "DUPLICATOR",
    "WINGS",
    "ATTRACTORB",
    "CROWN",
    "STONE_MASK",
    "SKULL_O_MANIAC",
}


def _as_str_set(raw: object) -> set[str]:
    if not isinstance(raw, list):
        return set()
    out: set[str] = set()
    for item in raw:
        value = str(item).strip()
        if value:
            out.add(value)
    return out


def _optional_str_list(raw: object) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        return None
    return [str(x) for x in raw]


def _count_positive_values(raw: object) -> int:
    if not isinstance(raw, dict):
        return 0
    count = 0
    for value in raw.values():
        try:
            if float(value) > 0.0:
                count += 1
        except Exception:  # noqa: BLE001
            continue
    return count


def _optional_int(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except Exception:  # noqa: BLE001
        return None


def _optional_ratio(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return _clamp01(float(raw))
    except Exception:  # noqa: BLE001
        return None


def _optional_float(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class MemorySignal:
    objective_hint: float
    stability_hint: float
    confidence: float
    source: str
    collection_entries: int | None = None
    collection_target: int | None = None
    collection_ratio: float | None = None
    bestiary_entries: int | None = None
    bestiary_target: int | None = None
    bestiary_ratio: float | None = None
    steam_achievements: int | None = None
    steam_achievements_target: int | None = None
    steam_achievements_ratio: float | None = None
    unlocked_characters: list[str] | None = None
    unlocked_characters_count: int | None = None
    unlocked_arcanas: list[str] | None = None
    unlocked_arcanas_count: int | None = None
    unlocked_weapons: list[str] | None = None
    unlocked_weapons_count: int | None = None
    unlocked_passives: list[str] | None = None
    unlocked_passives_count: int | None = None
    unlocked_stages: list[str] | None = None
    unlocked_stages_count: int | None = None
    save_data_age_seconds: float | None = None
    save_data_stale: bool | None = None
    save_data_path: str | None = None


@dataclass(frozen=True)
class MemoryProbeResult:
    ok: bool
    reason: str
    signal: MemorySignal | None


class SignalProvider(Protocol):
    name: str

    def probe(self) -> MemoryProbeResult: ...


class SignalFileProvider:
    name = "signal_file"

    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def probe(self) -> MemoryProbeResult:
        path = self.cfg.resolve(self.cfg.live.memory_signal_file)
        if not path.exists():
            return MemoryProbeResult(ok=False, reason=f"missing:{path}", signal=None)

        max_age = max(1.0, float(self.cfg.live.memory_signal_max_age_seconds))
        age_s = max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
        if age_s > max_age:
            return MemoryProbeResult(ok=False, reason=f"stale:{age_s:.2f}s", signal=None)

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return MemoryProbeResult(ok=False, reason=f"json_decode_error:{exc}", signal=None)

        if not isinstance(payload, dict):
            return MemoryProbeResult(ok=False, reason="invalid_payload_type", signal=None)
        if bool(payload.get("blocked", False)):
            blocked_reason = str(payload.get("reason", "blocked")).strip() or "blocked"
            return MemoryProbeResult(ok=False, reason=f"blocked:{blocked_reason}", signal=None)

        objective_hint = payload.get("objective_hint", payload.get("objective_rate", payload.get("unlock_rate", 0.0)))
        stability_hint = payload.get("stability_hint", payload.get("stability_rate", 0.0))
        confidence = payload.get("confidence", 0.6)

        signal = MemorySignal(
            objective_hint=_clamp01(float(objective_hint)),
            stability_hint=_clamp01(float(stability_hint)),
            confidence=_clamp01(float(confidence)),
            source=f"signal_file:{path}",
            collection_entries=_optional_int(payload.get("collection_entries")),
            collection_target=_optional_int(payload.get("collection_target")),
            collection_ratio=_optional_ratio(payload.get("collection_ratio")),
            bestiary_entries=_optional_int(payload.get("bestiary_entries")),
            bestiary_target=_optional_int(payload.get("bestiary_target")),
            bestiary_ratio=_optional_ratio(payload.get("bestiary_ratio")),
            steam_achievements=_optional_int(payload.get("steam_achievements")),
            steam_achievements_target=_optional_int(payload.get("steam_achievements_target")),
            steam_achievements_ratio=_optional_ratio(payload.get("steam_achievements_ratio")),
            unlocked_characters=_optional_str_list(payload.get("unlocked_characters")),
            unlocked_characters_count=_optional_int(payload.get("unlocked_characters_count")),
            unlocked_arcanas=_optional_str_list(payload.get("unlocked_arcanas")),
            unlocked_arcanas_count=_optional_int(payload.get("unlocked_arcanas_count")),
            unlocked_weapons=_optional_str_list(payload.get("unlocked_weapons")),
            unlocked_weapons_count=_optional_int(payload.get("unlocked_weapons_count")),
            unlocked_passives=_optional_str_list(payload.get("unlocked_passives")),
            unlocked_passives_count=_optional_int(payload.get("unlocked_passives_count")),
            unlocked_stages=_optional_str_list(payload.get("unlocked_stages")),
            unlocked_stages_count=_optional_int(payload.get("unlocked_stages_count")),
            save_data_age_seconds=_optional_float(payload.get("save_data_age_seconds")),
            save_data_stale=(bool(payload.get("save_data_stale")) if payload.get("save_data_stale") is not None else None),
            save_data_path=(str(payload.get("save_data_path")).strip() if payload.get("save_data_path") is not None else None),
        )
        return MemoryProbeResult(ok=True, reason="ok", signal=signal)


class SaveDataProvider:
    name = "save_data"

    def __init__(self, cfg: AppConfig, *, save_path_override: str = "") -> None:
        self.cfg = cfg
        self.save_path_override = str(save_path_override or "").strip()

    def probe(self) -> MemoryProbeResult:
        override = self.save_path_override
        configured = str(self.cfg.live.save_data_path or "").strip()
        env_override = os.environ.get("VSBOT_SAVE_DATA_PATH", "").strip()
        raw = override or env_override or configured
        if not raw:
            return MemoryProbeResult(ok=False, reason="save_data_path_unset", signal=None)

        path = self.cfg.resolve(raw)
        if not path.exists():
            return MemoryProbeResult(ok=False, reason=f"missing:{path}", signal=None)

        age_s = max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
        stale_minutes = max(0.0, float(self.cfg.live.save_data_stale_minutes))
        stale_threshold_s = stale_minutes * 60.0
        if stale_threshold_s > 0.0 and age_s > stale_threshold_s:
            return MemoryProbeResult(
                ok=False,
                reason=f"stale_save_data:{age_s:.1f}s>{stale_threshold_s:.1f}s",
                signal=None,
            )

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return MemoryProbeResult(ok=False, reason=f"json_decode_error:{exc}", signal=None)

        if not isinstance(payload, dict):
            return MemoryProbeResult(ok=False, reason="invalid_payload_type", signal=None)

        signal = signal_from_save_payload(
            payload,
            source=f"save_data:{path}",
            save_data_age_seconds=age_s,
            save_data_path=str(path),
            save_data_stale=False,
        )
        return MemoryProbeResult(ok=True, reason="ok", signal=signal)


class EnvGateProvider:
    name = "env_gate"

    def probe(self) -> MemoryProbeResult:
        ready = _is_truthy(os.environ.get("VSBOT_MEMORY_BACKEND_READY", ""))
        if not ready:
            return MemoryProbeResult(ok=False, reason="env_not_ready", signal=None)

        objective_hint = _clamp01(float(os.environ.get("VSBOT_MEMORY_OBJECTIVE_HINT", "0.52")))
        stability_hint = _clamp01(float(os.environ.get("VSBOT_MEMORY_STABILITY_HINT", "0.62")))
        confidence = _clamp01(float(os.environ.get("VSBOT_MEMORY_CONFIDENCE", "0.50")))
        signal = MemorySignal(
            objective_hint=objective_hint,
            stability_hint=stability_hint,
            confidence=confidence,
            source="env_gate",
        )
        return MemoryProbeResult(ok=True, reason="ok", signal=signal)


class MemoryBackend:
    def __init__(self, cfg: AppConfig) -> None:
        self.cfg = cfg

    def _providers(self) -> list[SignalProvider]:
        mode = str(self.cfg.live.memory_backend or "auto").strip().lower()
        if mode == "signal_file":
            return [SignalFileProvider(self.cfg)]
        if mode == "save_data":
            return [SaveDataProvider(self.cfg)]
        if mode == "env_gate":
            return [EnvGateProvider()]
        if bool(self.cfg.live.progress_training_mode):
            return [
                SignalFileProvider(self.cfg),
                SaveDataProvider(self.cfg),
            ]
        return [
            SignalFileProvider(self.cfg),
            SaveDataProvider(self.cfg),
            EnvGateProvider(),
        ]

    def probe(self) -> MemoryProbeResult:
        if not self.cfg.live.enabled:
            return MemoryProbeResult(ok=False, reason="live_disabled_by_config", signal=None)

        reasons: list[str] = []
        for provider in self._providers():
            result = provider.probe()
            if result.ok:
                return result
            reasons.append(f"{provider.name}:{result.reason}")

        reason = "memory_backend_unavailable"
        if reasons:
            reason += ":" + "|".join(reasons[:3])
        return MemoryProbeResult(ok=False, reason=reason, signal=None)


def signal_from_save_payload(
    payload: dict[str, object],
    *,
    source: str,
    save_data_age_seconds: float | None = None,
    save_data_path: str | None = None,
    save_data_stale: bool | None = None,
) -> MemorySignal:
    unlocked_characters = sorted(_as_str_set(payload.get("UnlockedCharacters", [])))
    unlocked_arcanas = sorted(_as_str_set(payload.get("UnlockedArcanas", [])))
    unlocked_weapons_raw = _as_str_set(payload.get("UnlockedWeapons", []))
    unlocked_stages = sorted(_as_str_set(payload.get("UnlockedStages", [])))
    collected_weapons = _as_str_set(payload.get("CollectedWeapons", []))
    collected_items = _as_str_set(payload.get("CollectedItems", []))
    unlocked_relics = _as_str_set(payload.get("UnlockedRelics", []))
    achievements = _as_str_set(payload.get("Achievements", []))

    unlocked_passives_set = {
        token
        for token in (unlocked_weapons_raw | collected_weapons | collected_items)
        if str(token).strip().upper() in PASSIVE_ITEM_IDS
    }
    unlocked_passives = sorted(unlocked_passives_set)
    unlocked_weapons = sorted(
        token for token in unlocked_weapons_raw if str(token).strip().upper() not in PASSIVE_ITEM_IDS
    )

    collection_entries = len(collected_weapons | collected_items | set(unlocked_arcanas) | unlocked_relics)
    bestiary_entries = _count_positive_values(payload.get("KillCount", {}))
    steam_achievements = len(achievements)

    collection_ratio = _clamp01(collection_entries / float(COLLECTION_TARGET_ENTRIES))
    bestiary_ratio = _clamp01(bestiary_entries / float(BESTIARY_TARGET_ENTRIES))
    steam_achievements_ratio = _clamp01(steam_achievements / float(STEAM_ACHIEVEMENTS_TARGET))

    # Blend long-horizon account completion dimensions into one stable quality hint.
    objective_hint = _clamp01(
        (0.45 * collection_ratio)
        + (0.30 * bestiary_ratio)
        + (0.25 * steam_achievements_ratio)
    )
    stability_hint = _clamp01(0.35 + (objective_hint * 0.5))
    confidence = 0.75

    return MemorySignal(
        objective_hint=objective_hint,
        stability_hint=stability_hint,
        confidence=confidence,
        source=source,
        collection_entries=collection_entries,
        collection_target=COLLECTION_TARGET_ENTRIES,
        collection_ratio=collection_ratio,
        bestiary_entries=bestiary_entries,
        bestiary_target=BESTIARY_TARGET_ENTRIES,
        bestiary_ratio=bestiary_ratio,
        steam_achievements=steam_achievements,
        steam_achievements_target=STEAM_ACHIEVEMENTS_TARGET,
        steam_achievements_ratio=steam_achievements_ratio,
        unlocked_characters=unlocked_characters,
        unlocked_characters_count=len(unlocked_characters),
        unlocked_arcanas=unlocked_arcanas,
        unlocked_arcanas_count=len(unlocked_arcanas),
        unlocked_weapons=unlocked_weapons,
        unlocked_weapons_count=len(unlocked_weapons),
        unlocked_passives=unlocked_passives,
        unlocked_passives_count=len(unlocked_passives),
        unlocked_stages=unlocked_stages,
        unlocked_stages_count=len(unlocked_stages),
        save_data_age_seconds=save_data_age_seconds,
        save_data_stale=save_data_stale,
        save_data_path=save_data_path,
    )

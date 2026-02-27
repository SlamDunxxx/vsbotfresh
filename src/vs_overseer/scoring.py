from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ScoringConfig
from .models import SimBatchMetrics


@dataclass(frozen=True)
class WeightedScore:
    total: float
    objective_component: float
    time_component: float
    stability_component: float


def weighted_score(metrics: SimBatchMetrics, scoring: ScoringConfig) -> WeightedScore:
    objective = metrics.objective_rate * scoring.objective_completion_weight
    time_component = metrics.unlock_rate * scoring.time_to_unlock_weight
    stability = metrics.stability_rate * scoring.stability_weight
    total = objective + time_component + stability
    return WeightedScore(
        total=float(total),
        objective_component=float(objective),
        time_component=float(time_component),
        stability_component=float(stability),
    )


def _ratio(payload: dict[str, Any], key: str) -> float | None:
    try:
        raw = payload.get(key)
        if raw is None:
            return None
        value = float(raw)
        return min(1.0, max(0.0, value))
    except Exception:  # noqa: BLE001
        return None


def objective_biased_scoring(scoring: ScoringConfig, signal_payload: dict[str, Any]) -> tuple[ScoringConfig, dict[str, Any]]:
    base_total = float(
        scoring.objective_completion_weight + scoring.time_to_unlock_weight + scoring.stability_weight
    )
    profile: dict[str, Any] = {
        "enabled": bool(scoring.objective_bias_enabled),
        "available": False,
        "pressure": 0.0,
        "bias": 0.0,
        "base_weights": {
            "objective_completion_weight": float(scoring.objective_completion_weight),
            "time_to_unlock_weight": float(scoring.time_to_unlock_weight),
            "stability_weight": float(scoring.stability_weight),
        },
        "effective_weights": {
            "objective_completion_weight": float(scoring.objective_completion_weight),
            "time_to_unlock_weight": float(scoring.time_to_unlock_weight),
            "stability_weight": float(scoring.stability_weight),
        },
        "ratios": {},
        "deficits": {},
        "deltas": {},
    }
    if not scoring.objective_bias_enabled:
        return scoring, profile

    collection_ratio = _ratio(signal_payload, "collection_ratio")
    bestiary_ratio = _ratio(signal_payload, "bestiary_ratio")
    achievement_ratio = _ratio(signal_payload, "steam_achievements_ratio")
    if collection_ratio is None or bestiary_ratio is None or achievement_ratio is None:
        return scoring, profile

    profile["available"] = True
    profile["ratios"] = {
        "collection_ratio": collection_ratio,
        "bestiary_ratio": bestiary_ratio,
        "steam_achievements_ratio": achievement_ratio,
    }

    collection_deficit = 1.0 - collection_ratio
    bestiary_deficit = 1.0 - bestiary_ratio
    achievement_deficit = 1.0 - achievement_ratio
    profile["deficits"] = {
        "collection_deficit": collection_deficit,
        "bestiary_deficit": bestiary_deficit,
        "steam_achievement_deficit": achievement_deficit,
    }

    wc = max(0.0, float(scoring.collection_gain_weight))
    wb = max(0.0, float(scoring.bestiary_gain_weight))
    wa = max(0.0, float(scoring.achievement_gain_weight))
    wsum = wc + wb + wa
    if wsum <= 0.0:
        return scoring, profile

    deficit_pressure = ((wc * collection_deficit) + (wb * bestiary_deficit) + (wa * achievement_deficit)) / wsum

    collection_target = max(1.0, float(signal_payload.get("collection_target") or 470.0))
    bestiary_target = max(1.0, float(signal_payload.get("bestiary_target") or 360.0))
    achievement_target = max(1.0, float(signal_payload.get("steam_achievements_target") or 243.0))

    raw_collection_delta = _to_float(signal_payload.get("collection_entries_delta"))
    raw_bestiary_delta = _to_float(signal_payload.get("bestiary_entries_delta"))
    raw_achievement_delta = _to_float(signal_payload.get("steam_achievements_delta"))
    delta_available = any(x is not None for x in [raw_collection_delta, raw_bestiary_delta, raw_achievement_delta])

    collection_gain = max(0.0, float(raw_collection_delta or 0.0)) / collection_target
    bestiary_gain = max(0.0, float(raw_bestiary_delta or 0.0)) / bestiary_target
    achievement_gain = max(0.0, float(raw_achievement_delta or 0.0)) / achievement_target
    delta_gain = ((wc * collection_gain) + (wb * bestiary_gain) + (wa * achievement_gain)) / wsum

    # Score ~0.0025 roughly equals one meaningful unlock gain in this window.
    delta_pressure = 1.0 - min(1.0, delta_gain / 0.0025)
    pressure = (
        (0.65 * deficit_pressure) + (0.35 * delta_pressure)
        if delta_available
        else deficit_pressure
    )
    pressure = max(0.0, min(1.0, float(pressure)))

    profile["deltas"] = {
        "available": bool(delta_available),
        "collection_entries_delta": raw_collection_delta,
        "bestiary_entries_delta": raw_bestiary_delta,
        "steam_achievements_delta": raw_achievement_delta,
        "collection_gain_norm": collection_gain,
        "bestiary_gain_norm": bestiary_gain,
        "steam_achievement_gain_norm": achievement_gain,
        "delta_gain_score": delta_gain,
        "delta_pressure": delta_pressure if delta_available else None,
        "deficit_pressure": deficit_pressure,
    }

    bias = max(0.0, min(2.0, float(scoring.objective_bias_strength) * pressure))
    profile["pressure"] = pressure
    profile["bias"] = bias

    objective_weight = float(scoring.objective_completion_weight) * (1.0 + bias)
    time_weight = float(scoring.time_to_unlock_weight) * max(0.35, 1.0 - (0.55 * bias))
    stability_weight = float(scoring.stability_weight) * max(0.35, 1.0 - (0.40 * bias))

    new_total = objective_weight + time_weight + stability_weight
    if new_total > 0.0 and base_total > 0.0:
        scale = base_total / new_total
        objective_weight *= scale
        time_weight *= scale
        stability_weight *= scale

    adjusted = ScoringConfig(
        objective_completion_weight=float(objective_weight),
        time_to_unlock_weight=float(time_weight),
        stability_weight=float(stability_weight),
        objective_bias_enabled=scoring.objective_bias_enabled,
        objective_bias_strength=scoring.objective_bias_strength,
        collection_gain_weight=scoring.collection_gain_weight,
        bestiary_gain_weight=scoring.bestiary_gain_weight,
        achievement_gain_weight=scoring.achievement_gain_weight,
    )
    profile["effective_weights"] = {
        "objective_completion_weight": adjusted.objective_completion_weight,
        "time_to_unlock_weight": adjusted.time_to_unlock_weight,
        "stability_weight": adjusted.stability_weight,
    }
    return adjusted, profile


def improvement_ratio(candidate: float, baseline: float) -> float:
    base = max(1e-9, float(baseline))
    return (float(candidate) - base) / base


def _to_float(raw: object) -> float | None:
    try:
        if raw is None:
            return None
        return float(raw)
    except Exception:  # noqa: BLE001
        return None

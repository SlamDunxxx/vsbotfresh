from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class PolicyParameters:
    aggression: float
    greed: float
    safety: float
    focus: float

    def clamp(self) -> "PolicyParameters":
        return PolicyParameters(
            aggression=min(1.0, max(0.0, self.aggression)),
            greed=min(1.0, max(0.0, self.greed)),
            safety=min(1.0, max(0.0, self.safety)),
            focus=min(1.0, max(0.0, self.focus)),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "aggression": float(self.aggression),
            "greed": float(self.greed),
            "safety": float(self.safety),
            "focus": float(self.focus),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "PolicyParameters":
        return PolicyParameters(
            aggression=float(payload.get("aggression", 0.5)),
            greed=float(payload.get("greed", 0.5)),
            safety=float(payload.get("safety", 0.5)),
            focus=float(payload.get("focus", 0.5)),
        ).clamp()


@dataclass(frozen=True)
class SimEpisodeResult:
    unlock_rate: float
    objective_complete: bool
    stability: float
    elapsed_s: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SimBatchMetrics:
    episodes: int
    objective_rate: float
    unlock_rate: float
    stability_rate: float
    mean_elapsed_s: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiveBatchMetrics:
    runs: int
    objective_rate: float
    stability_rate: float
    blocked: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanaryDecision:
    promote: bool
    reason: str
    improvement: float
    stability_regression: float
    live_deferred: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

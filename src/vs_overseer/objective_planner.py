from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .objective_graph import Objective


def _to_float(raw: object) -> float | None:
    try:
        if raw is None:
            return None
        return float(raw)
    except Exception:  # noqa: BLE001
        return None


def _format_target(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _sanitize_token(raw: str) -> str:
    out = []
    for ch in str(raw).strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in {".", "-"}:
            out.append("_")
        else:
            out.append("_")
    compact = "".join(out).strip("_")
    while "__" in compact:
        compact = compact.replace("__", "_")
    return compact or "goal"


@dataclass(frozen=True)
class PlannerTemplate:
    id_prefix: str
    name_template: str
    category: str
    signal_key: str
    targets: tuple[float, ...]
    max_gap: float
    weight: float
    estimated_time_s: int
    priority: int

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "PlannerTemplate":
        raw_targets = payload.get("targets", [])
        targets: list[float] = []
        if isinstance(raw_targets, list):
            for item in raw_targets:
                value = _to_float(item)
                if value is not None:
                    targets.append(float(value))
        targets = sorted(set(targets))
        return PlannerTemplate(
            id_prefix=str(payload.get("id_prefix", "")).strip() or "wiki_goal",
            name_template=str(payload.get("name_template", "Wiki Route: Reach {target}")).strip(),
            category=str(payload.get("category", "wiki")).strip() or "wiki",
            signal_key=str(payload.get("signal_key", "")).strip(),
            targets=tuple(targets),
            max_gap=max(0.0, float(payload.get("max_gap", 0.0))),
            weight=float(payload.get("weight", 1.0)),
            estimated_time_s=max(1, int(payload.get("estimated_time_s", 600))),
            priority=max(0, int(payload.get("priority", 100))),
        )

    def validate(self) -> None:
        if not self.signal_key:
            raise ValueError("planner template missing signal_key")
        if not self.targets:
            raise ValueError(f"planner template '{self.id_prefix}' missing targets")

    def candidate(self, *, signal_payload: dict[str, Any], completed_ids: set[str]) -> "PlannedObjective" | None:
        current = _to_float(signal_payload.get(self.signal_key))
        if current is None:
            return None

        for target in self.targets:
            if current >= target:
                continue
            gap = float(target - current)
            if gap > self.max_gap:
                continue

            target_text = _format_target(target)
            objective_id = f"{_sanitize_token(self.id_prefix)}_{_sanitize_token(target_text)}"
            if objective_id in completed_ids:
                continue

            objective = Objective(
                id=objective_id,
                name=self.name_template.format(target=target_text),
                category=self.category,
                prerequisites=tuple(),
                unlock_signal=f"{self.signal_key}:{target_text}",
                weight=float(self.weight),
                estimated_time_s=int(self.estimated_time_s),
            )
            return PlannedObjective(
                objective=objective,
                priority=int(self.priority),
                metric=self.signal_key,
                current=float(current),
                target=float(target),
                gap=float(gap),
            )
        return None


@dataclass(frozen=True)
class PlannedObjective:
    objective: Objective
    priority: int
    metric: str
    current: float
    target: float
    gap: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.objective.id,
            "name": self.objective.name,
            "category": self.objective.category,
            "prerequisites": list(self.objective.prerequisites),
            "unlock_signal": self.objective.unlock_signal,
            "weight": float(self.objective.weight),
            "estimated_time_s": int(self.objective.estimated_time_s),
            "priority": int(self.priority),
            "metric": self.metric,
            "current": float(self.current),
            "target": float(self.target),
            "gap": float(self.gap),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "PlannedObjective":
        obj = Objective(
            id=str(payload.get("id", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            category=str(payload.get("category", "wiki")).strip(),
            prerequisites=tuple(str(x) for x in payload.get("prerequisites", []) if str(x).strip()),
            unlock_signal=str(payload.get("unlock_signal", "")).strip(),
            weight=float(payload.get("weight", 1.0)),
            estimated_time_s=max(1, int(payload.get("estimated_time_s", 600))),
        )
        return PlannedObjective(
            objective=obj,
            priority=max(0, int(payload.get("priority", 100))),
            metric=str(payload.get("metric", "")).strip(),
            current=float(payload.get("current", 0.0)),
            target=float(payload.get("target", 0.0)),
            gap=float(payload.get("gap", 0.0)),
        )


class ObjectivePlanner:
    def __init__(
        self,
        *,
        mapping_path: Path,
        templates: list[PlannerTemplate],
        rolling_window_size: int,
    ) -> None:
        self.mapping_path = mapping_path
        self.templates = templates
        self.rolling_window_size = max(1, int(rolling_window_size))

    @staticmethod
    def load(path: str | Path, *, rolling_window_size: int) -> "ObjectivePlanner":
        mapping_path = Path(path).expanduser().resolve()
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
        rows = payload.get("templates", []) if isinstance(payload, dict) else []
        templates = [PlannerTemplate.from_dict(row) for row in rows if isinstance(row, dict)]
        for template in templates:
            template.validate()
        return ObjectivePlanner(
            mapping_path=mapping_path,
            templates=templates,
            rolling_window_size=rolling_window_size,
        )

    def plan(self, *, signal_payload: dict[str, Any], completed_ids: set[str]) -> list[PlannedObjective]:
        out: list[PlannedObjective] = []
        for template in self.templates:
            candidate = template.candidate(signal_payload=signal_payload, completed_ids=completed_ids)
            if candidate is None:
                continue
            out.append(candidate)

        out.sort(key=lambda item: (item.priority, item.gap, item.objective.id))
        return out[: self.rolling_window_size]

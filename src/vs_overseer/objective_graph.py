from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Objective:
    id: str
    name: str
    category: str
    prerequisites: tuple[str, ...]
    unlock_signal: str
    weight: float
    estimated_time_s: int

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> "Objective":
        return Objective(
            id=str(payload.get("id", "")).strip(),
            name=str(payload.get("name", "")).strip(),
            category=str(payload.get("category", "misc")).strip(),
            prerequisites=tuple(str(x) for x in payload.get("prerequisites", []) if str(x).strip()),
            unlock_signal=str(payload.get("unlock_signal", "")).strip(),
            weight=float(payload.get("weight", 1.0)),
            estimated_time_s=max(1, int(payload.get("estimated_time_s", 1))),
        )


class ObjectiveGraph:
    def __init__(self, objectives: list[Objective]) -> None:
        self.objectives = objectives
        self.by_id = {o.id: o for o in objectives}
        if len(self.by_id) != len(objectives):
            raise ValueError("duplicate objective id detected")

    @staticmethod
    def load(path: str | Path) -> "ObjectiveGraph":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = payload.get("objectives", []) if isinstance(payload, dict) else []
        objectives = [Objective.from_dict(x) for x in rows if isinstance(x, dict)]
        graph = ObjectiveGraph(objectives)
        graph.validate()
        return graph

    def validate(self) -> None:
        for obj in self.objectives:
            if not obj.id:
                raise ValueError("objective with empty id")
            for dep in obj.prerequisites:
                if dep not in self.by_id:
                    raise ValueError(f"objective '{obj.id}' references unknown prerequisite '{dep}'")
        _ = self.topological_order()

    def topological_order(self) -> list[Objective]:
        indegree = {o.id: 0 for o in self.objectives}
        children: dict[str, list[str]] = {o.id: [] for o in self.objectives}
        for obj in self.objectives:
            for dep in obj.prerequisites:
                indegree[obj.id] += 1
                children[dep].append(obj.id)

        queue = [oid for oid, deg in indegree.items() if deg == 0]
        queue.sort()
        ordered_ids: list[str] = []

        while queue:
            current = queue.pop(0)
            ordered_ids.append(current)
            for child in children[current]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
            queue.sort()

        if len(ordered_ids) != len(self.objectives):
            raise ValueError("objective graph contains a cycle")
        return [self.by_id[x] for x in ordered_ids]

    def next_objective(self, completed: set[str]) -> Objective | None:
        for obj in self.topological_order():
            if obj.id in completed:
                continue
            if all(dep in completed for dep in obj.prerequisites):
                return obj
        return None

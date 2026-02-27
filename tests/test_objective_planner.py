from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from vs_overseer.objective_planner import ObjectivePlanner


class ObjectivePlannerTests(unittest.TestCase):
    def _write_mapping(self, root: Path) -> Path:
        mapping = {
            "templates": [
                {
                    "id_prefix": "wiki_stage_count",
                    "name_template": "Unlock {target} stages",
                    "category": "stage",
                    "signal_key": "unlocked_stages_count",
                    "targets": [2, 4, 6],
                    "max_gap": 2,
                    "weight": 1.0,
                    "estimated_time_s": 600,
                    "priority": 10,
                },
                {
                    "id_prefix": "wiki_characters_count",
                    "name_template": "Unlock {target} characters",
                    "category": "character",
                    "signal_key": "unlocked_characters_count",
                    "targets": [5, 8, 12],
                    "max_gap": 3,
                    "weight": 1.0,
                    "estimated_time_s": 900,
                    "priority": 20,
                },
            ]
        }
        path = root / "wiki_progression.json"
        path.write_text(json.dumps(mapping) + "\n", encoding="utf-8")
        return path

    def test_plan_builds_achievable_queue(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-planner-") as td:
            root = Path(td)
            planner = ObjectivePlanner.load(self._write_mapping(root), rolling_window_size=6)
            planned = planner.plan(
                signal_payload={
                    "unlocked_stages_count": 1,
                    "unlocked_characters_count": 4,
                },
                completed_ids=set(),
            )
            ids = [item.objective.id for item in planned]
            self.assertIn("wiki_stage_count_2", ids)
            self.assertIn("wiki_characters_count_5", ids)
            self.assertEqual(ids[0], "wiki_stage_count_2")

    def test_plan_skips_completed_and_unachievable_targets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-planner-") as td:
            root = Path(td)
            planner = ObjectivePlanner.load(self._write_mapping(root), rolling_window_size=6)
            planned = planner.plan(
                signal_payload={
                    "unlocked_stages_count": 2,
                    "unlocked_characters_count": 4,
                },
                completed_ids={"wiki_stage_count_4", "wiki_characters_count_5"},
            )
            ids = [item.objective.id for item in planned]
            self.assertNotIn("wiki_stage_count_4", ids)
            self.assertNotIn("wiki_characters_count_5", ids)
            # stage 6 gap is >2 and character 8 gap is >3, so nothing should be proposed
            self.assertEqual(ids, [])

    def test_plan_respects_rolling_window_size(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-planner-") as td:
            root = Path(td)
            planner = ObjectivePlanner.load(self._write_mapping(root), rolling_window_size=1)
            planned = planner.plan(
                signal_payload={
                    "unlocked_stages_count": 1,
                    "unlocked_characters_count": 4,
                },
                completed_ids=set(),
            )
            self.assertEqual(len(planned), 1)
            self.assertEqual(planned[0].objective.id, "wiki_stage_count_2")


if __name__ == "__main__":
    unittest.main()

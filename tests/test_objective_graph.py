from __future__ import annotations

import unittest
from pathlib import Path

from vs_overseer.objective_graph import ObjectiveGraph


class ObjectiveGraphTests(unittest.TestCase):
    def test_next_objective_respects_prerequisites(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "objectives.json"
        graph = ObjectiveGraph.load(path)

        next0 = graph.next_objective(set())
        self.assertIsNotNone(next0)
        self.assertEqual(next0.id, "p01_unlock_bestiary")

        next1 = graph.next_objective({"p01_unlock_bestiary"})
        self.assertIsNotNone(next1)
        self.assertEqual(next1.id, "p01a_wiki_stage_route_bootstrap")

    def test_topological_order_is_complete(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "objectives.json"
        graph = ObjectiveGraph.load(path)
        order = [x.id for x in graph.topological_order()]
        self.assertEqual(len(order), len(set(order)))
        self.assertEqual(order[0], "p01_unlock_bestiary")


if __name__ == "__main__":
    unittest.main()

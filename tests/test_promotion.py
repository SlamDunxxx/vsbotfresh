from __future__ import annotations

import unittest

from vs_overseer.models import LiveBatchMetrics, SimBatchMetrics
from vs_overseer.orchestrator import strict_canary_decision


class PromotionTests(unittest.TestCase):
    def test_reject_when_improvement_below_threshold(self) -> None:
        decision = strict_canary_decision(
            candidate_metrics=SimBatchMetrics(50, 0.5, 0.5, 0.8, 900),
            baseline_metrics=SimBatchMetrics(50, 0.5, 0.5, 0.8, 900),
            candidate_live=LiveBatchMetrics(10, 0.5, 0.8, False, "ok"),
            baseline_live=LiveBatchMetrics(10, 0.5, 0.8, False, "ok"),
            required_improvement=0.03,
            max_stability_regression=0.02,
            candidate_score=1.0,
            baseline_score=1.0,
        )
        self.assertFalse(decision.promote)

    def test_defer_live_when_blocked(self) -> None:
        decision = strict_canary_decision(
            candidate_metrics=SimBatchMetrics(50, 0.7, 0.7, 0.8, 800),
            baseline_metrics=SimBatchMetrics(50, 0.5, 0.5, 0.81, 900),
            candidate_live=LiveBatchMetrics(0, 0.0, 0.0, True, "blocked"),
            baseline_live=LiveBatchMetrics(0, 0.0, 0.0, True, "blocked"),
            required_improvement=0.03,
            max_stability_regression=0.02,
            candidate_score=1.2,
            baseline_score=1.0,
        )
        self.assertTrue(decision.promote)
        self.assertTrue(decision.live_deferred)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from vs_overseer.config import ScoringConfig
from vs_overseer.models import SimBatchMetrics
from vs_overseer.scoring import improvement_ratio, objective_biased_scoring, weighted_score


class ScoringTests(unittest.TestCase):
    def test_weighted_score_components(self) -> None:
        metrics = SimBatchMetrics(
            episodes=10,
            objective_rate=0.5,
            unlock_rate=0.4,
            stability_rate=0.8,
            mean_elapsed_s=1000,
        )
        cfg = ScoringConfig(
            objective_completion_weight=0.6,
            time_to_unlock_weight=0.25,
            stability_weight=0.15,
        )

        score = weighted_score(metrics, cfg)
        self.assertAlmostEqual(score.total, 0.52, places=6)
        self.assertAlmostEqual(score.objective_component, 0.3, places=6)
        self.assertAlmostEqual(score.time_component, 0.1, places=6)
        self.assertAlmostEqual(score.stability_component, 0.12, places=6)

    def test_improvement_ratio(self) -> None:
        self.assertAlmostEqual(improvement_ratio(1.03, 1.0), 0.03, places=6)
        self.assertGreater(improvement_ratio(2.0, 0.0), 0.0)

    def test_objective_biased_scoring_shifts_weight_to_objective_when_progress_low(self) -> None:
        cfg = ScoringConfig(
            objective_completion_weight=0.6,
            time_to_unlock_weight=0.25,
            stability_weight=0.15,
            objective_bias_enabled=True,
            objective_bias_strength=0.8,
            collection_gain_weight=0.45,
            bestiary_gain_weight=0.30,
            achievement_gain_weight=0.25,
        )
        adjusted, profile = objective_biased_scoring(
            cfg,
            {
                "collection_ratio": 0.05,
                "bestiary_ratio": 0.04,
                "steam_achievements_ratio": 0.02,
            },
        )
        self.assertTrue(bool(profile.get("available")))
        self.assertGreater(adjusted.objective_completion_weight, cfg.objective_completion_weight)
        self.assertLess(adjusted.time_to_unlock_weight, cfg.time_to_unlock_weight)
        self.assertLess(adjusted.stability_weight, cfg.stability_weight)
        self.assertAlmostEqual(
            adjusted.objective_completion_weight + adjusted.time_to_unlock_weight + adjusted.stability_weight,
            cfg.objective_completion_weight + cfg.time_to_unlock_weight + cfg.stability_weight,
            places=6,
        )

    def test_objective_biased_scoring_no_signal_keeps_base_weights(self) -> None:
        cfg = ScoringConfig(
            objective_completion_weight=0.6,
            time_to_unlock_weight=0.25,
            stability_weight=0.15,
        )
        adjusted, profile = objective_biased_scoring(cfg, {})
        self.assertFalse(bool(profile.get("available")))
        self.assertEqual(adjusted.objective_completion_weight, cfg.objective_completion_weight)
        self.assertEqual(adjusted.time_to_unlock_weight, cfg.time_to_unlock_weight)
        self.assertEqual(adjusted.stability_weight, cfg.stability_weight)

    def test_objective_biased_scoring_relaxes_pressure_when_real_unlock_delta_present(self) -> None:
        cfg = ScoringConfig(
            objective_completion_weight=0.68,
            time_to_unlock_weight=0.20,
            stability_weight=0.12,
            objective_bias_enabled=True,
            objective_bias_strength=0.85,
            collection_gain_weight=0.45,
            bestiary_gain_weight=0.30,
            achievement_gain_weight=0.25,
        )
        base_payload = {
            "collection_ratio": 0.03,
            "bestiary_ratio": 0.02,
            "steam_achievements_ratio": 0.01,
            "collection_target": 470,
            "bestiary_target": 360,
            "steam_achievements_target": 243,
            "collection_entries_delta": 0,
            "bestiary_entries_delta": 0,
            "steam_achievements_delta": 0,
        }
        _, no_gain_profile = objective_biased_scoring(cfg, dict(base_payload))
        _, with_gain_profile = objective_biased_scoring(
            cfg,
            {
                **base_payload,
                "collection_entries_delta": 2,
                "bestiary_entries_delta": 1,
                "steam_achievements_delta": 1,
            },
        )
        self.assertTrue(bool(no_gain_profile.get("deltas", {}).get("available")))
        self.assertTrue(bool(with_gain_profile.get("deltas", {}).get("available")))
        self.assertGreater(float(no_gain_profile.get("pressure", 0.0)), float(with_gain_profile.get("pressure", 0.0)))


if __name__ == "__main__":
    unittest.main()

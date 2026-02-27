from __future__ import annotations

import unittest

from vs_overseer.orchestrator import objective_unlock_met


class OrchestratorObjectiveSignalTests(unittest.TestCase):
    def test_collection_ratio_signal(self) -> None:
        payload = {"collection_ratio": 0.42}
        self.assertTrue(bool(objective_unlock_met("collection_ratio:0.40", payload)))
        self.assertFalse(bool(objective_unlock_met("collection_ratio:0.50", payload)))

    def test_bestiary_entries_signal(self) -> None:
        payload = {"bestiary_entries": 199}
        self.assertFalse(bool(objective_unlock_met("bestiary_entries:200", payload)))
        self.assertTrue(bool(objective_unlock_met("bestiary_entries:150", payload)))

    def test_steam_achievement_signal(self) -> None:
        payload = {"steam_achievements": 120}
        self.assertTrue(bool(objective_unlock_met("steam_achievements:100", payload)))
        self.assertFalse(bool(objective_unlock_met("steam_achievements:200", payload)))

    def test_unlock_count_signals(self) -> None:
        payload = {
            "unlocked_characters_count": 5,
            "unlocked_arcanas_count": 1,
            "unlocked_weapons_count": 130,
            "unlocked_passives_count": 6,
            "unlocked_stages_count": 3,
        }
        self.assertTrue(bool(objective_unlock_met("unlocked_characters_count:5", payload)))
        self.assertTrue(bool(objective_unlock_met("unlocked_arcanas_count:1", payload)))
        self.assertTrue(bool(objective_unlock_met("unlocked_weapons_count:120", payload)))
        self.assertTrue(bool(objective_unlock_met("unlocked_passives_count:6", payload)))
        self.assertFalse(bool(objective_unlock_met("unlocked_stages_count:4", payload)))

    def test_has_token_signals(self) -> None:
        payload = {
            "unlocked_characters": ["Imelda"],
            "unlocked_arcanas": ["Gemini"],
            "unlocked_weapons": ["Whip"],
            "unlocked_passives": ["Clover"],
            "unlocked_stages": ["Forest"],
        }
        self.assertTrue(bool(objective_unlock_met("has_character:IMELDA", payload)))
        self.assertTrue(bool(objective_unlock_met("has_arcana:GEMINI", payload)))
        self.assertTrue(bool(objective_unlock_met("has_weapon:WHIP", payload)))
        self.assertTrue(bool(objective_unlock_met("has_passive:CLOVER", payload)))
        self.assertTrue(bool(objective_unlock_met("has_stage:FOREST", payload)))
        self.assertFalse(bool(objective_unlock_met("has_stage:LIBRARY", payload)))

    def test_full_triad_signal(self) -> None:
        payload = {
            "collection_ratio": 1.0,
            "bestiary_ratio": 1.0,
            "steam_achievements_ratio": 1.0,
        }
        self.assertTrue(bool(objective_unlock_met("completion:full_triad", payload)))
        self.assertIsNone(objective_unlock_met("completion:unknown", payload))

    def test_unknown_signal_returns_none(self) -> None:
        payload = {"collection_ratio": 1.0}
        self.assertIsNone(objective_unlock_met("weapon_unlock:whip", payload))
        self.assertIsNone(objective_unlock_met("invalid", payload))


if __name__ == "__main__":
    unittest.main()

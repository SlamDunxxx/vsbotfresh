from __future__ import annotations

import unittest

from vs_overseer.memory_backend import (
    BESTIARY_TARGET_ENTRIES,
    COLLECTION_TARGET_ENTRIES,
    STEAM_ACHIEVEMENTS_TARGET,
    signal_from_save_payload,
)


class MemoryBackendSignalTests(unittest.TestCase):
    def test_signal_from_save_payload_emits_completion_metrics(self) -> None:
        payload = {
            "UnlockedCharacters": ["ANTONIO", "IMELDA"],
            "UnlockedArcanas": ["GEMINI"],
            "UnlockedStages": ["FOREST", "LIBRARY"],
            "UnlockedWeapons": ["WHIP", "POWER", "ARMOR", "MAGIC_MISSILE"],
            "CollectedWeapons": ["WHIP", "AXE", "WHIP"],
            "CollectedItems": ["CLOVER", "ROAST"],
            "UnlockedRelics": ["ARS_GOUDA"],
            "Achievements": ["A1", "A2", "A3"],
            "KillCount": {"BAT": 5, "ZOMBIE": 0, "WOLF": 12},
        }

        signal = signal_from_save_payload(payload, source="unit-test")

        self.assertEqual(signal.collection_entries, 6)
        self.assertEqual(signal.collection_target, COLLECTION_TARGET_ENTRIES)
        self.assertAlmostEqual(signal.collection_ratio or 0.0, 6.0 / float(COLLECTION_TARGET_ENTRIES), places=6)

        self.assertEqual(signal.bestiary_entries, 2)
        self.assertEqual(signal.bestiary_target, BESTIARY_TARGET_ENTRIES)
        self.assertAlmostEqual(signal.bestiary_ratio or 0.0, 2.0 / float(BESTIARY_TARGET_ENTRIES), places=6)

        self.assertEqual(signal.steam_achievements, 3)
        self.assertEqual(signal.steam_achievements_target, STEAM_ACHIEVEMENTS_TARGET)
        self.assertAlmostEqual(signal.steam_achievements_ratio or 0.0, 3.0 / float(STEAM_ACHIEVEMENTS_TARGET), places=6)

        self.assertEqual(signal.unlocked_characters_count, 2)
        self.assertEqual(signal.unlocked_arcanas_count, 1)
        self.assertEqual(signal.unlocked_stages_count, 2)
        self.assertIn("WHIP", signal.unlocked_weapons or [])
        self.assertEqual(signal.unlocked_weapons_count, 2)
        self.assertIn("POWER", signal.unlocked_passives or [])
        self.assertIn("ARMOR", signal.unlocked_passives or [])
        self.assertIn("CLOVER", signal.unlocked_passives or [])
        self.assertEqual(signal.unlocked_passives_count, 3)

        self.assertGreaterEqual(signal.objective_hint, 0.0)
        self.assertLessEqual(signal.objective_hint, 1.0)
        self.assertGreaterEqual(signal.stability_hint, 0.0)
        self.assertLessEqual(signal.stability_hint, 1.0)

    def test_signal_from_save_payload_handles_missing_fields(self) -> None:
        signal = signal_from_save_payload({}, source="unit-test")
        self.assertEqual(signal.collection_entries, 0)
        self.assertEqual(signal.bestiary_entries, 0)
        self.assertEqual(signal.steam_achievements, 0)
        self.assertEqual(signal.collection_ratio, 0.0)
        self.assertEqual(signal.bestiary_ratio, 0.0)
        self.assertEqual(signal.steam_achievements_ratio, 0.0)
        self.assertEqual(signal.unlocked_characters_count, 0)
        self.assertEqual(signal.unlocked_arcanas_count, 0)
        self.assertEqual(signal.unlocked_stages_count, 0)
        self.assertEqual(signal.unlocked_weapons_count, 0)
        self.assertEqual(signal.unlocked_passives_count, 0)


if __name__ == "__main__":
    unittest.main()

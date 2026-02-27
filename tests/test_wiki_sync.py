from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from vs_overseer.wiki_sync import WikiSyncer


class WikiSyncTests(unittest.TestCase):
    def _write_sources(self, root: Path) -> Path:
        payload = {
            "totals": [
                {
                    "key": "bestiary_target",
                    "default": 360,
                    "url": "https://example.test/bestiary",
                    "patterns": ["([0-9]{3})\\s+entries"],
                },
                {
                    "key": "steam_achievements_target",
                    "default": 243,
                    "url": "https://example.test/achievements",
                    "patterns": ["([0-9]{3})\\s+achievements"],
                },
            ]
        }
        path = root / "wiki_sources.json"
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        return path

    def _write_mapping(self, root: Path) -> Path:
        payload = {
            "templates": [
                {
                    "id_prefix": "wiki_bestiary_count",
                    "targets": [20, 35, 50, 80, 120, 200, 300, 360],
                },
                {
                    "id_prefix": "wiki_achievements_count",
                    "targets": [10, 25, 50, 75, 100, 150, 200, 243],
                },
            ]
        }
        path = root / "wiki_progression.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    def test_sync_updates_mapping_targets_from_fetched_totals(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-wikisync-") as td:
            root = Path(td)
            sources = self._write_sources(root)
            mapping = self._write_mapping(root)

            def _fake_fetch(url: str, timeout_s: float) -> str:
                _ = timeout_s
                if "bestiary" in url:
                    return "There are 400 entries."
                return "There are 250 achievements."

            syncer = WikiSyncer(
                sources_path=sources,
                mapping_path=mapping,
                timeout_seconds=2.0,
                fetch_text=_fake_fetch,
            )
            result = syncer.sync()
            self.assertTrue(result.ok)
            self.assertTrue(result.changed)
            self.assertEqual(result.totals.get("bestiary_target"), 400)
            self.assertEqual(result.totals.get("steam_achievements_target"), 250)

            payload = json.loads(mapping.read_text(encoding="utf-8"))
            templates = {row.get("id_prefix"): row for row in payload.get("templates", [])}
            bestiary_targets = templates["wiki_bestiary_count"]["targets"]
            achievement_targets = templates["wiki_achievements_count"]["targets"]
            self.assertEqual(int(bestiary_targets[-1]), 400)
            self.assertEqual(int(achievement_targets[-1]), 250)
            self.assertIn("sync_meta", payload)

    def test_sync_falls_back_to_defaults_on_fetch_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vsbotfresh-wikisync-") as td:
            root = Path(td)
            sources = self._write_sources(root)
            mapping = self._write_mapping(root)

            def _failing_fetch(url: str, timeout_s: float) -> str:
                _ = timeout_s
                raise RuntimeError(f"unreachable:{url}")

            syncer = WikiSyncer(
                sources_path=sources,
                mapping_path=mapping,
                timeout_seconds=2.0,
                fetch_text=_failing_fetch,
            )
            result = syncer.sync()
            self.assertTrue(result.ok)
            self.assertEqual(result.totals.get("bestiary_target"), 360)
            self.assertEqual(result.totals.get("steam_achievements_target"), 243)


if __name__ == "__main__":
    unittest.main()

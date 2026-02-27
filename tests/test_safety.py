from __future__ import annotations

from datetime import timedelta
import unittest

from vs_overseer.config import SafetyConfig
from vs_overseer.safety import SafetyManager, utc_now


class SafetyTests(unittest.TestCase):
    def test_crash_loop_trigger(self) -> None:
        cfg = SafetyConfig(
            crash_loop_limit=3,
            crash_loop_window_minutes=30,
            backoff_seconds=[5, 15, 45],
            allow_destructive_actions=False,
        )
        manager = SafetyManager(cfg)
        now = utc_now()
        manager.record_recovery(now - timedelta(minutes=5))
        manager.record_recovery(now - timedelta(minutes=4))
        self.assertFalse(manager.crash_loop_triggered())
        manager.record_recovery(now - timedelta(minutes=3))
        self.assertTrue(manager.crash_loop_triggered())

    def test_destructive_actions_block_by_default(self) -> None:
        cfg = SafetyConfig(
            crash_loop_limit=3,
            crash_loop_window_minutes=30,
            backoff_seconds=[5, 15, 45],
            allow_destructive_actions=False,
        )
        manager = SafetyManager(cfg)

        messages: list[str] = []
        ok, reason = manager.require_destructive_flag(
            operation="reset_save",
            destructive_flag=False,
            audit_logger=messages.append,
        )
        self.assertFalse(ok)
        self.assertIn("destructive_action_blocked", reason)
        self.assertEqual(len(messages), 1)


if __name__ == "__main__":
    unittest.main()

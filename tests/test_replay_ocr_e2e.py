from __future__ import annotations

import json
from pathlib import Path
import unittest

from vs_overseer.game_input import MENU_ACTIONABLE_STATES, GameInputDaemon


def _build_daemon() -> GameInputDaemon:
    daemon = GameInputDaemon.__new__(GameInputDaemon)
    daemon.dry_run = True
    daemon.menu_action_interval_seconds = 0.0
    daemon.menu_state_retry_interval_seconds = 0.0
    daemon.gameplay_confirm_key = "return"
    daemon._menu_upgrade_choice_index = 2
    daemon._target_stage_key = "inlaid_library"
    daemon._target_stage_index = 1
    daemon._target_character_key = "imelda"
    daemon._target_character_index = 1
    daemon.fsm_transition_confirm_seconds = 0.35
    daemon._last_menu_action_mono = 0.0
    daemon._last_menu_action_state = ""
    daemon._last_menu_action_state_mono = 0.0
    daemon._fsm_state = "unknown"
    daemon._fsm_prev_state = ""
    daemon._fsm_last_transition_reason = "initial"
    daemon._fsm_last_transition_at = ""
    daemon._fsm_last_observed_state = ""
    daemon._fsm_last_observed_mono = 0.0
    daemon._fsm_blocked_transitions = 0
    return daemon


class ReplayOcrE2ETests(unittest.TestCase):
    def test_replay_scenarios(self) -> None:
        fixture_path = Path(__file__).resolve().parent / "fixtures" / "replay_ocr" / "scenarios.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        scenarios = payload.get("scenarios", [])
        self.assertTrue(scenarios)

        for scenario in scenarios:
            daemon = _build_daemon()
            now = 100.0
            steps = scenario.get("steps", [])
            self.assertTrue(steps, msg=f"empty scenario:{scenario.get('id')}")
            for step in steps:
                text = str(step.get("ocr_text", ""))
                expected_observed = str(step.get("expected_observed", ""))
                expected_effective = str(step.get("expected_effective", ""))
                expected_action = str(step.get("expected_action", "none"))

                observed_state, observed_reason = GameInputDaemon._classify_menu_state(daemon, text)
                self.assertEqual(
                    observed_state,
                    expected_observed,
                    msg=f"scenario={scenario.get('id')} text={text!r}",
                )
                effective_state, _ = GameInputDaemon._apply_menu_fsm_state(
                    daemon,
                    observed_state=observed_state,
                    observed_reason=observed_reason,
                    now_mono=now,
                )
                self.assertEqual(
                    effective_state,
                    expected_effective,
                    msg=f"scenario={scenario.get('id')} text={text!r}",
                )

                if expected_action == "none":
                    action, error, sent = GameInputDaemon._dispatch_menu_action(
                        daemon,
                        menu_state=effective_state,
                        now_mono=now,
                    )
                    if effective_state in MENU_ACTIONABLE_STATES:
                        self.assertFalse(sent, msg=f"scenario={scenario.get('id')} state={effective_state}")
                        self.assertEqual(action, "none")
                    else:
                        self.assertFalse(sent)
                        self.assertEqual(action, "none")
                    self.assertEqual(error, "")
                else:
                    action, error, sent = GameInputDaemon._dispatch_menu_action(
                        daemon,
                        menu_state=effective_state,
                        now_mono=now,
                    )
                    self.assertTrue(sent, msg=f"scenario={scenario.get('id')} state={effective_state}")
                    self.assertEqual(error, "")
                    self.assertEqual(
                        action,
                        expected_action,
                        msg=f"scenario={scenario.get('id')} state={effective_state}",
                    )
                now += 1.0


if __name__ == "__main__":
    unittest.main()

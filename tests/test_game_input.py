from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from vs_overseer.game_input import (
    _evaluate_arm_payload,
    _is_region_capture_retryable_error,
    _should_allow_unknown_menu_confirm,
    _should_treat_unknown_as_in_run,
    _text_has_menu_keywords,
    _token_to_osascript,
    GameInputDaemon,
    evaluate_nudge,
)


class GameInputTests(unittest.TestCase):
    def test_evaluate_nudge_disabled(self) -> None:
        should, reason, cooldown = evaluate_nudge(
            enabled=False,
            app_running=True,
            save_data_age_seconds=120.0,
            min_save_data_age_seconds=90.0,
            now_mono=1000.0,
            last_nudge_mono=0.0,
            nudge_cooldown_seconds=300.0,
            nudges_sent=0,
            max_nudges_per_session=8,
            force=False,
        )
        self.assertFalse(should)
        self.assertEqual(reason, "disabled_by_config")
        self.assertEqual(cooldown, 0.0)

    def test_evaluate_nudge_force_bypasses_checks(self) -> None:
        should, reason, cooldown = evaluate_nudge(
            enabled=True,
            app_running=True,
            save_data_age_seconds=1.0,
            min_save_data_age_seconds=90.0,
            now_mono=1000.0,
            last_nudge_mono=995.0,
            nudge_cooldown_seconds=300.0,
            nudges_sent=0,
            max_nudges_per_session=8,
            force=True,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "forced")
        self.assertEqual(cooldown, 0.0)

    def test_evaluate_nudge_cooldown_active(self) -> None:
        should, reason, cooldown = evaluate_nudge(
            enabled=True,
            app_running=True,
            save_data_age_seconds=999.0,
            min_save_data_age_seconds=90.0,
            now_mono=1000.0,
            last_nudge_mono=900.0,
            nudge_cooldown_seconds=300.0,
            nudges_sent=1,
            max_nudges_per_session=8,
            force=False,
        )
        self.assertFalse(should)
        self.assertEqual(reason, "cooldown_active")
        self.assertGreater(cooldown, 0.0)

    def test_evaluate_nudge_ready(self) -> None:
        should, reason, cooldown = evaluate_nudge(
            enabled=True,
            app_running=True,
            save_data_age_seconds=240.0,
            min_save_data_age_seconds=90.0,
            now_mono=1000.0,
            last_nudge_mono=0.0,
            nudge_cooldown_seconds=300.0,
            nudges_sent=0,
            max_nudges_per_session=8,
            force=False,
        )
        self.assertTrue(should)
        self.assertEqual(reason, "ready")
        self.assertEqual(cooldown, 0.0)

    def test_token_translation(self) -> None:
        self.assertEqual(_token_to_osascript("return"), "key code 36")
        self.assertEqual(_token_to_osascript("w"), "key code 13")
        self.assertEqual(_token_to_osascript("1"), 'keystroke "1"')
        with self.assertRaises(ValueError):
            _ = _token_to_osascript("unsupported_key")

    def test_select_sequence_escalates(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.sequence = ["return", "return"]
        daemon.stuck_window_seconds = 300.0

        seq1, label1 = GameInputDaemon._select_sequence(daemon, reason="ready", stuck_elapsed_seconds=0.0)
        self.assertEqual(label1, "default")
        self.assertEqual(seq1, ["return", "return"])

        seq2, label2 = GameInputDaemon._select_sequence(daemon, reason="stuck_watchdog", stuck_elapsed_seconds=650.0)
        self.assertEqual(label2, "stuck_medium")
        self.assertIn("escape", seq2)

        seq3, label3 = GameInputDaemon._select_sequence(daemon, reason="stuck_watchdog", stuck_elapsed_seconds=1900.0)
        self.assertEqual(label3, "stuck_deep")
        self.assertGreaterEqual(len(seq3), len(seq2))

    def test_gameplay_direction_cycles(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.gameplay_sequence = ["left", "up", "right"]
        daemon._gameplay_direction_index = 0

        d1 = GameInputDaemon._next_gameplay_direction(daemon)
        d2 = GameInputDaemon._next_gameplay_direction(daemon)
        d3 = GameInputDaemon._next_gameplay_direction(daemon)
        d4 = GameInputDaemon._next_gameplay_direction(daemon)

        self.assertEqual([d1, d2, d3, d4], ["left", "up", "right", "left"])

    def test_arm_payload_evaluation(self) -> None:
        now = datetime(2026, 2, 27, 5, 0, tzinfo=timezone.utc)
        ok, reason = _evaluate_arm_payload(require_arm_file=True, payload={}, now_utc=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "arm_missing")

        ok2, reason2 = _evaluate_arm_payload(require_arm_file=False, payload={}, now_utc=now)
        self.assertTrue(ok2)
        self.assertEqual(reason2, "arm_not_required")

        payload = {
            "armed": True,
            "expires_at": (now + timedelta(minutes=5)).isoformat(),
        }
        ok3, reason3 = _evaluate_arm_payload(require_arm_file=True, payload=payload, now_utc=now)
        self.assertTrue(ok3)
        self.assertEqual(reason3, "armed")

    def test_menu_classification(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        state1, _ = GameInputDaemon._classify_menu_state(daemon, "PRESS TO START")
        state2, _ = GameInputDaemon._classify_menu_state(daemon, "LEVEL UP REROLL SKIP")
        state3, _ = GameInputDaemon._classify_menu_state(daemon, "GAME OVER")
        state3b, _ = GameInputDaemon._classify_menu_state(daemon, "REVIVE QUIT")
        state3c, _ = GameInputDaemon._classify_menu_state(
            daemon,
            "Results Survived: 00:13 Gold earned Level reached Enemies defeated",
        )
        state3d, _ = GameInputDaemon._classify_menu_state(
            daemon,
            "00:12 gold 10 kills 29 whip level 1",
        )
        state4, _ = GameInputDaemon._classify_menu_state(
            daemon,
            "Vampire Survivors Start Power Up Collection Unlocks Options",
        )
        self.assertEqual(state1, "title_screen")
        self.assertEqual(state2, "level_up")
        self.assertEqual(state3, "game_over")
        self.assertEqual(state3b, "game_over")
        self.assertEqual(state3c, "run_results")
        self.assertEqual(state3d, "in_run")
        self.assertEqual(state4, "main_menu")

    def test_text_has_menu_keywords(self) -> None:
        self.assertTrue(_text_has_menu_keywords("Game Over  Quit  Revive"))
        self.assertTrue(_text_has_menu_keywords("Stage Selection"))
        self.assertFalse(_text_has_menu_keywords("@ - (= Meat, WSS Tie pedi"))

    def test_region_capture_retryable_error(self) -> None:
        self.assertTrue(_is_region_capture_retryable_error("could not create image from rect"))
        self.assertTrue(_is_region_capture_retryable_error("invalid rect"))
        self.assertFalse(_is_region_capture_retryable_error("permission denied"))

    def test_unknown_run_candidate_requires_recent_in_run(self) -> None:
        self.assertFalse(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=3.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=10.0,
            )
        )
        self.assertTrue(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=3.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertTrue(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=3.0,
                in_run_recent=True,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertFalse(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=True,
                menu_ocr_error="",
                save_age_seconds=3.0,
                in_run_recent=True,
                save_stall_elapsed_seconds=10.0,
            )
        )
        self.assertFalse(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=3.0,
                in_run_recent=True,
                save_stall_elapsed_seconds=6.0,
            )
        )
        self.assertTrue(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=False,
                unknown_has_menu_keywords=False,
                menu_ocr_error="capture_error",
                save_age_seconds=2.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertFalse(
            _should_treat_unknown_as_in_run(
                menu_state="unknown",
                menu_ocr_ok=False,
                unknown_has_menu_keywords=False,
                menu_ocr_error="capture_error",
                save_age_seconds=2.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=6.0,
            )
        )

    def test_unknown_menu_confirm_prefers_menu_when_not_recent_run(self) -> None:
        self.assertFalse(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=4.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=10.0,
            )
        )
        self.assertFalse(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=4.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertFalse(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=False,
                menu_ocr_error="",
                save_age_seconds=4.0,
                in_run_recent=True,
                save_stall_elapsed_seconds=10.0,
            )
        )
        self.assertTrue(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=True,
                menu_ocr_error="",
                save_age_seconds=4.0,
                in_run_recent=True,
                save_stall_elapsed_seconds=10.0,
            )
        )
        self.assertFalse(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=True,
                unknown_has_menu_keywords=True,
                menu_ocr_error="",
                save_age_seconds=4.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertFalse(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=False,
                unknown_has_menu_keywords=False,
                menu_ocr_error="capture_error",
                save_age_seconds=2.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=1.0,
            )
        )
        self.assertTrue(
            _should_allow_unknown_menu_confirm(
                menu_state="unknown",
                menu_ocr_ok=False,
                unknown_has_menu_keywords=False,
                menu_ocr_error="capture_error",
                save_age_seconds=2.0,
                in_run_recent=False,
                save_stall_elapsed_seconds=6.0,
            )
        )

    def test_menu_fsm_blocks_unexpected_transition_then_confirms_repeated(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.fsm_transition_confirm_seconds = 0.35
        daemon._fsm_state = "main_menu"
        daemon._fsm_prev_state = ""
        daemon._fsm_last_transition_reason = "initial"
        daemon._fsm_last_transition_at = ""
        daemon._fsm_last_observed_state = ""
        daemon._fsm_last_observed_mono = 0.0
        daemon._fsm_blocked_transitions = 0

        state1, reason1 = GameInputDaemon._apply_menu_fsm_state(
            daemon,
            observed_state="game_over",
            observed_reason="matched_game_over",
            now_mono=100.0,
        )
        self.assertEqual(state1, "unknown")
        self.assertIn("fsm_blocked:main_menu->game_over", reason1)
        self.assertEqual(daemon._fsm_state, "main_menu")

        state2, reason2 = GameInputDaemon._apply_menu_fsm_state(
            daemon,
            observed_state="game_over",
            observed_reason="matched_game_over",
            now_mono=101.0,
        )
        self.assertEqual(state2, "game_over")
        self.assertIn("fsm_transition:", reason2)
        self.assertEqual(daemon._fsm_state, "game_over")

    def test_upgrade_choice_prefers_scored_line(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        lines = [
            (120, "Garlic"),
            (180, "Empty Tome"),
            (240, "Armor"),
        ]
        idx, reason = GameInputDaemon._choose_upgrade_index_from_lines(daemon, lines, 1080)
        self.assertEqual(idx, 1)
        self.assertIn("scored_choice", reason)

    def test_focus_gate_disabled_allows_input(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.pause_when_unfocused = False
        daemon.app_name = "Vampire Survivors"
        focused, reason, pid, name = GameInputDaemon._game_focus_state(daemon, app_running=True, pids=[123])
        self.assertTrue(focused)
        self.assertEqual(reason, "focus_gate_disabled")
        self.assertIsNone(pid)
        self.assertEqual(name, "")

    def test_focus_gate_matches_frontmost_pid(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.pause_when_unfocused = True
        daemon.app_name = "Vampire Survivors"
        daemon._frontmost_process = lambda: (4242, "Some Other Name", "")  # type: ignore[method-assign]
        focused, reason, _, _ = GameInputDaemon._game_focus_state(daemon, app_running=True, pids=[111, 4242])
        self.assertTrue(focused)
        self.assertEqual(reason, "focused_by_pid")

    def test_focus_gate_matches_frontmost_name(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.pause_when_unfocused = True
        daemon.app_name = "Vampire Survivors"
        daemon._frontmost_process = lambda: (9999, "Vampire Survivors", "")  # type: ignore[method-assign]
        focused, reason, _, _ = GameInputDaemon._game_focus_state(daemon, app_running=True, pids=[111, 222])
        self.assertTrue(focused)
        self.assertEqual(reason, "focused_by_name")

    def test_focus_gate_blocks_when_unfocused_or_unknown(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon.pause_when_unfocused = True
        daemon.app_name = "Vampire Survivors"
        daemon._frontmost_process = lambda: (8888, "Messages", "")  # type: ignore[method-assign]
        focused, reason, _, _ = GameInputDaemon._game_focus_state(daemon, app_running=True, pids=[111, 222])
        self.assertFalse(focused)
        self.assertEqual(reason, "game_not_frontmost")

        daemon._frontmost_process = lambda: (None, "", "osascript_failed")  # type: ignore[method-assign]
        focused2, reason2, _, _ = GameInputDaemon._game_focus_state(daemon, app_running=True, pids=[111, 222])
        self.assertFalse(focused2)
        self.assertIn("focus_check_error", reason2)

    def test_unknown_menu_confirm_dry_run(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon._last_menu_action_mono = 0.0
        daemon.unknown_menu_confirm_interval_seconds = 2.0
        daemon.dry_run = True
        daemon.gameplay_confirm_key = "return"

        action, error, sent = GameInputDaemon._dispatch_unknown_menu_confirm(daemon, now_mono=100.0)
        self.assertTrue(sent)
        self.assertEqual(error, "")
        self.assertEqual(action, "menu_unknown_confirm_dry_run")

    def test_main_menu_action_dry_run(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon._last_menu_action_mono = 0.0
        daemon.menu_action_interval_seconds = 0.6
        daemon._menu_upgrade_choice_index = 0
        daemon._target_stage_key = "mad_forest"
        daemon._target_stage_index = 0
        daemon._target_character_key = "antonio"
        daemon._target_character_index = 0
        daemon.dry_run = True
        daemon.gameplay_confirm_key = "return"

        action, error, sent = GameInputDaemon._dispatch_menu_action(
            daemon,
            menu_state="main_menu",
            now_mono=100.0,
        )
        self.assertTrue(sent)
        self.assertEqual(error, "")
        self.assertEqual(action, "menu_main_menu_start_dry_run")

    def test_character_and_stage_action_dry_run(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon._last_menu_action_mono = 0.0
        daemon.menu_action_interval_seconds = 0.0
        daemon._menu_upgrade_choice_index = 0
        daemon._target_stage_key = "dairy_plant"
        daemon._target_stage_index = 2
        daemon._target_character_key = "imelda"
        daemon._target_character_index = 1
        daemon.dry_run = True
        daemon.gameplay_confirm_key = "return"

        action1, error1, sent1 = GameInputDaemon._dispatch_menu_action(
            daemon,
            menu_state="character_select",
            now_mono=100.0,
        )
        action2, error2, sent2 = GameInputDaemon._dispatch_menu_action(
            daemon,
            menu_state="stage_select",
            now_mono=101.0,
        )
        self.assertTrue(sent1)
        self.assertEqual(error1, "")
        self.assertEqual(action1, "menu_character_select_imelda_1_dry_run")
        self.assertTrue(sent2)
        self.assertEqual(error2, "")
        self.assertEqual(action2, "menu_stage_select_dairy_plant_2_dry_run")

    def test_game_over_action_dry_run(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        daemon._last_menu_action_mono = 0.0
        daemon.menu_action_interval_seconds = 0.0
        daemon.menu_state_retry_interval_seconds = 0.0
        daemon._menu_upgrade_choice_index = 0
        daemon._target_stage_key = "mad_forest"
        daemon._target_stage_index = 0
        daemon._target_character_key = "antonio"
        daemon._target_character_index = 0
        daemon.dry_run = True
        daemon.gameplay_confirm_key = "return"

        action, error, sent = GameInputDaemon._dispatch_menu_action(
            daemon,
            menu_state="game_over",
            now_mono=100.0,
        )
        self.assertTrue(sent)
        self.assertEqual(error, "")
        self.assertEqual(action, "menu_game_over_quit_confirm_dry_run")

    def test_stage_target_from_objective_prefers_unlocked_prereq_stage(self) -> None:
        daemon = GameInputDaemon.__new__(GameInputDaemon)
        key, idx, reason = GameInputDaemon._select_stage_target(
            daemon,
            objective_context={
                "next_objective_category": "stage",
                "next_objective_signal": "unlocked_stages_count:8",
            },
            memory_context={
                "unlocked_stages": ["FOREST", "TP_CASTLE"],
            },
        )
        self.assertEqual(key, "inlaid_library")
        self.assertEqual(idx, 1)
        self.assertIn("objective_stage_prereq_for_missing:dairy_plant:inlaid_library", reason)


if __name__ == "__main__":
    unittest.main()

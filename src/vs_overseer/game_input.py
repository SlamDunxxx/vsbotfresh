from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import subprocess
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any

from .config import AppConfig


KEY_CODE_MAP = {
    "return": "key code 36",
    "enter": "key code 36",
    "space": "key code 49",
    "escape": "key code 53",
    "esc": "key code 53",
    "up": "key code 126",
    "down": "key code 125",
    "left": "key code 123",
    "right": "key code 124",
    "tab": "key code 48",
    "a": "key code 0",
    "s": "key code 1",
    "d": "key code 2",
    "w": "key code 13",
}

MENU_ACTIONABLE_STATES = {
    "title_screen",
    "main_menu",
    "character_select",
    "stage_select",
    "pause_menu",
    "game_over",
    "run_results",
    "level_up",
}

MENU_FSM_TRANSITIONS: dict[str, set[str]] = {
    "unknown": {
        "unknown",
        "game_not_running",
        "title_screen",
        "main_menu",
        "character_select",
        "stage_select",
        "pause_menu",
        "game_over",
        "run_results",
        "level_up",
        "in_run",
    },
    "game_not_running": {"game_not_running", "unknown", "title_screen", "main_menu"},
    "title_screen": {"title_screen", "unknown", "main_menu"},
    "main_menu": {"main_menu", "unknown", "character_select", "title_screen"},
    "character_select": {"character_select", "unknown", "main_menu", "stage_select"},
    "stage_select": {"stage_select", "unknown", "main_menu", "character_select", "in_run"},
    "in_run": {"in_run", "unknown", "level_up", "pause_menu", "game_over", "run_results"},
    "level_up": {"level_up", "unknown", "in_run", "game_over", "run_results"},
    "pause_menu": {"pause_menu", "unknown", "in_run", "main_menu"},
    "game_over": {"game_over", "unknown", "run_results", "main_menu"},
    "run_results": {"run_results", "unknown", "main_menu", "character_select"},
}

MENU_FSM_KNOWN_STATES = set(MENU_FSM_TRANSITIONS.keys())

UPGRADE_SCORE_HINTS = {
    "empty tome": 120.0,
    "duplicator": 110.0,
    "spinach": 105.0,
    "candelabrador": 100.0,
    "attractorb": 95.0,
    "king bible": 94.0,
    "lightning ring": 93.0,
    "santa water": 92.0,
    "runetracer": 88.0,
    "axe": 82.0,
    "cross": 81.0,
    "garlic": 78.0,
    "whip": 75.0,
    "laurel": 70.0,
    "clock lancet": 66.0,
    "armor": 64.0,
    "wings": 52.0,
    "crown": 50.0,
    "luck": 46.0,
}


UNKNOWN_RUN_OCR_FRESH_SAVE_SECONDS = 20.0
UNKNOWN_RUN_SAVE_HEARTBEAT_SECONDS = 2.5

STAGE_ROUTE = [
    {"key": "mad_forest", "menu_index": 0, "aliases": {"mad forest", "forest"}},
    {"key": "inlaid_library", "menu_index": 1, "aliases": {"inlaid library", "library", "tp castle", "castle"}},
    {"key": "dairy_plant", "menu_index": 2, "aliases": {"dairy plant", "plant"}},
    {"key": "gallo_tower", "menu_index": 3, "aliases": {"gallo tower", "tower"}},
    {"key": "cappella_magna", "menu_index": 4, "aliases": {"cappella magna", "cappella"}},
    {"key": "bone_zone", "menu_index": 5, "aliases": {"bone zone", "bone"}},
]

CHARACTER_ROUTE = [
    {"key": "antonio", "menu_index": 0, "aliases": {"antonio"}},
    {"key": "imelda", "menu_index": 1, "aliases": {"imelda"}},
    {"key": "pasqualina", "menu_index": 2, "aliases": {"pasqualina"}},
    {"key": "gennaro", "menu_index": 3, "aliases": {"gennaro"}},
    {"key": "arca", "menu_index": 4, "aliases": {"arca"}},
    {"key": "porta", "menu_index": 5, "aliases": {"porta"}},
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def _escape_osascript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _normalize_ocr_match_text(raw: str) -> str:
    lowered = str(raw).lower()
    cleaned = re.sub(r"[^a-z0-9:]+", " ", lowered)
    return " ".join(cleaned.split())


def _text_has_menu_keywords(raw: str) -> bool:
    normalized = _normalize_ocr_match_text(raw)
    if not normalized:
        return False
    tokens = (
        "press to start",
        "start",
        "game over",
        "revive",
        "quit",
        "results",
        "survived",
        "enemies defeated",
        "gold earned",
        "level reached",
        "level up",
        "reroll",
        "skip",
        "banish",
        "seal",
        "character",
        "stage",
        "selection",
        "resume",
        "options",
        "power up",
        "collection",
        "unlocks",
        "bestiary",
        "armory",
        "login",
        "linked",
        "account",
        "loading",
    )
    return any(token in normalized for token in tokens)


def _subprocess_error_detail(completed: subprocess.CompletedProcess[str]) -> str:
    stderr = str(completed.stderr).strip()
    stdout = str(completed.stdout).strip()
    return stderr or stdout or f"process_exit_{completed.returncode}"


def _is_region_capture_retryable_error(raw: str) -> bool:
    normalized = _normalize_ocr_match_text(raw)
    if not normalized:
        return False
    markers = (
        "could not create image from rect",
        "could not create image from rectangle",
        "invalid rect",
        "illegal rectangle",
    )
    return any(marker in normalized for marker in markers)


def _signal_key_from_unlock_signal(unlock_signal: str) -> str:
    raw = str(unlock_signal).strip()
    if ":" not in raw:
        return ""
    key, _, _ = raw.partition(":")
    return str(key).strip().lower()


def _normalize_entity_token(raw: str) -> str:
    return _normalize_ocr_match_text(str(raw).replace("_", " "))


def _normalize_entity_set(rows: list[str]) -> set[str]:
    out: set[str] = set()
    for row in rows:
        token = _normalize_entity_token(row)
        if token:
            out.add(token)
    return out


def _entry_matches_aliases(entry: dict[str, Any], unlocked_tokens: set[str]) -> bool:
    aliases = {_normalize_entity_token(x) for x in entry.get("aliases", set())}
    for alias in aliases:
        if not alias:
            continue
        for token in unlocked_tokens:
            if alias in token or token in alias:
                return True
    return False


def _should_treat_unknown_as_in_run(
    *,
    menu_state: str,
    menu_ocr_ok: bool,
    unknown_has_menu_keywords: bool,
    menu_ocr_error: str,
    save_age_seconds: float | None,
    in_run_recent: bool,
    save_stall_elapsed_seconds: float | None,
) -> bool:
    if str(menu_state) != "unknown":
        return False
    save_stall_fresh = bool(
        save_stall_elapsed_seconds is not None
        and float(save_stall_elapsed_seconds) <= UNKNOWN_RUN_SAVE_HEARTBEAT_SECONDS
    )
    save_recent = bool(
        save_age_seconds is not None
        and float(save_age_seconds) < UNKNOWN_RUN_OCR_FRESH_SAVE_SECONDS
    )
    if menu_ocr_ok:
        if not in_run_recent:
            # Fresh save writes during unknown OCR strongly indicate in-run state.
            return bool((not unknown_has_menu_keywords) and save_stall_fresh and save_recent)
        if unknown_has_menu_keywords:
            return False
        # Keep movement active when OCR briefly degrades, unless menu markers appear.
        return True
    if str(menu_ocr_error).strip() == "":
        return False
    if not save_recent:
        return False
    if in_run_recent:
        return True
    return save_stall_fresh


def _should_allow_unknown_menu_confirm(
    *,
    menu_state: str,
    menu_ocr_ok: bool,
    unknown_has_menu_keywords: bool,
    menu_ocr_error: str,
    save_age_seconds: float | None,
    in_run_recent: bool,
    save_stall_elapsed_seconds: float | None,
) -> bool:
    if str(menu_state) != "unknown":
        return False
    save_stall_fresh = bool(
        save_stall_elapsed_seconds is not None
        and float(save_stall_elapsed_seconds) <= UNKNOWN_RUN_SAVE_HEARTBEAT_SECONDS
    )
    save_recent = bool(
        save_age_seconds is not None
        and float(save_age_seconds) < UNKNOWN_RUN_OCR_FRESH_SAVE_SECONDS
    )

    if menu_ocr_ok:
        if not unknown_has_menu_keywords:
            # Hard-safe: avoid blind confirms when OCR does not look like a menu.
            return False
        if save_stall_fresh and save_recent:
            return False
        return True

    if str(menu_ocr_error).strip() == "":
        return False
    if in_run_recent:
        return False
    if save_age_seconds is None:
        return True
    if float(save_age_seconds) >= UNKNOWN_RUN_OCR_FRESH_SAVE_SECONDS:
        return True
    if save_stall_fresh:
        # Recent save writes strongly indicate in-run activity; avoid blind confirms.
        return False
    return True


def _token_to_osascript(token: str) -> str:
    key = str(token).strip().lower()
    if key in KEY_CODE_MAP:
        return KEY_CODE_MAP[key]
    if len(key) == 1 and key.isascii() and key.isalnum():
        return f'keystroke "{key}"'
    raise ValueError(f"unsupported_key_token:{token}")


def _token_to_key_code_number(token: str) -> int:
    key_stmt = _token_to_osascript(token)
    if not key_stmt.startswith("key code "):
        raise ValueError(f"hold_requires_key_code:{token}")
    return int(str(key_stmt).split()[-1])


def _parse_iso8601_utc(raw: str) -> datetime | None:
    token = str(raw).strip()
    if not token:
        return None
    try:
        if token.endswith("Z"):
            token = token[:-1] + "+00:00"
        parsed = datetime.fromisoformat(token)
    except Exception:  # noqa: BLE001
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _evaluate_arm_payload(
    *,
    require_arm_file: bool,
    payload: dict[str, Any] | None,
    now_utc: datetime | None = None,
) -> tuple[bool, str]:
    if not require_arm_file:
        return (True, "arm_not_required")

    if not isinstance(payload, dict) or not payload:
        return (False, "arm_missing")
    if not bool(payload.get("armed", False)):
        return (False, "arm_disarmed")
    expires_raw = str(payload.get("expires_at", "")).strip()
    expires_at = _parse_iso8601_utc(expires_raw)
    if expires_at is None:
        return (False, "arm_invalid_expiry")

    now = now_utc or _utc_now()
    if now >= expires_at:
        return (False, "arm_expired")
    return (True, "armed")


def set_game_input_arm_state(
    cfg: AppConfig,
    *,
    armed: bool,
    minutes: float = 15.0,
    reason: str = "",
    menu_only: bool = False,
) -> dict[str, Any]:
    path = cfg.resolve(cfg.game_input.arm_file)
    now = _utc_now()
    expiry = ""
    if armed:
        expiry = (now + timedelta(minutes=max(0.1, float(minutes)))).isoformat()
    payload: dict[str, Any] = {
        "armed": bool(armed),
        "expires_at": expiry,
        "reason": str(reason).strip(),
        "menu_only": bool(menu_only),
        "updated_at": now.isoformat(),
    }
    _write_json_atomic(path, payload)
    ok, state = _evaluate_arm_payload(
        require_arm_file=bool(cfg.game_input.require_arm_file),
        payload=payload,
        now_utc=now,
    )
    return {
        "ok": bool(ok),
        "state": state,
        "arm_file": str(path),
        "payload": payload,
    }


def get_game_input_arm_state(cfg: AppConfig) -> dict[str, Any]:
    path = cfg.resolve(cfg.game_input.arm_file)
    payload = _read_json(path) if path.exists() else {}
    ok, state = _evaluate_arm_payload(
        require_arm_file=bool(cfg.game_input.require_arm_file),
        payload=payload,
    )
    return {
        "ok": bool(ok),
        "state": state,
        "require_arm_file": bool(cfg.game_input.require_arm_file),
        "arm_file": str(path),
        "payload": payload,
    }


def evaluate_nudge(
    *,
    enabled: bool,
    app_running: bool,
    save_data_age_seconds: float | None,
    min_save_data_age_seconds: float,
    now_mono: float,
    last_nudge_mono: float,
    nudge_cooldown_seconds: float,
    nudges_sent: int,
    max_nudges_per_session: int,
    force: bool,
) -> tuple[bool, str, float]:
    if not enabled:
        return (False, "disabled_by_config", 0.0)
    if not app_running:
        return (False, "game_not_running", 0.0)
    if nudges_sent >= max(1, int(max_nudges_per_session)):
        return (False, "session_nudge_limit_reached", 0.0)
    if force:
        return (True, "forced", 0.0)
    if save_data_age_seconds is None:
        return (False, "save_data_age_unknown", 0.0)
    if save_data_age_seconds < max(0.0, float(min_save_data_age_seconds)):
        return (False, "save_data_recent", 0.0)

    if last_nudge_mono > 0.0:
        elapsed = max(0.0, now_mono - last_nudge_mono)
        cooldown = max(0.0, float(nudge_cooldown_seconds))
        if elapsed < cooldown:
            return (False, "cooldown_active", cooldown - elapsed)
    return (True, "ready", 0.0)


@dataclass
class GameInputResult:
    ok: bool
    payload: dict[str, Any]


class GameInputDaemon:
    def __init__(
        self,
        cfg: AppConfig,
        *,
        status_output_override: str = "",
        interval_override: float | None = None,
        dry_run_override: bool | None = None,
    ) -> None:
        self.cfg = cfg
        self.app_name = str(cfg.game_input.app_name).strip() or "Vampire Survivors"
        self.watch_interval_seconds = (
            max(1.0, float(interval_override))
            if interval_override is not None and interval_override > 0.0
            else max(0.2, float(cfg.game_input.watch_interval_seconds))
        )
        self.require_arm_file = bool(cfg.game_input.require_arm_file)
        self.arm_file = cfg.resolve(cfg.game_input.arm_file)
        self.pause_when_unfocused = bool(cfg.game_input.pause_when_unfocused)
        self.gameplay_enabled = bool(cfg.game_input.gameplay_enabled)
        self.gameplay_interval_seconds = max(0.2, float(cfg.game_input.gameplay_interval_seconds))
        self.gameplay_hold_seconds = max(0.05, float(cfg.game_input.gameplay_hold_seconds))
        self.gameplay_sequence = [
            str(token).strip().lower()
            for token in cfg.game_input.gameplay_sequence
            if str(token).strip()
        ]
        if not self.gameplay_sequence:
            self.gameplay_sequence = ["left", "up", "right", "down"]
        self.gameplay_confirm_enabled = bool(cfg.game_input.gameplay_confirm_enabled)
        self.gameplay_confirm_interval_seconds = max(0.2, float(cfg.game_input.gameplay_confirm_interval_seconds))
        self.gameplay_confirm_key = str(cfg.game_input.gameplay_confirm_key).strip().lower() or "return"
        self.menu_detection_enabled = bool(cfg.game_input.menu_detection_enabled)
        self.menu_scan_interval_seconds = max(0.5, float(cfg.game_input.menu_scan_interval_seconds))
        self.fsm_transition_confirm_seconds = max(0.0, float(cfg.game_input.fsm_transition_confirm_seconds))
        self.menu_action_interval_seconds = 0.6
        self.menu_state_retry_interval_seconds = 1.0
        self.menu_state_sticky_seconds = 2.5
        self.unknown_menu_confirm_interval_seconds = 2.0
        self.unknown_in_run_grace_seconds = 90.0
        self.tesseract_cmd = shutil.which("tesseract") or "/usr/local/bin/tesseract"
        self.min_save_data_age_seconds = max(0.0, float(cfg.game_input.min_save_data_age_seconds))
        self.nudge_cooldown_seconds = max(0.0, float(cfg.game_input.nudge_cooldown_seconds))
        self.max_nudges_per_session = max(1, int(cfg.game_input.max_nudges_per_session))
        self.key_delay_seconds = max(0.05, float(cfg.game_input.key_delay_seconds))
        self.sequence = [str(token).strip().lower() for token in cfg.game_input.title_nudge_sequence if str(token).strip()]
        if not self.sequence:
            self.sequence = ["return", "return", "return", "return", "return"]
        self.status_file = cfg.resolve(status_output_override or cfg.game_input.status_file)
        self.save_data_path = cfg.resolve(cfg.live.save_data_path) if str(cfg.live.save_data_path).strip() else None
        self.memory_signal_path = cfg.resolve(cfg.live.memory_signal_file) if str(cfg.live.memory_signal_file).strip() else None
        self.health_path = cfg.resolve(cfg.reporting.status_file)
        self.summary_path = cfg.resolve(cfg.reporting.latest_summary_file)
        self.enabled = bool(cfg.game_input.enabled)
        self.dry_run = bool(cfg.game_input.dry_run) if dry_run_override is None else bool(dry_run_override)
        self.stuck_watchdog_enabled = bool(cfg.game_input.stuck_watchdog_enabled)
        self.stuck_window_seconds = max(30.0, float(cfg.game_input.stuck_window_seconds))
        self.stuck_min_save_data_age_seconds = max(0.0, float(cfg.game_input.stuck_min_save_data_age_seconds))
        self.stuck_recovery_interval_seconds = max(30.0, float(cfg.game_input.stuck_recovery_interval_seconds))
        self.auto_launch_when_not_running = bool(cfg.game_input.auto_launch_when_not_running)
        self.auto_launch_cooldown_seconds = max(5.0, float(cfg.game_input.auto_launch_cooldown_seconds))
        self.auto_launch_command = str(cfg.game_input.auto_launch_command).strip()
        self.objective_stale_threshold_seconds = max(60.0, float(cfg.game_input.objective_stale_threshold_seconds))

        self._session_started_at = utc_now_iso()
        self._last_nudge_mono = 0.0
        self._last_nudge_at = ""
        self._nudges_sent = 0
        self._last_error = ""
        self._last_error_at = ""
        self._gameplay_last_error = ""
        self._gameplay_last_error_at = ""
        self._last_progress_signature = ""
        self._last_progress_change_mono = 0.0
        self._last_progress_change_at = ""
        self._last_stuck_nudge_mono = 0.0
        self._last_seen_save_mtime = 0.0
        self._last_save_change_mono = 0.0
        self._last_save_change_at = ""
        self._last_gameplay_mono = 0.0
        self._last_gameplay_at = ""
        self._gameplay_pulses_sent = 0
        self._last_gameplay_direction = ""
        self._gameplay_direction_index = 0
        self._last_confirm_mono = 0.0
        self._last_menu_scan_mono = 0.0
        self._menu_state = "unknown"
        self._menu_state_reason = "uninitialized"
        self._menu_ocr_ok = False
        self._menu_ocr_error = ""
        self._menu_text_excerpt = ""
        self._menu_capture_mode = "none"
        self._menu_last_scan_at = ""
        self._menu_upgrade_choice_index = 0
        self._menu_upgrade_choice_reason = "default"
        self._last_menu_action_mono = 0.0
        self._last_menu_action_state = ""
        self._last_menu_action_state_mono = 0.0
        self._last_known_menu_state = ""
        self._last_known_menu_state_mono = 0.0
        self._last_in_run_seen_mono = 0.0
        self._last_in_run_seen_at = ""
        self._target_stage_key = ""
        self._target_stage_index = 0
        self._target_stage_reason = "default"
        self._target_character_key = ""
        self._target_character_index = 0
        self._target_character_reason = "default"
        self._fsm_state = "unknown"
        self._fsm_prev_state = ""
        self._fsm_last_transition_reason = "initial"
        self._fsm_last_transition_at = ""
        self._fsm_last_observed_state = ""
        self._fsm_last_observed_mono = 0.0
        self._fsm_blocked_transitions = 0
        self._last_auto_launch_mono = 0.0
        self._last_auto_launch_at = ""
        self._auto_launch_attempts = 0
        self._last_auto_launch_error = ""
        self._last_objective_id = ""
        self._last_objective_change_mono = 0.0
        self._last_objective_change_at = ""

    def _find_game_pids(self) -> list[int]:
        try:
            completed = subprocess.run(
                ["/usr/bin/pgrep", "-f", self.app_name],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except Exception:  # noqa: BLE001
            return []

        pids: list[int] = []
        for row in str(completed.stdout).splitlines():
            token = row.strip()
            if not token:
                continue
            try:
                pids.append(int(token))
            except Exception:  # noqa: BLE001
                continue
        return sorted(set(pids))

    def _frontmost_process(self) -> tuple[int | None, str, str]:
        lines = [
            'tell application "System Events"',
            "set front_proc to first application process whose frontmost is true",
            "set front_pid to unix id of front_proc",
            "set front_name to name of front_proc",
            'return (front_pid as text) & "|" & front_name',
            "end tell",
        ]
        cmd = ["/usr/bin/osascript"]
        for line in lines:
            cmd.extend(["-e", line])
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return (None, "", "osascript_timeout")
        except Exception as exc:  # noqa: BLE001
            return (None, "", f"osascript_exception:{exc}")
        if completed.returncode != 0:
            stderr = str(completed.stderr).strip()
            stdout = str(completed.stdout).strip()
            detail = stderr or stdout or f"osascript_exit_{completed.returncode}"
            return (None, "", detail)

        raw = str(completed.stdout).strip()
        if not raw:
            return (None, "", "frontmost_process_empty")
        pid_raw, _, name_raw = raw.partition("|")
        front_name = str(name_raw).strip()
        front_pid: int | None = None
        try:
            front_pid = int(str(pid_raw).strip())
        except Exception:  # noqa: BLE001
            front_pid = None
        return (front_pid, front_name, "")

    def _game_focus_state(self, *, app_running: bool, pids: list[int]) -> tuple[bool, str, int | None, str]:
        if not self.pause_when_unfocused:
            return (True, "focus_gate_disabled", None, "")
        if not app_running:
            return (False, "game_not_running", None, "")

        front_pid, front_name, focus_error = self._frontmost_process()
        if focus_error != "":
            return (False, f"focus_check_error:{focus_error}", front_pid, front_name)
        if front_pid is not None and front_pid in set(pids):
            return (True, "focused_by_pid", front_pid, front_name)

        expected = str(self.app_name).strip().lower()
        observed = str(front_name).strip().lower()
        if expected and observed and (expected in observed or observed in expected):
            return (True, "focused_by_name", front_pid, front_name)
        return (False, "game_not_frontmost", front_pid, front_name)

    def _dispatch_auto_launch(self) -> tuple[bool, str]:
        if self.auto_launch_command != "":
            completed = subprocess.run(
                ["/bin/zsh", "-lc", self.auto_launch_command],
                capture_output=True,
                text=True,
                timeout=20.0,
                check=False,
            )
        else:
            completed = subprocess.run(
                ["/usr/bin/open", "-a", self.app_name],
                capture_output=True,
                text=True,
                timeout=20.0,
                check=False,
            )
        if completed.returncode != 0:
            return (False, _subprocess_error_detail(completed))
        return (True, "")

    def _menu_transition_allowed(self, from_state: str, to_state: str) -> bool:
        from_token = str(from_state).strip().lower()
        to_token = str(to_state).strip().lower()
        allowed = MENU_FSM_TRANSITIONS.get(from_token)
        if allowed is None:
            return to_token in MENU_FSM_TRANSITIONS["unknown"]
        return to_token in allowed

    def _apply_menu_fsm_state(
        self,
        *,
        observed_state: str,
        observed_reason: str,
        now_mono: float,
    ) -> tuple[str, str]:
        current = str(getattr(self, "_fsm_state", "unknown") or "unknown").strip().lower()
        if current not in MENU_FSM_KNOWN_STATES:
            current = "unknown"
            self._fsm_state = "unknown"

        observed = str(observed_state).strip().lower()
        if observed not in MENU_FSM_KNOWN_STATES:
            observed = "unknown"

        last_observed_state = str(getattr(self, "_fsm_last_observed_state", "")).strip().lower()
        last_observed_mono = float(getattr(self, "_fsm_last_observed_mono", 0.0))
        self._fsm_last_observed_state = observed
        self._fsm_last_observed_mono = now_mono

        if observed == current:
            return (current, f"{observed_reason}|fsm_stable")

        if self._menu_transition_allowed(current, observed):
            prev = current
            self._fsm_prev_state = prev
            self._fsm_state = observed
            self._fsm_last_transition_reason = f"{prev}->{observed}:{observed_reason}"
            self._fsm_last_transition_at = utc_now_iso()
            return (observed, f"fsm_transition:{self._fsm_last_transition_reason}")

        # Require a repeated observation before allowing unexpected transitions.
        confirm_window = max(0.0, float(getattr(self, "fsm_transition_confirm_seconds", 0.0)))
        observed_repeated = (
            last_observed_state == observed
            and last_observed_mono > 0.0
            and (now_mono - last_observed_mono) <= max(2.0, confirm_window * 8.0)
        )
        if not observed_repeated:
            self._fsm_blocked_transitions = int(getattr(self, "_fsm_blocked_transitions", 0)) + 1
            return ("unknown", f"fsm_blocked:{current}->{observed}:{observed_reason}")

        prev = current
        self._fsm_prev_state = prev
        self._fsm_state = observed
        self._fsm_last_transition_reason = f"{prev}->{observed}:fsm_confirmed_unexpected:{observed_reason}"
        self._fsm_last_transition_at = utc_now_iso()
        return (observed, f"fsm_transition:{self._fsm_last_transition_reason}")

    def _save_data_metadata(self) -> tuple[float | None, float | None]:
        path = self.save_data_path
        if path is None or not path.exists():
            return (None, None)
        stat_row = path.stat()
        age_s = max(0.0, time.time() - stat_row.st_mtime)
        return (age_s, float(stat_row.st_mtime))

    def _dispatch_sequence(self, sequence: list[str]) -> None:
        app = _escape_osascript(self.app_name)
        lines = [
            f'tell application "{app}" to activate',
            "delay 0.25",
            'tell application "System Events"',
        ]
        for token in sequence:
            lines.append(f"  {_token_to_osascript(token)}")
            lines.append(f"  delay {self.key_delay_seconds:.2f}")
        lines.append("end tell")

        cmd = ["/usr/bin/osascript"]
        for line in lines:
            cmd.extend(["-e", line])

        timeout_s = max(5.0, (len(sequence) * (self.key_delay_seconds + 0.2)) + 2.0)
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
        if completed.returncode != 0:
            stderr = str(completed.stderr).strip()
            stdout = str(completed.stdout).strip()
            detail = stderr or stdout or f"osascript_exit_{completed.returncode}"
            raise RuntimeError(detail)

    def _dispatch_key_tap(self, token: str) -> None:
        app = _escape_osascript(self.app_name)
        lines = [
            f'tell application "{app}" to activate',
            "delay 0.08",
            'tell application "System Events"',
            f"  {_token_to_osascript(token)}",
            "end tell",
        ]
        cmd = ["/usr/bin/osascript"]
        for line in lines:
            cmd.extend(["-e", line])
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0, check=False)
        if completed.returncode != 0:
            stderr = str(completed.stderr).strip()
            stdout = str(completed.stdout).strip()
            detail = stderr or stdout or f"osascript_exit_{completed.returncode}"
            raise RuntimeError(detail)

    def _dispatch_movement_hold(self, token: str, hold_seconds: float) -> None:
        key_code = _token_to_key_code_number(token)
        app = _escape_osascript(self.app_name)
        hold_s = max(0.05, float(hold_seconds))
        lines = [
            f'tell application "{app}" to activate',
            "delay 0.05",
            'tell application "System Events"',
            f"  key down (key code {key_code})",
            f"  delay {hold_s:.2f}",
            f"  key up (key code {key_code})",
            "end tell",
        ]
        cmd = ["/usr/bin/osascript"]
        for line in lines:
            cmd.extend(["-e", line])
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=max(4.0, hold_s + 3.0), check=False)
        if completed.returncode != 0:
            stderr = str(completed.stderr).strip()
            stdout = str(completed.stdout).strip()
            detail = stderr or stdout or f"osascript_exit_{completed.returncode}"
            raise RuntimeError(detail)

    def _next_gameplay_direction(self) -> str:
        if not self.gameplay_sequence:
            return "left"
        token = self.gameplay_sequence[self._gameplay_direction_index % len(self.gameplay_sequence)]
        self._gameplay_direction_index = (self._gameplay_direction_index + 1) % len(self.gameplay_sequence)
        return token

    def _arm_state(self) -> tuple[bool, str, dict[str, Any]]:
        payload = _read_json(self.arm_file) if self.arm_file.exists() else {}
        ok, reason = _evaluate_arm_payload(
            require_arm_file=self.require_arm_file,
            payload=payload,
        )
        return (ok, reason, payload)

    def _window_capture_region(self) -> tuple[int, int, int, int] | None:
        script = (
            'tell application "System Events" to tell process "'
            + _escape_osascript(self.app_name)
            + '" to get {position, size} of window 1'
        )
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if completed.returncode != 0:
            return None
        raw = str(completed.stdout).strip()
        parts = [token.strip() for token in raw.split(",")]
        if len(parts) != 4:
            return None
        try:
            x = int(float(parts[0]))
            y = int(float(parts[1]))
            w = int(float(parts[2]))
            h = int(float(parts[3]))
        except Exception:  # noqa: BLE001
            return None
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    def _capture_screenshot(self) -> Path:
        with tempfile.NamedTemporaryFile(prefix="vsbot_menu_", suffix=".png", delete=False) as fh:
            image_path = Path(fh.name)
        region = self._window_capture_region()
        capture_errors: list[str] = []
        if region is not None:
            x, y, w, h = region
            self._menu_capture_mode = "window_region"
            region_completed = subprocess.run(
                ["/usr/sbin/screencapture", "-x", "-R", f"{x},{y},{w},{h}", str(image_path)],
                capture_output=True,
                text=True,
                timeout=4.0,
                check=False,
            )
            if region_completed.returncode == 0:
                return image_path

            region_error = _subprocess_error_detail(region_completed)
            capture_errors.append(f"window_region:{region_error}")
            if not _is_region_capture_retryable_error(region_error):
                self._menu_capture_mode = "capture_error"
                image_path.unlink(missing_ok=True)
                raise RuntimeError(region_error)

            self._menu_capture_mode = "fullscreen_retry_after_region_error"
            image_path.unlink(missing_ok=True)
        else:
            self._menu_capture_mode = "fullscreen_fallback"

        fullscreen_completed = subprocess.run(
            ["/usr/sbin/screencapture", "-x", str(image_path)],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
        if fullscreen_completed.returncode != 0:
            capture_errors.append(f"fullscreen:{_subprocess_error_detail(fullscreen_completed)}")
            self._menu_capture_mode = "capture_error"
            image_path.unlink(missing_ok=True)
            raise RuntimeError("; ".join(capture_errors))
        return image_path

    def _ocr_text_from_image(self, image_path: Path) -> str:
        if not str(self.tesseract_cmd).strip() or not Path(self.tesseract_cmd).exists():
            raise RuntimeError("tesseract_not_found")
        completed = subprocess.run(
            [self.tesseract_cmd, str(image_path), "stdout", "--oem", "1", "--psm", "6"],
            capture_output=True,
            text=True,
            timeout=6.0,
            check=False,
        )
        if completed.returncode != 0:
            stderr = str(completed.stderr).strip()
            stdout = str(completed.stdout).strip()
            detail = stderr or stdout or f"tesseract_exit_{completed.returncode}"
            raise RuntimeError(detail)
        return str(completed.stdout)

    def _ocr_lines_from_image(self, image_path: Path) -> tuple[list[tuple[int, str]], int]:
        if not str(self.tesseract_cmd).strip() or not Path(self.tesseract_cmd).exists():
            return ([], 0)
        completed = subprocess.run(
            [self.tesseract_cmd, str(image_path), "stdout", "--oem", "1", "--psm", "6", "tsv"],
            capture_output=True,
            text=True,
            timeout=6.0,
            check=False,
        )
        if completed.returncode != 0:
            return ([], 0)
        rows = str(completed.stdout).splitlines()
        if len(rows) < 2:
            return ([], 0)
        header = rows[0].split("\t")
        index = {name: idx for idx, name in enumerate(header)}
        required = {"level", "text", "top", "conf", "line_num", "par_num", "block_num", "page_num", "height"}
        if not required.issubset(set(index)):
            return ([], 0)

        page_height = 0
        grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for row in rows[1:]:
            parts = row.split("\t")
            if len(parts) < len(header):
                parts.extend([""] * (len(header) - len(parts)))
            try:
                level = int(parts[index["level"]] or "0")
            except Exception:  # noqa: BLE001
                continue

            if level == 1:
                try:
                    page_height = max(page_height, int(parts[index["height"]] or "0"))
                except Exception:  # noqa: BLE001
                    pass
                continue

            if level != 5:
                continue

            text = str(parts[index["text"]]).strip()
            if not text:
                continue
            try:
                conf = float(parts[index["conf"]] or "-1")
            except Exception:  # noqa: BLE001
                conf = -1.0
            if conf < 25.0:
                continue
            try:
                top = int(parts[index["top"]] or "0")
            except Exception:  # noqa: BLE001
                top = 0

            key = (
                str(parts[index["page_num"]]),
                str(parts[index["block_num"]]),
                str(parts[index["par_num"]]),
                str(parts[index["line_num"]]),
            )
            node = grouped.setdefault(key, {"top": top, "words": []})
            node["top"] = min(int(node["top"]), top)
            node["words"].append(text)

        lines: list[tuple[int, str]] = []
        for node in grouped.values():
            text = " ".join(str(word).strip() for word in node.get("words", []) if str(word).strip())
            if text:
                lines.append((int(node.get("top", 0)), text))
        lines.sort(key=lambda item: item[0])
        return (lines, page_height)

    def _classify_menu_state(self, ocr_text: str) -> tuple[str, str]:
        normalized = _normalize_ocr_match_text(ocr_text)
        if not normalized:
            return ("unknown", "no_ocr_text")
        if "press to start" in normalized:
            return ("title_screen", "matched_press_to_start")
        if "game over" in normalized:
            return ("game_over", "matched_game_over")
        if "revive" in normalized and "quit" in normalized:
            return ("game_over", "matched_revive_quit")
        if "game over" not in normalized and "quit" in normalized and "revive" in normalized:
            return ("game_over", "matched_quit_revive")
        if "level up" in normalized or ("reroll" in normalized and "skip" in normalized):
            return ("level_up", "matched_level_up")
        if "stage select" in normalized or "select stage" in normalized or "stage selection" in normalized:
            return ("stage_select", "matched_stage_select")
        if "character" in normalized and ("select" in normalized or "random" in normalized):
            return ("character_select", "matched_character_select")
        if "resume" in normalized and ("options" in normalized or "quit" in normalized):
            return ("pause_menu", "matched_pause_menu")
        if (
            "results" in normalized
            or (
                "survived" in normalized
                and (
                    "enemies defeated" in normalized
                    or "gold earned" in normalized
                    or "level reached" in normalized
                )
            )
        ):
            return ("run_results", "matched_run_results")
        if "start" in normalized and "options" in normalized and ("quit" in normalized or "credits" in normalized):
            return ("main_menu", "matched_main_menu")
        if "power up" in normalized or ("power" in normalized and "collection" in normalized):
            return ("main_menu", "matched_main_menu_power_up")
        if "collection" in normalized and ("unlocks" in normalized or "bestiary" in normalized):
            return ("main_menu", "matched_main_menu_collection")
        if "vampire survivors" in normalized and ("power" in normalized or "start" in normalized):
            return ("main_menu", "matched_main_menu_logo")
        if re.search(r"\b\d{1,2}:\d{2}\b", normalized):
            blocked = (
                "press to start",
                "level up",
                "game over",
                "results",
                "character",
                "stage",
                "resume",
                "options",
                "loading",
            )
            if not any(token in normalized for token in blocked):
                return ("in_run", "matched_hud_timer")
        if ("gold" in normalized and "level" in normalized) or ("minutes" in normalized and "kills" in normalized):
            return ("in_run", "matched_hud_hint")
        return ("unknown", "no_menu_match")

    def _score_upgrade_line(self, line_text: str) -> float:
        text = " ".join(str(line_text).lower().split())
        if not text:
            return 0.0
        score = 0.0
        for token, token_score in UPGRADE_SCORE_HINTS.items():
            if token in text:
                score = max(score, float(token_score))
        return score

    def _choose_upgrade_index_from_lines(self, lines: list[tuple[int, str]], page_height: int) -> tuple[int, str]:
        if not lines:
            return (0, "fallback_first_no_lines")

        excluded_tokens = {
            "level up",
            "reroll",
            "skip",
            "banish",
            "seal",
            "press to start",
            "game over",
            "resume",
            "options",
            "quit",
            "start",
            "character",
            "stage",
        }

        upper = int(page_height * 0.95) if page_height > 0 else 10_000
        candidates: list[tuple[int, float, str]] = []
        for top, text in lines:
            compact = " ".join(text.lower().split())
            if not compact:
                continue
            if any(token in compact for token in excluded_tokens):
                continue
            if top < 10 or top > upper:
                continue
            score = self._score_upgrade_line(compact)
            if score <= 0.0:
                continue
            candidates.append((top, score, compact))

        if not candidates:
            return (0, "fallback_first_no_score_match")

        candidates.sort(key=lambda row: row[0])
        best = max(candidates, key=lambda row: row[1])
        index = 0
        for idx, row in enumerate(candidates):
            if row == best:
                index = idx
                break
        index = max(0, min(5, index))
        return (index, f"scored_choice:{best[2]}")

    def _refresh_menu_state(self, *, now_mono: float, app_running: bool) -> None:
        if not self.menu_detection_enabled:
            self._menu_state = str(getattr(self, "_fsm_state", "unknown") or "unknown")
            self._menu_state_reason = "menu_detection_disabled"
            self._menu_ocr_ok = False
            self._menu_ocr_error = ""
            self._menu_text_excerpt = ""
            self._menu_capture_mode = "disabled"
            self._menu_upgrade_choice_index = 0
            self._menu_upgrade_choice_reason = "menu_detection_disabled"
            return

        if not app_running:
            state, reason = self._apply_menu_fsm_state(
                observed_state="game_not_running",
                observed_reason="game_not_running",
                now_mono=now_mono,
            )
            self._menu_state = state
            self._menu_state_reason = reason
            self._menu_ocr_ok = False
            self._menu_ocr_error = ""
            self._menu_text_excerpt = ""
            self._menu_capture_mode = "game_not_running"
            self._menu_upgrade_choice_index = 0
            self._menu_upgrade_choice_reason = "game_not_running"
            return

        if self._last_menu_scan_mono > 0.0 and (now_mono - self._last_menu_scan_mono) < self.menu_scan_interval_seconds:
            return

        self._last_menu_scan_mono = now_mono
        self._menu_last_scan_at = utc_now_iso()
        image_path: Path | None = None
        try:
            image_path = self._capture_screenshot()
            text = self._ocr_text_from_image(image_path)
            state, reason = self._classify_menu_state(text)
            if (
                state == "unknown"
                and reason in {"no_menu_match", "no_ocr_text"}
                and self._last_known_menu_state in MENU_ACTIONABLE_STATES
                and self._last_known_menu_state_mono > 0.0
                and (now_mono - self._last_known_menu_state_mono) <= self.menu_state_sticky_seconds
            ):
                state = self._last_known_menu_state
                reason = f"sticky_prev_menu:{state}"
            effective_state, effective_reason = self._apply_menu_fsm_state(
                observed_state=state,
                observed_reason=reason,
                now_mono=now_mono,
            )
            self._menu_state = effective_state
            self._menu_state_reason = effective_reason
            if effective_state in MENU_ACTIONABLE_STATES:
                self._last_known_menu_state = effective_state
                self._last_known_menu_state_mono = now_mono
            self._menu_ocr_ok = True
            self._menu_ocr_error = ""
            self._menu_text_excerpt = " ".join(text.split())[:220]

            if effective_state == "level_up":
                lines, page_height = self._ocr_lines_from_image(image_path)
                upgrade_index, upgrade_reason = self._choose_upgrade_index_from_lines(lines, page_height)
                self._menu_upgrade_choice_index = upgrade_index
                self._menu_upgrade_choice_reason = upgrade_reason
            else:
                self._menu_upgrade_choice_index = 0
                self._menu_upgrade_choice_reason = "not_level_up"
        except Exception as exc:  # noqa: BLE001
            state, reason = self._apply_menu_fsm_state(
                observed_state="unknown",
                observed_reason="ocr_error",
                now_mono=now_mono,
            )
            self._menu_state = state
            self._menu_state_reason = reason
            self._menu_ocr_ok = False
            self._menu_ocr_error = str(exc)
            self._menu_text_excerpt = ""
            self._menu_upgrade_choice_index = 0
            self._menu_upgrade_choice_reason = "ocr_error"
        finally:
            if image_path is not None:
                image_path.unlink(missing_ok=True)

    def _dispatch_menu_action(self, *, menu_state: str, now_mono: float) -> tuple[str, str, bool]:
        if menu_state not in MENU_ACTIONABLE_STATES:
            return ("none", "", False)
        if self._last_menu_action_mono > 0.0 and (now_mono - self._last_menu_action_mono) < self.menu_action_interval_seconds:
            return ("none", "", False)
        last_menu_action_state = str(getattr(self, "_last_menu_action_state", ""))
        last_menu_action_state_mono = float(getattr(self, "_last_menu_action_state_mono", 0.0))
        menu_state_retry_interval_seconds = max(0.0, float(getattr(self, "menu_state_retry_interval_seconds", 0.0)))
        retry_bypass_states = {"title_screen", "main_menu", "character_select", "stage_select", "game_over", "run_results"}
        if (
            menu_state_retry_interval_seconds > 0.0
            and menu_state not in retry_bypass_states
            and last_menu_action_state == menu_state
            and last_menu_action_state_mono > 0.0
            and (now_mono - last_menu_action_state_mono) < menu_state_retry_interval_seconds
        ):
            return ("none", "", False)

        action = "none"
        if self.dry_run:
            if menu_state == "level_up":
                action = f"menu_level_up_select_{self._menu_upgrade_choice_index}_dry_run"
            elif menu_state == "main_menu":
                action = "menu_main_menu_start_dry_run"
            elif menu_state == "character_select":
                action = f"menu_character_select_{self._target_character_key}_{self._target_character_index}_dry_run"
            elif menu_state == "stage_select":
                action = f"menu_stage_select_{self._target_stage_key}_{self._target_stage_index}_dry_run"
            elif menu_state == "game_over":
                action = "menu_game_over_quit_confirm_dry_run"
            else:
                action = f"menu_{menu_state}_confirm_dry_run"
            self._last_menu_action_mono = now_mono
            self._last_menu_action_state = menu_state
            self._last_menu_action_state_mono = now_mono
            return (action, "", True)

        try:
            if menu_state == "level_up":
                step_count = max(0, int(self._menu_upgrade_choice_index))
                for _ in range(step_count):
                    self._dispatch_key_tap("down")
                    time.sleep(0.05)
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = f"menu_level_up_select_{step_count}"
            elif menu_state == "main_menu":
                # Avoid directional churn on wrapped menus; confirm current default item.
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = "menu_main_menu_start"
            elif menu_state == "character_select":
                step_count = max(0, min(12, int(self._target_character_index)))
                for _ in range(step_count):
                    self._dispatch_key_tap("right")
                    time.sleep(0.03)
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = f"menu_character_select_{self._target_character_key}_{step_count}"
            elif menu_state == "stage_select":
                # Deterministic route: reset to top stage, then move down to target.
                for _ in range(10):
                    self._dispatch_key_tap("up")
                    time.sleep(0.03)
                step_count = max(0, min(12, int(self._target_stage_index)))
                for _ in range(step_count):
                    self._dispatch_key_tap("down")
                    time.sleep(0.03)
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = f"menu_stage_select_{self._target_stage_key}_{step_count}"
            elif menu_state == "game_over":
                # Prefer "Quit" path over revive loops.
                self._dispatch_key_tap("down")
                time.sleep(0.05)
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = "menu_game_over_quit_confirm"
            else:
                self._dispatch_key_tap(self.gameplay_confirm_key)
                action = f"menu_{menu_state}_confirm"
            self._last_menu_action_mono = now_mono
            self._last_menu_action_state = menu_state
            self._last_menu_action_state_mono = now_mono
            return (action, "", True)
        except Exception as exc:  # noqa: BLE001
            return ("menu_action_error", str(exc), False)

    def _dispatch_unknown_menu_confirm(self, *, now_mono: float) -> tuple[str, str, bool]:
        if self._last_menu_action_mono > 0.0 and (
            now_mono - self._last_menu_action_mono
        ) < self.unknown_menu_confirm_interval_seconds:
            return ("none", "", False)

        if self.dry_run:
            self._last_menu_action_mono = now_mono
            return ("menu_unknown_confirm_dry_run", "", True)

        try:
            self._dispatch_key_tap(self.gameplay_confirm_key)
            self._last_menu_action_mono = now_mono
            return ("menu_unknown_confirm", "", True)
        except Exception as exc:  # noqa: BLE001
            return ("menu_unknown_confirm_error", str(exc), False)

    def _memory_signal_context(self) -> dict[str, Any]:
        payload = (
            _read_json(self.memory_signal_path)
            if self.memory_signal_path is not None and self.memory_signal_path.exists()
            else {}
        )
        unlocked_characters_raw = payload.get("unlocked_characters", [])
        unlocked_stages_raw = payload.get("unlocked_stages", [])
        unlocked_characters = (
            [str(row) for row in unlocked_characters_raw if str(row).strip()]
            if isinstance(unlocked_characters_raw, list)
            else []
        )
        unlocked_stages = (
            [str(row) for row in unlocked_stages_raw if str(row).strip()]
            if isinstance(unlocked_stages_raw, list)
            else []
        )
        return {
            "path": (str(self.memory_signal_path) if self.memory_signal_path is not None else ""),
            "unlocked_characters": unlocked_characters,
            "unlocked_characters_count": int(payload.get("unlocked_characters_count", len(unlocked_characters)) or 0),
            "unlocked_stages": unlocked_stages,
            "unlocked_stages_count": int(payload.get("unlocked_stages_count", len(unlocked_stages)) or 0),
        }

    def _select_stage_target(self, *, objective_context: dict[str, Any], memory_context: dict[str, Any]) -> tuple[str, int, str]:
        unlocked_tokens = _normalize_entity_set([str(row) for row in memory_context.get("unlocked_stages", [])])
        objective_category = str(objective_context.get("next_objective_category", "")).strip().lower()
        objective_signal_key = _signal_key_from_unlock_signal(str(objective_context.get("next_objective_signal", "")))
        stage_obj_active = objective_category == "stage" or objective_signal_key == "unlocked_stages_count"

        for idx, entry in enumerate(STAGE_ROUTE):
            if not _entry_matches_aliases(entry, unlocked_tokens):
                key = str(entry["key"])
                if stage_obj_active:
                    # When the target stage is still locked, route to the nearest unlocked prerequisite stage.
                    for back in range(idx - 1, -1, -1):
                        prev = STAGE_ROUTE[back]
                        if _entry_matches_aliases(prev, unlocked_tokens):
                            prev_key = str(prev["key"])
                            prev_idx = int(prev["menu_index"])
                            return (
                                prev_key,
                                prev_idx,
                                f"objective_stage_prereq_for_missing:{key}:{prev_key}",
                            )
                    entry_idx = int(entry["menu_index"])
                    return (key, entry_idx, f"objective_stage_missing:{key}")
                # Non-stage objectives still benefit from explicit stage route progression.
                entry_idx = int(entry["menu_index"])
                return (key, entry_idx, f"fallback_stage_missing:{key}")

        # If all route stages appear unlocked, use library for farm-heavy objectives when available.
        library_entry = next((row for row in STAGE_ROUTE if str(row["key"]) == "inlaid_library"), None)
        if library_entry is not None:
            if _entry_matches_aliases(library_entry, unlocked_tokens):
                return (
                    "inlaid_library",
                    int(library_entry["menu_index"]),
                    "fallback_stage_library_farm",
                )
        return ("mad_forest", 0, "fallback_stage_default_forest")

    def _select_character_target(
        self,
        *,
        objective_context: dict[str, Any],
        memory_context: dict[str, Any],
    ) -> tuple[str, int, str]:
        unlocked_tokens = _normalize_entity_set([str(row) for row in memory_context.get("unlocked_characters", [])])
        objective_category = str(objective_context.get("next_objective_category", "")).strip().lower()
        objective_signal_key = _signal_key_from_unlock_signal(str(objective_context.get("next_objective_signal", "")))
        character_obj_active = objective_category == "character" or objective_signal_key == "unlocked_characters_count"

        if character_obj_active:
            for preferred in ("imelda", "pasqualina", "gennaro", "antonio"):
                entry = next((row for row in CHARACTER_ROUTE if str(row["key"]) == preferred), None)
                if entry is None:
                    continue
                if _entry_matches_aliases(entry, unlocked_tokens):
                    return (preferred, int(entry["menu_index"]), f"objective_character_preferred:{preferred}")

        # Fallback: first unlocked known route entry, else default Antonio.
        for entry in CHARACTER_ROUTE:
            if _entry_matches_aliases(entry, unlocked_tokens):
                key = str(entry["key"])
                return (key, int(entry["menu_index"]), f"fallback_character_unlocked:{key}")
        return ("antonio", 0, "fallback_character_default_antonio")

    def _refresh_menu_targets(self, *, objective_context: dict[str, Any], memory_context: dict[str, Any]) -> None:
        stage_key, stage_index, stage_reason = self._select_stage_target(
            objective_context=objective_context,
            memory_context=memory_context,
        )
        character_key, character_index, character_reason = self._select_character_target(
            objective_context=objective_context,
            memory_context=memory_context,
        )
        self._target_stage_key = stage_key
        self._target_stage_index = max(0, int(stage_index))
        self._target_stage_reason = stage_reason
        self._target_character_key = character_key
        self._target_character_index = max(0, int(character_index))
        self._target_character_reason = character_reason

    def _objective_context(self) -> dict[str, Any]:
        health = _read_json(self.health_path)
        planner = health.get("objective_planner")
        queue = []
        if isinstance(planner, dict):
            candidate = planner.get("queue")
            if isinstance(candidate, list):
                queue = [row for row in candidate if isinstance(row, dict)]
        next_objective = queue[0] if queue else None
        return {
            "generation": health.get("generation"),
            "state": health.get("state"),
            "next_objective_id": (next_objective or {}).get("id"),
            "next_objective_signal": (next_objective or {}).get("unlock_signal"),
            "next_objective_category": (next_objective or {}).get("category"),
            "next_objective_metric": (next_objective or {}).get("metric"),
            "next_objective_target": (next_objective or {}).get("target"),
            "next_objective_current": (next_objective or {}).get("current"),
            "next_objective_priority": (next_objective or {}).get("priority"),
        }

    def _unlock_progress_signature(self) -> tuple[str | None, bool]:
        summary = _read_json(self.summary_path)
        unlock_progress = summary.get("unlock_progress")
        if not isinstance(unlock_progress, dict):
            return (None, False)

        keys = [
            "collection_entries",
            "collection_ratio",
            "bestiary_entries",
            "bestiary_ratio",
            "steam_achievements",
            "steam_achievements_ratio",
            "unlocked_characters_count",
            "unlocked_arcanas_count",
            "unlocked_weapons_count",
            "unlocked_passives_count",
            "unlocked_stages_count",
        ]
        parts: list[str] = []
        has_metric_value = False
        for key in keys:
            value = unlock_progress.get(key)
            if isinstance(value, float):
                parts.append(f"{key}:{value:.8f}")
            else:
                parts.append(f"{key}:{value}")
            if value is not None:
                has_metric_value = True

        unlock_trend = summary.get("unlock_trend")
        triad_progress_any_gain = False
        if isinstance(unlock_trend, dict):
            triad_progress_any_gain = bool(unlock_trend.get("triad_progress_any_gain", False))

        if not has_metric_value:
            return (None, triad_progress_any_gain)
        return ("|".join(parts), triad_progress_any_gain)

    def _select_sequence(self, *, reason: str, stuck_elapsed_seconds: float) -> tuple[list[str], str]:
        if reason != "stuck_watchdog":
            return (list(self.sequence), "default")

        base = max(30.0, float(self.stuck_window_seconds))
        if stuck_elapsed_seconds >= (base * 6.0):
            # Deep recovery: back out menus and re-confirm start path.
            return (["escape", "escape", "return", "return", "down", "return", "return", "return"], "stuck_deep")
        if stuck_elapsed_seconds >= (base * 2.0):
            # Medium recovery: explicit menu backout + confirm.
            return (["escape", "return", "return", "return", "return"], "stuck_medium")
        # Initial recovery: confirm through likely start prompt.
        return (list(self.sequence), "stuck_light")

    def tick(self, *, force: bool = False) -> GameInputResult:
        now_mono = time.monotonic()
        pids = self._find_game_pids()
        app_running = bool(pids)
        game_focused, focus_state_reason, frontmost_pid, frontmost_name = self._game_focus_state(
            app_running=app_running,
            pids=pids,
        )
        focus_pause_active = bool(self.pause_when_unfocused and app_running and (not game_focused))
        safety_armed, safety_reason, safety_payload = self._arm_state()
        safety_menu_only = bool(safety_payload.get("menu_only", False)) if isinstance(safety_payload, dict) else False

        auto_launch_action = "none"
        auto_launch_error = ""
        auto_launch_due = bool(
            self.enabled
            and safety_armed
            and self.auto_launch_when_not_running
            and (not app_running)
            and (
                self._last_auto_launch_mono <= 0.0
                or (now_mono - self._last_auto_launch_mono) >= self.auto_launch_cooldown_seconds
            )
        )
        if auto_launch_due:
            self._last_auto_launch_mono = now_mono
            self._last_auto_launch_at = utc_now_iso()
            self._auto_launch_attempts += 1
            if self.dry_run:
                auto_launch_action = "launch_dry_run"
                self._last_auto_launch_error = ""
            else:
                launched, detail = self._dispatch_auto_launch()
                if launched:
                    auto_launch_action = "launch_sent"
                    self._last_auto_launch_error = ""
                else:
                    auto_launch_action = "launch_error"
                    auto_launch_error = detail
                    self._last_auto_launch_error = detail
            pids = self._find_game_pids()
            app_running = bool(pids)
            game_focused, focus_state_reason, frontmost_pid, frontmost_name = self._game_focus_state(
                app_running=app_running,
                pids=pids,
            )
            focus_pause_active = bool(self.pause_when_unfocused and app_running and (not game_focused))

        self._refresh_menu_state(now_mono=now_mono, app_running=app_running)
        objective_context = self._objective_context()
        objective_id = str(objective_context.get("next_objective_id", "") or "")
        if objective_id != self._last_objective_id:
            self._last_objective_id = objective_id
            self._last_objective_change_mono = now_mono
            self._last_objective_change_at = utc_now_iso()
        elif self._last_objective_change_mono <= 0.0:
            self._last_objective_change_mono = now_mono
            self._last_objective_change_at = utc_now_iso()
        objective_staleness_seconds = (
            max(0.0, now_mono - self._last_objective_change_mono) if self._last_objective_change_mono > 0.0 else 0.0
        )
        objective_stale = objective_staleness_seconds >= self.objective_stale_threshold_seconds
        memory_context = self._memory_signal_context()
        self._refresh_menu_targets(
            objective_context=objective_context,
            memory_context=memory_context,
        )
        next_objective_candidate_source = (
            "objective_planner_queue"
            if objective_id != ""
            else f"route_fallback:{self._target_stage_reason}"
        )
        if self._menu_state == "in_run":
            self._last_in_run_seen_mono = now_mono
            self._last_in_run_seen_at = utc_now_iso()
        elif self._menu_state in MENU_ACTIONABLE_STATES:
            self._last_in_run_seen_mono = 0.0
            self._last_in_run_seen_at = ""
        in_run_recent = bool(
            self._last_in_run_seen_mono > 0.0
            and (now_mono - self._last_in_run_seen_mono) <= self.unknown_in_run_grace_seconds
        )

        save_age, save_mtime = self._save_data_metadata()
        save_mtime_changed = False
        if save_mtime is not None:
            if self._last_seen_save_mtime <= 0.0:
                self._last_seen_save_mtime = float(save_mtime)
                self._last_save_change_mono = now_mono
                self._last_save_change_at = utc_now_iso()
            elif float(save_mtime) > (self._last_seen_save_mtime + 1e-6):
                save_mtime_changed = True
                self._last_seen_save_mtime = float(save_mtime)
                self._last_save_change_mono = now_mono
                self._last_save_change_at = utc_now_iso()
                # New save write means the game is making progress again.
                self._nudges_sent = 0
                self._last_stuck_nudge_mono = 0.0
            else:
                self._last_seen_save_mtime = max(self._last_seen_save_mtime, float(save_mtime))
        progress_signature, triad_progress_any_gain = self._unlock_progress_signature()

        progress_signature_changed = False
        if progress_signature is not None:
            if progress_signature != self._last_progress_signature:
                self._last_progress_signature = progress_signature
                self._last_progress_change_mono = now_mono
                self._last_progress_change_at = utc_now_iso()
                progress_signature_changed = True
            elif self._last_progress_change_mono <= 0.0:
                self._last_progress_change_mono = now_mono
                self._last_progress_change_at = utc_now_iso()

        stuck_elapsed_seconds = (
            max(0.0, now_mono - self._last_progress_change_mono) if self._last_progress_change_mono > 0.0 else 0.0
        )
        stuck_recovery_remaining_seconds = (
            max(0.0, self.stuck_recovery_interval_seconds - (now_mono - self._last_stuck_nudge_mono))
            if self._last_stuck_nudge_mono > 0.0
            else 0.0
        )
        save_stall_elapsed_seconds = (
            max(0.0, now_mono - self._last_save_change_mono) if self._last_save_change_mono > 0.0 else 0.0
        )
        stuck_watchdog_active = False
        stuck_watchdog_reason = "inactive"
        if not self.stuck_watchdog_enabled:
            stuck_watchdog_reason = "watchdog_disabled"
        elif not app_running:
            stuck_watchdog_reason = "game_not_running"
        elif save_age is None:
            stuck_watchdog_reason = "save_data_age_unknown"
        elif save_age < self.stuck_min_save_data_age_seconds:
            stuck_watchdog_reason = "save_data_not_old_enough"
        elif self._last_save_change_mono <= 0.0:
            stuck_watchdog_reason = "save_baseline_pending"
        elif save_stall_elapsed_seconds < self.stuck_window_seconds:
            stuck_watchdog_reason = "save_stall_window_not_elapsed"
        elif stuck_recovery_remaining_seconds > 0.0:
            stuck_watchdog_reason = "stuck_recovery_cooldown_active"
        else:
            stuck_watchdog_active = True
            stuck_watchdog_reason = "stuck_progress_detected"

        if not self.enabled:
            should_nudge, reason, cooldown_remaining = (False, "disabled_by_config", 0.0)
        elif not safety_armed:
            should_nudge, reason, cooldown_remaining = (False, f"safety_switch:{safety_reason}", 0.0)
        elif focus_pause_active:
            should_nudge, reason, cooldown_remaining = (False, f"paused_unfocused:{focus_state_reason}", 0.0)
        else:
            should_nudge, reason, cooldown_remaining = evaluate_nudge(
                enabled=True,
                app_running=app_running,
                save_data_age_seconds=save_age,
                min_save_data_age_seconds=self.min_save_data_age_seconds,
                now_mono=now_mono,
                last_nudge_mono=self._last_nudge_mono,
                nudge_cooldown_seconds=self.nudge_cooldown_seconds,
                nudges_sent=self._nudges_sent,
                max_nudges_per_session=self.max_nudges_per_session,
                force=force,
            )
        if (
            safety_armed
            and (not focus_pause_active)
            and
            stuck_watchdog_active
            and (not should_nudge)
            and reason not in {"disabled_by_config", "game_not_running"}
        ):
            should_nudge = True
            reason = "stuck_watchdog"
            cooldown_remaining = 0.0

        input_paused_reason = ""
        if not self.enabled:
            input_paused_reason = "disabled_by_config"
        elif not safety_armed:
            input_paused_reason = f"safety_switch:{safety_reason}"
        elif focus_pause_active:
            input_paused_reason = f"paused_unfocused:{focus_state_reason}"
        elif not app_running:
            input_paused_reason = "game_not_running"

        menu_action = "none"
        menu_action_error = ""
        menu_action_sent = False
        if self.enabled and safety_armed and (not focus_pause_active) and app_running and self._menu_state in MENU_ACTIONABLE_STATES:
            menu_action, menu_action_error, menu_action_sent = self._dispatch_menu_action(
                menu_state=self._menu_state,
                now_mono=now_mono,
            )
            if menu_action_sent and menu_action_error == "":
                self._last_error = ""
                self._last_error_at = ""

        unknown_excerpt = str(self._menu_text_excerpt).strip()
        unknown_has_menu_keywords = _text_has_menu_keywords(unknown_excerpt)
        unknown_menu_confirm_allowed = bool(
            _should_allow_unknown_menu_confirm(
                menu_state=self._menu_state,
                menu_ocr_ok=self._menu_ocr_ok,
                unknown_has_menu_keywords=unknown_has_menu_keywords,
                menu_ocr_error=self._menu_ocr_error,
                save_age_seconds=save_age,
                in_run_recent=in_run_recent,
                save_stall_elapsed_seconds=save_stall_elapsed_seconds,
            )
        )
        unknown_menu_confirm_allowed = bool(
            self.enabled
            and safety_armed
            and (not focus_pause_active)
            and app_running
            and self.menu_detection_enabled
            and unknown_menu_confirm_allowed
        )
        if unknown_menu_confirm_allowed and (not menu_action_sent):
            menu_action, menu_action_error, menu_action_sent = self._dispatch_unknown_menu_confirm(
                now_mono=now_mono,
            )
            if menu_action_sent and menu_action_error == "":
                self._last_error = ""
                self._last_error_at = ""

        action = "none"
        error = ""
        used_stuck_watchdog_override = reason == "stuck_watchdog"
        selected_sequence, sequence_label = self._select_sequence(
            reason=reason,
            stuck_elapsed_seconds=stuck_elapsed_seconds,
        )
        recovery_tier = 0
        recovery_reason = "none"
        if reason == "stuck_watchdog":
            if sequence_label == "stuck_light":
                recovery_tier = 1
            elif sequence_label == "stuck_medium":
                recovery_tier = 2
            elif sequence_label == "stuck_deep":
                recovery_tier = 3
            recovery_reason = sequence_label
        elif menu_action.startswith("menu_unknown_confirm"):
            recovery_tier = 1
            recovery_reason = "unknown_menu_confirm"
        if should_nudge and not menu_action_sent:
            if used_stuck_watchdog_override:
                self._last_stuck_nudge_mono = now_mono
            if self.dry_run:
                action = "nudge_dry_run"
            else:
                try:
                    self._dispatch_sequence(selected_sequence)
                    action = "nudge_sent"
                except Exception as exc:  # noqa: BLE001
                    action = "nudge_error"
                    error = str(exc)
                    self._last_error = error
                    self._last_error_at = utc_now_iso()
                    # Back off after failed injections to avoid tight retry loops/spam.
                    self._last_nudge_mono = now_mono

            if action in {"nudge_sent", "nudge_dry_run"}:
                self._last_nudge_mono = now_mono
                self._last_nudge_at = utc_now_iso()
                self._nudges_sent += 1
                self._last_error = ""
                self._last_error_at = ""

        gameplay_action = "none"
        gameplay_error = ""
        gameplay_direction = ""
        gameplay_confirm_sent = False
        unknown_run_candidate_reason = "classifier"
        unknown_run_candidate = bool(
            _should_treat_unknown_as_in_run(
                menu_state=self._menu_state,
                menu_ocr_ok=self._menu_ocr_ok,
                unknown_has_menu_keywords=unknown_has_menu_keywords,
                menu_ocr_error=self._menu_ocr_error,
                save_age_seconds=save_age,
                in_run_recent=in_run_recent,
                save_stall_elapsed_seconds=save_stall_elapsed_seconds,
            )
        )
        menu_recently_observed = bool(
            self._last_known_menu_state in MENU_ACTIONABLE_STATES
            and self._last_known_menu_state_mono > 0.0
            and (now_mono - self._last_known_menu_state_mono) <= 20.0
        )
        if (
            self._menu_state == "unknown"
            and (not unknown_has_menu_keywords)
            and (not unknown_run_candidate)
            and (not menu_recently_observed)
        ):
            unknown_run_candidate = True
            unknown_run_candidate_reason = "unknown_no_menu_keywords"
        if (
            self._menu_state == "unknown"
            and (not unknown_has_menu_keywords)
            and (not unknown_run_candidate)
        ):
            gameplay_recent = bool(
                self._last_gameplay_mono > 0.0
                and (now_mono - self._last_gameplay_mono) <= max(30.0, self.unknown_in_run_grace_seconds)
            )
            save_recent_for_gameplay = bool(
                save_age is not None
                and float(save_age) <= max(45.0, self.unknown_in_run_grace_seconds)
            )
            if gameplay_recent and save_recent_for_gameplay and (not menu_recently_observed):
                unknown_run_candidate = True
                unknown_run_candidate_reason = "persist_recent_gameplay"
        gameplay_allowed_state = (
            (not self.menu_detection_enabled)
            or (self._menu_state == "in_run")
            or unknown_run_candidate
        )
        gameplay_due = (
            self.enabled
            and safety_armed
            and (not focus_pause_active)
            and (not safety_menu_only)
            and
            self.gameplay_enabled
            and app_running
            and gameplay_allowed_state
            and (
                self._last_gameplay_mono <= 0.0
                or (now_mono - self._last_gameplay_mono) >= self.gameplay_interval_seconds
            )
        )
        if gameplay_due and action == "none" and not menu_action_sent:
            gameplay_direction = self._next_gameplay_direction()
            if self.dry_run:
                gameplay_action = "pulse_dry_run"
                self._last_gameplay_mono = now_mono
                self._last_gameplay_at = utc_now_iso()
                self._last_gameplay_direction = gameplay_direction
            else:
                try:
                    self._dispatch_movement_hold(gameplay_direction, self.gameplay_hold_seconds)
                    gameplay_action = "pulse_sent"
                    self._last_gameplay_mono = now_mono
                    self._last_gameplay_at = utc_now_iso()
                    self._last_gameplay_direction = gameplay_direction
                    self._gameplay_pulses_sent += 1

                    confirm_due = (
                        self.gameplay_confirm_enabled
                        and (
                            self._last_confirm_mono <= 0.0
                            or (now_mono - self._last_confirm_mono) >= self.gameplay_confirm_interval_seconds
                        )
                    )
                    if confirm_due:
                        self._dispatch_key_tap(self.gameplay_confirm_key)
                        gameplay_confirm_sent = True
                        self._last_confirm_mono = now_mono
                        gameplay_action = "pulse_and_confirm_sent"

                    self._gameplay_last_error = ""
                    self._gameplay_last_error_at = ""
                    self._last_error = ""
                    self._last_error_at = ""
                except Exception as exc:  # noqa: BLE001
                    gameplay_action = "pulse_error"
                    gameplay_error = str(exc)
                    self._gameplay_last_error = gameplay_error
                    self._gameplay_last_error_at = utc_now_iso()
                    self._last_error = f"gameplay:{gameplay_error}"
                    self._last_error_at = self._gameplay_last_error_at

        ok_state = bool(
            error == ""
            and gameplay_error == ""
            and menu_action_error == ""
            and self._last_error == ""
            and self._gameplay_last_error == ""
        )

        payload = {
            "generated_at": utc_now_iso(),
            "enabled": self.enabled,
            "active": True,
            "ok": ok_state,
            "app_name": self.app_name,
            "app_running": app_running,
            "pids": pids,
            "require_arm_file": self.require_arm_file,
            "arm_file": str(self.arm_file),
            "safety_armed": safety_armed,
            "safety_reason": safety_reason,
            "safety_menu_only": safety_menu_only,
            "pause_when_unfocused": self.pause_when_unfocused,
            "game_focused": game_focused,
            "focus_state_reason": focus_state_reason,
            "focus_pause_active": focus_pause_active,
            "input_paused_reason": input_paused_reason,
            "frontmost_app_name": frontmost_name,
            "frontmost_app_pid": frontmost_pid,
            "effective_input_enabled": bool(self.enabled and safety_armed and (not focus_pause_active)),
            "auto_launch_when_not_running": self.auto_launch_when_not_running,
            "auto_launch_cooldown_seconds": self.auto_launch_cooldown_seconds,
            "auto_launch_action": auto_launch_action,
            "auto_launch_due": auto_launch_due,
            "auto_launch_error": auto_launch_error,
            "last_auto_launch_at": self._last_auto_launch_at,
            "last_auto_launch_error": self._last_auto_launch_error,
            "auto_launch_attempts": self._auto_launch_attempts,
            "menu_detection_enabled": self.menu_detection_enabled,
            "menu_scan_interval_seconds": self.menu_scan_interval_seconds,
            "fsm_state": self._fsm_state,
            "fsm_previous_state": self._fsm_prev_state,
            "fsm_last_transition_reason": self._fsm_last_transition_reason,
            "fsm_last_transition_at": self._fsm_last_transition_at,
            "fsm_blocked_transitions": self._fsm_blocked_transitions,
            "menu_state": self._menu_state,
            "menu_state_reason": self._menu_state_reason,
            "in_run_recent": in_run_recent,
            "last_in_run_seen_at": self._last_in_run_seen_at,
            "unknown_in_run_grace_seconds": self.unknown_in_run_grace_seconds,
            "menu_target_stage_key": self._target_stage_key,
            "menu_target_stage_index": self._target_stage_index,
            "menu_target_stage_reason": self._target_stage_reason,
            "menu_target_character_key": self._target_character_key,
            "menu_target_character_index": self._target_character_index,
            "menu_target_character_reason": self._target_character_reason,
            "menu_ocr_ok": self._menu_ocr_ok,
            "menu_ocr_error": self._menu_ocr_error,
            "menu_last_scan_at": self._menu_last_scan_at,
            "menu_capture_mode": self._menu_capture_mode,
            "menu_text_excerpt": self._menu_text_excerpt,
            "menu_unknown_has_menu_keywords": unknown_has_menu_keywords,
            "menu_unknown_confirm_allowed": unknown_menu_confirm_allowed,
            "menu_action": menu_action,
            "menu_action_error": menu_action_error,
            "menu_upgrade_choice_index": self._menu_upgrade_choice_index,
            "menu_upgrade_choice_reason": self._menu_upgrade_choice_reason,
            "gameplay_enabled": self.gameplay_enabled,
            "gameplay_interval_seconds": self.gameplay_interval_seconds,
            "gameplay_hold_seconds": self.gameplay_hold_seconds,
            "gameplay_sequence": list(self.gameplay_sequence),
            "gameplay_allowed_state": gameplay_allowed_state,
            "gameplay_unknown_run_candidate": unknown_run_candidate,
            "gameplay_unknown_run_candidate_reason": unknown_run_candidate_reason,
            "gameplay_action": gameplay_action,
            "gameplay_direction": gameplay_direction,
            "last_gameplay_direction": self._last_gameplay_direction,
            "gameplay_confirm_enabled": self.gameplay_confirm_enabled,
            "gameplay_confirm_interval_seconds": self.gameplay_confirm_interval_seconds,
            "gameplay_confirm_key": self.gameplay_confirm_key,
            "gameplay_confirm_sent": gameplay_confirm_sent,
            "gameplay_pulses_sent": self._gameplay_pulses_sent,
            "last_gameplay_at": self._last_gameplay_at,
            "gameplay_error": gameplay_error,
            "last_gameplay_error": self._gameplay_last_error,
            "last_gameplay_error_at": self._gameplay_last_error_at,
            "save_data_path": (str(self.save_data_path) if self.save_data_path is not None else ""),
            "save_data_age_seconds": save_age,
            "min_save_data_age_seconds": self.min_save_data_age_seconds,
            "nudge_cooldown_seconds": self.nudge_cooldown_seconds,
            "cooldown_remaining_seconds": cooldown_remaining,
            "nudges_sent": self._nudges_sent,
            "max_nudges_per_session": self.max_nudges_per_session,
            "last_nudge_at": self._last_nudge_at,
            "watch_interval_seconds": self.watch_interval_seconds,
            "dry_run": self.dry_run,
            "force": bool(force),
            "sequence": list(self.sequence),
            "sequence_used": selected_sequence,
            "sequence_label": sequence_label,
            "decision_reason": reason,
            "action": action,
            "error": error,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "stuck_watchdog_enabled": self.stuck_watchdog_enabled,
            "stuck_watchdog_active": stuck_watchdog_active,
            "stuck_watchdog_reason": stuck_watchdog_reason,
            "stuck_window_seconds": self.stuck_window_seconds,
            "stuck_min_save_data_age_seconds": self.stuck_min_save_data_age_seconds,
            "stuck_recovery_interval_seconds": self.stuck_recovery_interval_seconds,
            "stuck_recovery_remaining_seconds": stuck_recovery_remaining_seconds,
            "stuck_elapsed_seconds": stuck_elapsed_seconds,
            "recovery_tier": recovery_tier,
            "recovery_reason": recovery_reason,
            "recovery_cooldown_remaining_seconds": stuck_recovery_remaining_seconds,
            "save_stall_elapsed_seconds": save_stall_elapsed_seconds,
            "save_mtime_changed": save_mtime_changed,
            "last_save_change_at": self._last_save_change_at,
            "progress_signature_present": bool(progress_signature is not None),
            "progress_signature_changed": progress_signature_changed,
            "last_progress_change_at": self._last_progress_change_at,
            "triad_progress_any_gain": triad_progress_any_gain,
            "session_started_at": self._session_started_at,
            "objective_stale_threshold_seconds": self.objective_stale_threshold_seconds,
            "objective_staleness_seconds": objective_staleness_seconds,
            "objective_stale": objective_stale,
            "last_objective_id": self._last_objective_id,
            "last_objective_change_at": self._last_objective_change_at,
            "next_objective_candidate_source": next_objective_candidate_source,
            "objective_context": objective_context,
            "memory_context": memory_context,
        }
        _write_json_atomic(self.status_file, payload)
        print(json.dumps(payload, ensure_ascii=True))
        return GameInputResult(ok=bool(payload.get("ok", False)), payload=payload)

    def run_forever(self, *, force: bool = False) -> None:
        wait_s = max(0.2, float(self.watch_interval_seconds))
        while True:
            _ = self.tick(force=force)
            time.sleep(wait_s)


def run_game_input_once(
    cfg: AppConfig,
    *,
    force: bool = False,
    status_output_override: str = "",
    dry_run_override: bool | None = None,
) -> GameInputResult:
    daemon = GameInputDaemon(
        cfg,
        status_output_override=status_output_override,
        dry_run_override=dry_run_override,
    )
    return daemon.tick(force=force)


def run_game_input_daemon(
    cfg: AppConfig,
    *,
    force: bool = False,
    status_output_override: str = "",
    interval_override: float | None = None,
    dry_run_override: bool | None = None,
) -> None:
    daemon = GameInputDaemon(
        cfg,
        status_output_override=status_output_override,
        interval_override=interval_override,
        dry_run_override=dry_run_override,
    )
    daemon.run_forever(force=force)

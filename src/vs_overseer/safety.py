from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import SafetyConfig


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SafetyManager:
    def __init__(self, cfg: SafetyConfig) -> None:
        self.cfg = cfg
        self._recovery_times: deque[datetime] = deque()

    def record_recovery(self, at: datetime | None = None) -> None:
        now = at or utc_now()
        self._recovery_times.append(now)
        self._trim(now)

    def _trim(self, now: datetime) -> None:
        window = timedelta(minutes=max(1, int(self.cfg.crash_loop_window_minutes)))
        cutoff = now - window
        while self._recovery_times and self._recovery_times[0] < cutoff:
            self._recovery_times.popleft()

    def recovery_count(self) -> int:
        self._trim(utc_now())
        return len(self._recovery_times)

    def crash_loop_triggered(self) -> bool:
        return self.recovery_count() >= max(1, int(self.cfg.crash_loop_limit))

    def require_destructive_flag(
        self,
        *,
        operation: str,
        destructive_flag: bool,
        audit_logger: Callable[[str], None],
    ) -> tuple[bool, str]:
        if destructive_flag and self.cfg.allow_destructive_actions:
            return True, "allowed"
        reason = f"destructive_action_blocked:{operation}"
        audit_logger(reason)
        return False, reason

    def backoff_seconds(self, attempt_index: int) -> int:
        schedule = list(self.cfg.backoff_seconds)
        if not schedule:
            schedule = [5, 15, 45, 120, 300]
        idx = min(max(0, int(attempt_index)), len(schedule) - 1)
        return int(schedule[idx])

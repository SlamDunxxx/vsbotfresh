from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any, Callable
import urllib.request


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_number(text: str, patterns: list[str]) -> int | None:
    for raw in patterns:
        try:
            match = re.search(raw, text, flags=re.IGNORECASE | re.DOTALL)
        except Exception:  # noqa: BLE001
            continue
        if match is None:
            continue
        candidate = match.group(1) if match.groups() else match.group(0)
        digits = re.sub(r"[^0-9]", "", str(candidate))
        if not digits:
            continue
        try:
            value = int(digits)
        except Exception:  # noqa: BLE001
            continue
        if value > 0:
            return value
    return None


def _milestones(total: int, ratios: list[float]) -> list[int]:
    out: list[int] = []
    for ratio in ratios:
        value = int(round(float(total) * float(ratio)))
        value = max(1, min(int(total), value))
        out.append(value)
    out.append(int(total))
    out = sorted(set(out))
    return out


def _default_fetch_text(url: str, timeout_s: float) -> str:
    request = urllib.request.Request(url=url, headers={"User-Agent": "VSBotFresh/1.0 (+local overseer)"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="ignore")


@dataclass(frozen=True)
class WikiSyncResult:
    ok: bool
    changed: bool
    reason: str
    synced_at: str
    totals: dict[str, int]
    sources: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "changed": bool(self.changed),
            "reason": str(self.reason),
            "synced_at": str(self.synced_at),
            "totals": {str(k): int(v) for k, v in self.totals.items()},
            "sources": dict(self.sources),
        }


class WikiSyncer:
    def __init__(
        self,
        *,
        sources_path: Path,
        mapping_path: Path,
        timeout_seconds: float = 8.0,
        fetch_text: Callable[[str, float], str] | None = None,
    ) -> None:
        self.sources_path = sources_path
        self.mapping_path = mapping_path
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self._fetch_text = fetch_text or _default_fetch_text

    def _load_sources(self) -> list[dict[str, Any]]:
        payload = json.loads(self.sources_path.read_text(encoding="utf-8"))
        rows = payload.get("totals", []) if isinstance(payload, dict) else []
        return [dict(row) for row in rows if isinstance(row, dict)]

    def _fetch_totals(self, rows: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, Any]]:
        totals: dict[str, int] = {}
        source_status: dict[str, Any] = {}
        for row in rows:
            key = str(row.get("key", "")).strip()
            if not key:
                continue
            default = max(1, int(row.get("default", 1)))
            url = str(row.get("url", "")).strip()
            patterns = [str(x) for x in row.get("patterns", []) if str(x).strip()]
            value = default
            status: dict[str, Any] = {"url": url, "default": default, "value": default, "status": "default"}
            if url and patterns:
                try:
                    body = self._fetch_text(url, self.timeout_seconds)
                    parsed = _extract_number(body, patterns)
                    if parsed is not None and parsed > 0:
                        value = int(parsed)
                        status["status"] = "fetched"
                    else:
                        status["status"] = "parse_fallback_default"
                except Exception as exc:  # noqa: BLE001
                    status["status"] = f"fetch_error:{exc}"
            totals[key] = int(value)
            status["value"] = int(value)
            source_status[key] = status
        return totals, source_status

    @staticmethod
    def _refresh_mapping_payload(payload: dict[str, Any], totals: dict[str, int]) -> dict[str, Any]:
        rows = payload.get("templates", []) if isinstance(payload, dict) else []
        templates = [dict(row) for row in rows if isinstance(row, dict)]

        bestiary_total = max(1, int(totals.get("bestiary_target", 360)))
        achievement_total = max(1, int(totals.get("steam_achievements_target", 243)))

        bestiary_targets = _milestones(bestiary_total, [0.06, 0.10, 0.14, 0.22, 0.33, 0.55, 0.83, 1.00])
        achievement_targets = _milestones(achievement_total, [0.04, 0.10, 0.20, 0.30, 0.41, 0.62, 0.82, 1.00])

        for row in templates:
            prefix = str(row.get("id_prefix", "")).strip()
            if prefix == "wiki_bestiary_count":
                row["targets"] = bestiary_targets
            elif prefix == "wiki_achievements_count":
                row["targets"] = achievement_targets

        return {
            "templates": templates,
            "sync_meta": {
                "last_synced_at": _now_iso(),
                "totals": totals,
                "source": "vampire.survivors.wiki",
            },
        }

    def sync(self) -> WikiSyncResult:
        if not self.sources_path.exists():
            return WikiSyncResult(
                ok=False,
                changed=False,
                reason=f"missing_sources:{self.sources_path}",
                synced_at=_now_iso(),
                totals={},
                sources={},
            )
        if not self.mapping_path.exists():
            return WikiSyncResult(
                ok=False,
                changed=False,
                reason=f"missing_mapping:{self.mapping_path}",
                synced_at=_now_iso(),
                totals={},
                sources={},
            )

        rows = self._load_sources()
        if not rows:
            return WikiSyncResult(
                ok=False,
                changed=False,
                reason="empty_sources",
                synced_at=_now_iso(),
                totals={},
                sources={},
            )

        totals, source_status = self._fetch_totals(rows)

        before_raw = self.mapping_path.read_text(encoding="utf-8")
        before_payload = json.loads(before_raw)
        refreshed = self._refresh_mapping_payload(before_payload, totals)
        after_raw = json.dumps(refreshed, indent=2, ensure_ascii=True) + "\n"
        changed = after_raw != before_raw
        if changed:
            self.mapping_path.write_text(after_raw, encoding="utf-8")

        return WikiSyncResult(
            ok=True,
            changed=bool(changed),
            reason="ok",
            synced_at=_now_iso(),
            totals=totals,
            sources=source_status,
        )

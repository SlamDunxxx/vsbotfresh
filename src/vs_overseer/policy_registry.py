from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .models import PolicyParameters, utc_now_iso


@dataclass(frozen=True)
class PolicyRecord:
    policy_id: str
    parent_policy_id: str | None
    created_at: str
    parameters: PolicyParameters
    sim_metrics: dict[str, Any]
    promotion_state: str
    score: float
    live_metrics: dict[str, Any]


@dataclass
class CheckpointState:
    loop_cursor: int
    active_policy_id: str
    population_state: dict[str, Any]
    failure_counters: dict[str, Any]
    last_success_ts: str
    safe_pause: bool
    safe_pause_reason: str
    updated_at: str


class PolicyRegistry:
    def __init__(self, database_path: Path, policies_root: Path) -> None:
        self.database_path = database_path
        self.policies_root = policies_root
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.policies_root.mkdir(parents=True, exist_ok=True)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.database_path))
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _session(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _setup(self) -> None:
        with self._session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY,
                    parent_policy_id TEXT,
                    created_at TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    sim_metrics_json TEXT NOT NULL,
                    promotion_state TEXT NOT NULL,
                    score REAL NOT NULL,
                    live_metrics_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    loop_cursor INTEGER NOT NULL,
                    active_policy_id TEXT NOT NULL,
                    population_state_json TEXT NOT NULL,
                    failure_counters_json TEXT NOT NULL,
                    last_success_ts TEXT NOT NULL,
                    safe_pause INTEGER NOT NULL,
                    safe_pause_reason TEXT NOT NULL
                )
                """
            )

    def _get_state(self, conn: sqlite3.Connection, key: str, default: Any) -> Any:
        row = conn.execute("SELECT value_json FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except Exception:
            return default

    def _set_state(self, conn: sqlite3.Connection, key: str, value: Any) -> None:
        conn.execute(
            "INSERT INTO runtime_state(key, value_json) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value, ensure_ascii=True)),
        )

    def _policy_manifest_path(self, policy_id: str) -> Path:
        return self.policies_root / policy_id / "manifest.json"

    def _write_manifest(self, record: PolicyRecord) -> None:
        path = self._policy_manifest_path(record.policy_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "policy_id": record.policy_id,
            "parent_policy_id": record.parent_policy_id,
            "created_at": record.created_at,
            "parameters": record.parameters.to_dict(),
            "sim_metrics": record.sim_metrics,
            "promotion_state": record.promotion_state,
            "score": record.score,
            "live_metrics": record.live_metrics,
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    def bootstrap_baseline(self) -> PolicyRecord:
        with self._session() as conn:
            active_id = self._get_state(conn, "active_policy_id", "")
            if active_id:
                existing = self.get_policy(active_id)
                if existing is not None:
                    return existing

        baseline = PolicyParameters(aggression=0.55, greed=0.52, safety=0.63, focus=0.60)
        record = self.save_policy(
            parameters=baseline,
            parent_policy_id=None,
            sim_metrics={"episodes": 0},
            promotion_state="ACTIVE_BASELINE",
            score=0.0,
            live_metrics={"runs": 0, "blocked": True, "reason": "not_run"},
            policy_id="baseline-v1",
        )
        self.set_active_policy(record.policy_id)
        self.set_last_stable_policy(record.policy_id)
        return record

    def save_policy(
        self,
        *,
        parameters: PolicyParameters,
        parent_policy_id: str | None,
        sim_metrics: dict[str, Any],
        promotion_state: str,
        score: float,
        live_metrics: dict[str, Any],
        policy_id: str | None = None,
    ) -> PolicyRecord:
        pid = policy_id or f"p-{utc_now_iso().replace(':', '').replace('-', '').replace('+', 'z')}-{uuid.uuid4().hex[:8]}"
        created = utc_now_iso()
        record = PolicyRecord(
            policy_id=pid,
            parent_policy_id=parent_policy_id,
            created_at=created,
            parameters=parameters.clamp(),
            sim_metrics=sim_metrics,
            promotion_state=promotion_state,
            score=float(score),
            live_metrics=live_metrics,
        )
        with self._session() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO policies(
                    policy_id, parent_policy_id, created_at, parameters_json,
                    sim_metrics_json, promotion_state, score, live_metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.policy_id,
                    record.parent_policy_id,
                    record.created_at,
                    json.dumps(record.parameters.to_dict(), ensure_ascii=True),
                    json.dumps(record.sim_metrics, ensure_ascii=True),
                    record.promotion_state,
                    record.score,
                    json.dumps(record.live_metrics, ensure_ascii=True),
                ),
            )
        self._write_manifest(record)
        return record

    def update_policy(
        self,
        policy_id: str,
        *,
        promotion_state: str,
        sim_metrics: dict[str, Any],
        score: float,
        live_metrics: dict[str, Any],
    ) -> None:
        with self._session() as conn:
            row = conn.execute(
                "SELECT parameters_json, parent_policy_id, created_at FROM policies WHERE policy_id = ?",
                (policy_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"unknown policy_id {policy_id}")
            params = PolicyParameters.from_dict(json.loads(str(row["parameters_json"])))
            conn.execute(
                """
                UPDATE policies
                SET sim_metrics_json = ?, promotion_state = ?, score = ?, live_metrics_json = ?
                WHERE policy_id = ?
                """,
                (
                    json.dumps(sim_metrics, ensure_ascii=True),
                    promotion_state,
                    float(score),
                    json.dumps(live_metrics, ensure_ascii=True),
                    policy_id,
                ),
            )
        self._write_manifest(
            PolicyRecord(
                policy_id=policy_id,
                parent_policy_id=str(row["parent_policy_id"]) if row["parent_policy_id"] is not None else None,
                created_at=str(row["created_at"]),
                parameters=params,
                sim_metrics=sim_metrics,
                promotion_state=promotion_state,
                score=float(score),
                live_metrics=live_metrics,
            )
        )

    def get_policy(self, policy_id: str) -> PolicyRecord | None:
        with self._session() as conn:
            row = conn.execute("SELECT * FROM policies WHERE policy_id = ?", (policy_id,)).fetchone()
        if row is None:
            return None
        return PolicyRecord(
            policy_id=str(row["policy_id"]),
            parent_policy_id=str(row["parent_policy_id"]) if row["parent_policy_id"] is not None else None,
            created_at=str(row["created_at"]),
            parameters=PolicyParameters.from_dict(json.loads(str(row["parameters_json"]))),
            sim_metrics=json.loads(str(row["sim_metrics_json"])),
            promotion_state=str(row["promotion_state"]),
            score=float(row["score"]),
            live_metrics=json.loads(str(row["live_metrics_json"])),
        )

    def list_recent_policies(self, limit: int = 20) -> list[PolicyRecord]:
        with self._session() as conn:
            rows = conn.execute(
                "SELECT * FROM policies ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [
            PolicyRecord(
                policy_id=str(r["policy_id"]),
                parent_policy_id=str(r["parent_policy_id"]) if r["parent_policy_id"] is not None else None,
                created_at=str(r["created_at"]),
                parameters=PolicyParameters.from_dict(json.loads(str(r["parameters_json"]))),
                sim_metrics=json.loads(str(r["sim_metrics_json"])),
                promotion_state=str(r["promotion_state"]),
                score=float(r["score"]),
                live_metrics=json.loads(str(r["live_metrics_json"])),
            )
            for r in rows
        ]

    def get_active_policy_id(self) -> str:
        with self._session() as conn:
            return str(self._get_state(conn, "active_policy_id", ""))

    def set_active_policy(self, policy_id: str) -> None:
        with self._session() as conn:
            self._set_state(conn, "active_policy_id", policy_id)

    def get_last_stable_policy(self) -> str:
        with self._session() as conn:
            return str(self._get_state(conn, "last_stable_policy_id", ""))

    def set_last_stable_policy(self, policy_id: str) -> None:
        with self._session() as conn:
            self._set_state(conn, "last_stable_policy_id", policy_id)

    def load_checkpoint(self) -> CheckpointState:
        with self._session() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints ORDER BY checkpoint_id DESC LIMIT 1"
            ).fetchone()
            active = str(self._get_state(conn, "active_policy_id", ""))
        if row is None:
            return CheckpointState(
                loop_cursor=0,
                active_policy_id=active,
                population_state={},
                failure_counters={"recoveries": 0, "regression_windows": 0},
                last_success_ts="",
                safe_pause=False,
                safe_pause_reason="",
                updated_at=utc_now_iso(),
            )
        return CheckpointState(
            loop_cursor=int(row["loop_cursor"]),
            active_policy_id=str(row["active_policy_id"]),
            population_state=json.loads(str(row["population_state_json"])),
            failure_counters=json.loads(str(row["failure_counters_json"])),
            last_success_ts=str(row["last_success_ts"]),
            safe_pause=bool(int(row["safe_pause"])),
            safe_pause_reason=str(row["safe_pause_reason"]),
            updated_at=str(row["created_at"]),
        )

    def save_checkpoint(self, state: CheckpointState) -> None:
        with self._session() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints(
                    created_at, loop_cursor, active_policy_id, population_state_json,
                    failure_counters_json, last_success_ts, safe_pause, safe_pause_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utc_now_iso(),
                    int(state.loop_cursor),
                    state.active_policy_id,
                    json.dumps(state.population_state, ensure_ascii=True),
                    json.dumps(state.failure_counters, ensure_ascii=True),
                    state.last_success_ts,
                    1 if state.safe_pause else 0,
                    state.safe_pause_reason,
                ),
            )
            self._set_state(conn, "active_policy_id", state.active_policy_id)

    def set_safe_pause(self, *, reason: str) -> None:
        state = self.load_checkpoint()
        state.safe_pause = True
        state.safe_pause_reason = reason
        state.updated_at = utc_now_iso()
        self.save_checkpoint(state)

    def clear_safe_pause(self) -> None:
        state = self.load_checkpoint()
        state.safe_pause = False
        state.safe_pause_reason = ""
        state.updated_at = utc_now_iso()
        self.save_checkpoint(state)

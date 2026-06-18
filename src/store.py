from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class WorkflowStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED_APPROVAL = "paused_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"
    CRASHED = "crashed"


@dataclass(frozen=True)
class WorkflowState:
    workflow_id: str
    workflow_type: str
    current_step: int
    step_data: dict[str, Any]
    status: WorkflowStatus
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class StepResult:
    step_name: str
    output: dict[str, Any]
    duration_ms: float
    cost_usd: float = 0.0
    model_used: str | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            object.__setattr__(self, "timestamp", utc_now())


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _loads_dict(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


class WorkflowStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id     TEXT PRIMARY KEY,
                    workflow_type   TEXT NOT NULL,
                    current_step    INTEGER NOT NULL DEFAULT -1,
                    step_data       TEXT NOT NULL DEFAULT '{}',
                    status          TEXT NOT NULL DEFAULT 'pending',
                    created_at      TEXT NOT NULL,
                    updated_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS step_results (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id     TEXT NOT NULL,
                    step_index      INTEGER NOT NULL,
                    step_name       TEXT NOT NULL,
                    output          TEXT NOT NULL,
                    duration_ms     REAL NOT NULL,
                    cost_usd        REAL NOT NULL DEFAULT 0.0,
                    model_used      TEXT,
                    created_at      TEXT NOT NULL,
                    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                );

                CREATE TABLE IF NOT EXISTS approval_queue (
                    gate_id         TEXT PRIMARY KEY,
                    workflow_id     TEXT NOT NULL,
                    step_name       TEXT NOT NULL,
                    payload         TEXT NOT NULL,
                    status          TEXT NOT NULL DEFAULT 'pending',
                    requested_at    TEXT NOT NULL,
                    decided_at      TEXT,
                    decided_by      TEXT,
                    rejection_reason TEXT,
                    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                );

                CREATE TABLE IF NOT EXISTS side_effect_log (
                    idempotency_key TEXT PRIMARY KEY,
                    workflow_id     TEXT NOT NULL,
                    step_name       TEXT NOT NULL,
                    result          TEXT NOT NULL,
                    executed_at     TEXT NOT NULL,
                    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
                );

                CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
                CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_queue(status);
                CREATE INDEX IF NOT EXISTS idx_step_results_workflow ON step_results(workflow_id);
                """
            )

    def create_workflow(
        self,
        workflow_type: str,
        workflow_id: str | None = None,
        initial_data: dict[str, Any] | None = None,
    ) -> WorkflowState:
        workflow_id = workflow_id or f"wf-{uuid.uuid4().hex[:12]}"
        now = utc_now()
        step_data = initial_data or {}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows
                  (workflow_id, workflow_type, current_step, step_data, status, created_at, updated_at)
                VALUES (?, ?, -1, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    workflow_type,
                    json.dumps(step_data, sort_keys=True),
                    WorkflowStatus.PENDING.value,
                    now,
                    now,
                ),
            )
        return self.load_workflow(workflow_id)

    def save_checkpoint(self, workflow_id: str, step_index: int, result: StepResult) -> WorkflowState:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT step_data FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workflow not found: {workflow_id}")
            step_data = _loads_dict(row["step_data"])
            step_data[result.step_name] = result.output
            conn.execute(
                """
                INSERT INTO step_results
                  (workflow_id, step_index, step_name, output, duration_ms, cost_usd, model_used, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    workflow_id,
                    step_index,
                    result.step_name,
                    json.dumps(result.output, sort_keys=True),
                    result.duration_ms,
                    result.cost_usd,
                    result.model_used,
                    result.timestamp or now,
                ),
            )
            conn.execute(
                """
                UPDATE workflows
                SET current_step = ?, step_data = ?, status = ?, updated_at = ?
                WHERE workflow_id = ?
                """,
                (
                    step_index,
                    json.dumps(step_data, sort_keys=True),
                    WorkflowStatus.RUNNING.value,
                    now,
                    workflow_id,
                ),
            )
        return self.load_workflow(workflow_id)

    def load_workflow(self, workflow_id: str) -> WorkflowState:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflows WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"workflow not found: {workflow_id}")
        return self._row_to_state(row)

    def list_pending(self) -> list[WorkflowState]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM workflows
                WHERE status IN (?, ?, ?, ?)
                ORDER BY updated_at ASC
                """,
                (
                    WorkflowStatus.PENDING.value,
                    WorkflowStatus.RUNNING.value,
                    WorkflowStatus.PAUSED_APPROVAL.value,
                    WorkflowStatus.APPROVED.value,
                ),
            ).fetchall()
        return [self._row_to_state(row) for row in rows]

    def update_status(self, workflow_id: str, status: WorkflowStatus | str) -> WorkflowState:
        normalized = WorkflowStatus(status)
        with self.connect() as conn:
            conn.execute(
                "UPDATE workflows SET status = ?, updated_at = ? WHERE workflow_id = ?",
                (normalized.value, utc_now(), workflow_id),
            )
        return self.load_workflow(workflow_id)

    def detect_crashed(self, stale_after_seconds: int = 30) -> list[WorkflowState]:
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
        crashed: list[WorkflowState] = []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflows WHERE status = ?",
                (WorkflowStatus.RUNNING.value,),
            ).fetchall()
            for row in rows:
                updated_at = datetime.fromisoformat(row["updated_at"])
                if updated_at < cutoff:
                    conn.execute(
                        "UPDATE workflows SET status = ?, updated_at = ? WHERE workflow_id = ?",
                        (WorkflowStatus.CRASHED.value, utc_now(), row["workflow_id"]),
                    )
                    crashed.append(self.load_workflow(row["workflow_id"]))
        return crashed

    def mark_stale_for_demo(self, workflow_id: str, seconds_old: int = 120) -> None:
        stale = datetime.now(UTC) - timedelta(seconds=seconds_old)
        with self.connect() as conn:
            conn.execute(
                "UPDATE workflows SET updated_at = ? WHERE workflow_id = ?",
                (stale.isoformat(), workflow_id),
            )

    def step_results(self, workflow_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM step_results
                WHERE workflow_id = ?
                ORDER BY step_index, id
                """,
                (workflow_id,),
            ).fetchall()
        return [dict(row) | {"output": json.loads(row["output"])} for row in rows]

    def log_side_effect(
        self,
        idempotency_key: str,
        workflow_id: str,
        step_name: str,
        result: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO side_effect_log
                  (idempotency_key, workflow_id, step_name, result, executed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    workflow_id,
                    step_name,
                    json.dumps(result, sort_keys=True),
                    utc_now(),
                ),
            )

    def get_side_effect(self, idempotency_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT result FROM side_effect_log WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        return None if row is None else json.loads(row["result"])

    def side_effect_count(self, workflow_id: str, step_name: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM side_effect_log WHERE workflow_id = ?"
        params: tuple[Any, ...] = (workflow_id,)
        if step_name:
            query += " AND step_name = ?"
            params = (workflow_id, step_name)
        with self.connect() as conn:
            row = conn.execute(query, params).fetchone()
        return int(row["count"])

    def _row_to_state(self, row: sqlite3.Row) -> WorkflowState:
        return WorkflowState(
            workflow_id=row["workflow_id"],
            workflow_type=row["workflow_type"],
            current_step=int(row["current_step"]),
            step_data=_loads_dict(row["step_data"]),
            status=WorkflowStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

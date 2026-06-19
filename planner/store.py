from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from src.store import StepResult, WorkflowStore, utc_now

from .budget import Remaining
from .constraints import ExecutionConstraints
from .outcomes import Attempt, PlanOutcome
from .serialization import to_jsonable
from .solver import ExecutionPlan
from .taskclass import TASK_CLASS_TAXONOMY_VERSION, TaskClass


class PlannerStore:
    def __init__(self, db_path: str | Path):
        self.workflow_store = WorkflowStore(db_path)
        self.db_path = Path(db_path)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        return self.workflow_store.connect()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS planner_targets (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, tier TEXT NOT NULL,
                  model_id TEXT NOT NULL, privacy_class TEXT NOT NULL, region TEXT,
                  cost_in_per_1k REAL NOT NULL, cost_out_per_1k REAL NOT NULL,
                  enabled INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS planner_target_stats (
                  target_id TEXT NOT NULL, task_class TEXT NOT NULL, taxonomy_version INTEGER NOT NULL,
                  latency_ms_p50 REAL, latency_ms_p95 REAL,
                  success_rate REAL, sample_count INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY (target_id, task_class, taxonomy_version)
                );
                CREATE TABLE IF NOT EXISTS planner_plans (
                  id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
                  constraints_json TEXT NOT NULL, plan_json TEXT NOT NULL,
                  status TEXT NOT NULL, planning_ms REAL NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planner_outcomes (
                  id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, step_index INTEGER NOT NULL,
                  target_id TEXT NOT NULL, actual_cost_usd REAL, actual_latency_ms INTEGER,
                  verifiable_outcome TEXT NOT NULL, success INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS planner_budgets (
                  budget_id TEXT PRIMARY KEY, limit_usd REAL NOT NULL,
                  spent_usd REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
                );
                """
            )

    def create_plan_workflow(
        self,
        request_id: str,
        constraints: ExecutionConstraints,
        plan: ExecutionPlan,
    ) -> str:
        workflow_id = self._workflow_id(plan.id)
        try:
            self.workflow_store.create_workflow(
                workflow_type="planner_request",
                workflow_id=workflow_id,
                initial_data={
                    "request_id": request_id,
                    "constraints": to_jsonable(constraints),
                    "plan": to_jsonable(plan),
                },
            )
        except sqlite3.IntegrityError:
            pass
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO planner_plans
                  (id, request_id, constraints_json, plan_json, status, planning_ms, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  constraints_json = excluded.constraints_json,
                  plan_json = excluded.plan_json,
                  status = excluded.status,
                  planning_ms = excluded.planning_ms
                """,
                (
                    plan.id,
                    request_id,
                    json.dumps(to_jsonable(constraints), sort_keys=True),
                    json.dumps(to_jsonable(plan), sort_keys=True),
                    plan.status.value,
                    plan.planning_ms,
                    utc_now(),
                ),
            )
        return workflow_id

    def checkpoint_attempt(self, plan: ExecutionPlan, attempt: Attempt) -> None:
        workflow_id = self._workflow_id(plan.id)
        try:
            self.workflow_store.load_workflow(workflow_id)
        except KeyError:
            self.workflow_store.create_workflow(
                workflow_type="planner_request",
                workflow_id=workflow_id,
                initial_data={"request_id": plan.request_id, "plan_id": plan.id},
            )
        result = StepResult(
            step_name=f"attempt_{attempt.step_index}",
            output={
                "target_id": attempt.target_id,
                "verifiable_outcome": attempt.verifiable_outcome.value,
                "actual_latency_ms": attempt.actual_latency_ms,
                "actual_cost_usd": attempt.actual_cost_usd,
                "success": attempt.success,
            },
            duration_ms=attempt.actual_latency_ms,
            cost_usd=attempt.actual_cost_usd,
        )
        self.workflow_store.save_checkpoint(workflow_id, attempt.step_index, result)
        self._insert_attempt(plan.id, attempt)

    def insert_outcome(self, plan: ExecutionPlan, outcome: PlanOutcome) -> list[Attempt]:
        inserted: list[Attempt] = []
        for attempt in outcome.attempts:
            if self._insert_attempt(plan.id, attempt):
                inserted.append(attempt)
        return inserted

    def update_target_stats(self, target_id: str, task_class: TaskClass, attempt: Attempt) -> None:
        now = utc_now()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM planner_target_stats
                WHERE target_id = ? AND task_class = ? AND taxonomy_version = ?
                """,
                (target_id, task_class.value, TASK_CLASS_TAXONOMY_VERSION),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO planner_target_stats
                      (target_id, task_class, taxonomy_version, latency_ms_p50, latency_ms_p95,
                       success_rate, sample_count, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        target_id,
                        task_class.value,
                        TASK_CLASS_TAXONOMY_VERSION,
                        attempt.actual_latency_ms,
                        attempt.actual_latency_ms,
                        1.0 if attempt.success else 0.0,
                        now,
                    ),
                )
                return
            sample_count = int(row["sample_count"]) + 1
            alpha = 0.2
            old_success = float(row["success_rate"] or 0.0)
            new_success = old_success * (1.0 - alpha) + (1.0 if attempt.success else 0.0) * alpha
            old_p50 = float(row["latency_ms_p50"] or attempt.actual_latency_ms)
            old_p95 = float(row["latency_ms_p95"] or attempt.actual_latency_ms)
            latency = float(attempt.actual_latency_ms)
            new_p50 = old_p50 * (1.0 - alpha) + latency * alpha
            new_p95 = max(new_p50, old_p95 * (1.0 - alpha) + latency * alpha)
            conn.execute(
                """
                UPDATE planner_target_stats
                SET latency_ms_p50 = ?, latency_ms_p95 = ?, success_rate = ?,
                    sample_count = ?, updated_at = ?
                WHERE target_id = ? AND task_class = ? AND taxonomy_version = ?
                """,
                (
                    new_p50,
                    new_p95,
                    new_success,
                    sample_count,
                    now,
                    target_id,
                    task_class.value,
                    TASK_CLASS_TAXONOMY_VERSION,
                ),
            )

    def get_target_stats(self, target_id: str, task_class: TaskClass) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM planner_target_stats
                WHERE target_id = ? AND task_class = ? AND taxonomy_version = ?
                """,
                (target_id, task_class.value, TASK_CLASS_TAXONOMY_VERSION),
            ).fetchone()
        return None if row is None else dict(row)

    def upsert_budget(self, budget_id: str, limit_usd: float, spent_usd: float) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO planner_budgets (budget_id, limit_usd, spent_usd, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(budget_id) DO UPDATE SET
                  limit_usd = excluded.limit_usd,
                  spent_usd = excluded.spent_usd,
                  updated_at = excluded.updated_at
                """,
                (budget_id, limit_usd, spent_usd, utc_now()),
            )

    def get_budget(self, budget_id: str) -> Remaining | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM planner_budgets WHERE budget_id = ?",
                (budget_id,),
            ).fetchone()
        if row is None:
            return None
        return Remaining(
            budget_id=row["budget_id"],
            limit_usd=float(row["limit_usd"]),
            spent_usd=float(row["spent_usd"]),
        )

    def load_plan_json(self, request_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM planner_plans
                WHERE request_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "request_id": row["request_id"],
            "status": row["status"],
            "planning_ms": row["planning_ms"],
            "plan": json.loads(row["plan_json"]),
            "constraints": json.loads(row["constraints_json"]),
        }

    def _insert_attempt(self, plan_id: str, attempt: Attempt) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO planner_outcomes
                  (id, plan_id, step_index, target_id, actual_cost_usd, actual_latency_ms,
                   verifiable_outcome, success, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self._attempt_id(plan_id, attempt),
                    plan_id,
                    attempt.step_index,
                    attempt.target_id,
                    attempt.actual_cost_usd,
                    attempt.actual_latency_ms,
                    attempt.verifiable_outcome.value,
                    1 if attempt.success else 0,
                    utc_now(),
                ),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _workflow_id(plan_id: str) -> str:
        return f"planner:{plan_id}"

    @staticmethod
    def _attempt_id(plan_id: str, attempt: Attempt) -> str:
        basis = (
            f"{plan_id}:{attempt.step_index}:{attempt.target_id}:"
            f"{attempt.verifiable_outcome.value}:{attempt.actual_latency_ms}:{attempt.actual_cost_usd}"
        )
        return uuid.uuid5(uuid.NAMESPACE_URL, basis).hex

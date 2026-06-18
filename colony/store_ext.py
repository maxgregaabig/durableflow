from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.store import StepResult, WorkflowStore

from .models import Job, JobStatus, RunReport


class ColonyStore:
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
                CREATE TABLE IF NOT EXISTS colony_jobs (
                    job_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    batch_id TEXT NOT NULL,
                    spec TEXT NOT NULL,
                    stage_count INTEGER NOT NULL,
                    current_stage INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    assigned_instance_id TEXT,
                    checkpoint_ref TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS colony_runs (
                    run_id TEXT PRIMARY KEY,
                    report TEXT NOT NULL
                );
                """
            )

    def create_job(self, run_id: str, job: Job) -> None:
        workflow_id = self._workflow_id(run_id, job)
        self.workflow_store.create_workflow(
            workflow_type="colony_job",
            workflow_id=workflow_id,
            initial_data={"batch_id": job.batch_id, "spec": job.spec},
        )
        self.save_job(run_id, job)

    def save_job(self, run_id: str, job: Job) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO colony_jobs
                  (job_id, run_id, batch_id, spec, stage_count, current_stage, status,
                   assigned_instance_id, checkpoint_ref, attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                  current_stage = excluded.current_stage,
                  status = excluded.status,
                  assigned_instance_id = excluded.assigned_instance_id,
                  checkpoint_ref = excluded.checkpoint_ref,
                  attempts = excluded.attempts
                """,
                (
                    job.job_id,
                    run_id,
                    job.batch_id,
                    json.dumps(job.spec, sort_keys=True),
                    job.stage_count,
                    job.current_stage,
                    job.status.value,
                    job.assigned_instance_id,
                    job.checkpoint_ref,
                    job.attempts,
                ),
            )

    def checkpoint_job(self, run_id: str, job: Job, stage: int, output: dict[str, Any], duration_s: float) -> None:
        result = StepResult(
            step_name=f"stage_{stage}",
            output=output,
            duration_ms=duration_s * 1000.0,
        )
        workflow_id = self._workflow_id(run_id, job)
        self.workflow_store.save_checkpoint(workflow_id, stage, result)
        job.current_stage = stage
        job.status = JobStatus.CHECKPOINTED
        job.checkpoint_ref = f"{job.job_id}:stage:{stage}"
        self.save_job(run_id, job)

    def save_report(self, report: RunReport) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO colony_runs (run_id, report)
                VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET report = excluded.report
                """,
                (report.run_id, json.dumps(report.__dict__, sort_keys=True)),
            )

    def dispatch_once(self, run_id: str, job: Job, instance_id: str) -> bool:
        key = f"{run_id}:{job.job_id}:dispatch:{job.current_stage + 1}"
        existing = self.workflow_store.get_side_effect(key)
        if existing is not None:
            return False
        self.workflow_store.log_side_effect(
            key,
            self._workflow_id(run_id, job),
            "dispatch",
            {"instance_id": instance_id, "stage": job.current_stage + 1},
        )
        return True

    def _workflow_id(self, run_id: str, job: Job) -> str:
        return f"{run_id}:{job.job_id}"

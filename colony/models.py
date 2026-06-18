from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    CHECKPOINTED = "checkpointed"
    RECOVERING = "recovering"
    COMPLETED = "completed"
    FAILED = "failed"


class InstanceStatus(StrEnum):
    REQUESTED = "requested"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    LOST = "lost"
    RELEASED = "released"


@dataclass
class Job:
    job_id: str
    batch_id: str
    spec: dict[str, Any]
    stage_count: int
    current_stage: int = -1
    status: JobStatus = JobStatus.QUEUED
    assigned_instance_id: str | None = None
    checkpoint_ref: str | None = None
    attempts: int = 0


@dataclass
class Instance:
    instance_id: str
    provider: str
    gpu_type: str
    cost_per_hour_usd: float
    status: InstanceStatus = InstanceStatus.REQUESTED
    slot: int = 0
    acquired_at: float = 0.0
    lost_at: float | None = None
    released_at: float | None = None
    provider_handle: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageResult:
    stage_index: int
    duration_s: float
    output: dict[str, Any]


@dataclass(frozen=True)
class ChaosEvent:
    event_id: str
    scheduled_at_offset_s: float
    event_type: str
    target_slot: int
    target_instance_id: str | None = None
    applied: bool = False


@dataclass
class RunReport:
    run_id: str
    mode: str
    runner: str
    batch_size: int
    jobs_completed: int = 0
    jobs_failed: int = 0
    instances_acquired: int = 0
    instances_lost: int = 0
    recoveries: int = 0
    human_interventions: int = 0
    total_cost_usd: float = 0.0
    wall_clock_seconds: float = 0.0
    budget_usd: float = 0.0
    budget_halted: bool = False
    chaos_seed: int = 0
    started_at: float = 0.0
    ended_at: float = 0.0

    @property
    def completion_rate(self) -> float:
        if self.batch_size == 0:
            return 0.0
        return self.jobs_completed / self.batch_size

    @property
    def completion_rate_pct(self) -> float:
        return self.completion_rate * 100.0


def make_eval_batch(batch_size: int = 20, batch_id: str = "eval-batch") -> list[Job]:
    stages = ["setup", "data_load", "inference_eval_shard", "metrics_write", "artifact_upload"]
    return [
        Job(
            job_id=f"job-{index:02d}",
            batch_id=batch_id,
            spec={
                "workload": "toy_retrieval_model_eval",
                "shard": index,
                "stages": stages,
                "stage_durations_s": [5.0, 7.0, 13.0, 4.0, 3.0],
            },
            stage_count=len(stages),
        )
        for index in range(batch_size)
    ]

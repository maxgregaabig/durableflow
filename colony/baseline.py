from __future__ import annotations

import tempfile
from pathlib import Path

from .chaos import ChaosSchedule
from .cost import CostAccountant
from .models import Instance, Job, JobStatus, RunReport
from .provider import ComputeProvider


class NaiveRunner:
    def __init__(
        self,
        provider: ComputeProvider,
        schedule: ChaosSchedule,
        *,
        pool_size: int = 5,
        max_retries: int = 1,
        db_path: str | Path | None = None,
    ):
        self.provider = provider
        self.schedule = schedule
        self.pool_size = pool_size
        self.max_retries = max_retries
        self.cost = CostAccountant()
        self.db_path = db_path or Path(tempfile.gettempdir()) / "colony-naive.sqlite"

    def run_batch(self, batch: list[Job], budget: float, run_id: str = "naive-run") -> RunReport:
        report = RunReport(
            run_id=run_id,
            mode=self.provider.mode,
            runner="naive",
            batch_size=len(batch),
            budget_usd=budget,
            chaos_seed=self.schedule.seed,
        )
        instances = [self.provider.acquire(slot=slot, now=0.0) for slot in range(self.pool_size)]
        report.instances_acquired = len(instances)
        now = 0.0
        for index, job in enumerate(batch):
            slot = index % self.pool_size
            instance = instances[slot]
            completed, now, instance = self._run_job(job, instance, slot, now, report, budget)
            instances[slot] = instance
            if completed:
                report.jobs_completed += 1
                job.status = JobStatus.COMPLETED
            else:
                report.jobs_failed += 1
                job.status = JobStatus.FAILED
            report.wall_clock_seconds = now
            if report.budget_halted:
                break
        report.total_cost_usd = self.cost.total()
        report.ended_at = report.wall_clock_seconds
        return report

    def _run_job(
        self,
        job: Job,
        instance: Instance,
        slot: int,
        now: float,
        report: RunReport,
        budget: float,
    ) -> tuple[bool, float, Instance]:
        attempt = 0
        while attempt <= self.max_retries:
            for stage in range(job.stage_count):
                result = self.provider.run_stage(instance, job, stage)
                end = now + result.duration_s
                event = self.schedule.between(now, end, slot)
                if event is not None:
                    elapsed = max(0.0, event.scheduled_at_offset_s - now)
                    self._charge(instance, elapsed, report)
                    now = event.scheduled_at_offset_s
                    report.wall_clock_seconds = now
                    self.schedule.apply(event, self.provider, instance, now=now)
                    report.instances_lost += 1
                    attempt += 1
                    job.attempts = attempt
                    job.current_stage = -1
                    if report.total_cost_usd >= budget:
                        report.budget_halted = True
                        return False, now, instance
                    instance = self.provider.acquire(slot=slot, now=now)
                    report.instances_acquired += 1
                    break
                self._charge(instance, result.duration_s, report)
                now = end
                report.wall_clock_seconds = now
                if report.total_cost_usd > budget:
                    report.budget_halted = True
                    return False, now, instance
            else:
                return True, now, instance
        return False, now, instance

    def _charge(self, instance: Instance, seconds: float, report: RunReport) -> None:
        self.cost.charge(instance, seconds)
        report.total_cost_usd = self.cost.total()

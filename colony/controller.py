from __future__ import annotations

import tempfile
from pathlib import Path

from .chaos import ChaosSchedule
from .cost import CostAccountant
from .models import Instance, Job, JobStatus, RunReport
from .provider import ComputeProvider
from .store_ext import ColonyStore


class ColonyController:
    def __init__(
        self,
        provider: ComputeProvider,
        schedule: ChaosSchedule,
        *,
        pool_size: int = 5,
        db_path: str | Path | None = None,
    ):
        self.provider = provider
        self.schedule = schedule
        self.pool_size = pool_size
        self.store = ColonyStore(db_path or Path(tempfile.gettempdir()) / "colony.sqlite")
        self.cost = CostAccountant()

    def run_batch(self, batch: list[Job], budget: float, run_id: str = "colony-run") -> RunReport:
        report = RunReport(
            run_id=run_id,
            mode=self.provider.mode,
            runner="colony",
            batch_size=len(batch),
            budget_usd=budget,
            chaos_seed=self.schedule.seed,
        )
        instances = [self.provider.acquire(slot=slot, now=0.0) for slot in range(self.pool_size)]
        report.instances_acquired = len(instances)
        for job in batch:
            self.store.create_job(run_id, job)

        now = 0.0
        job_index = 0
        while job_index < len(batch):
            job = batch[job_index]
            if report.total_cost_usd >= budget:
                report.budget_halted = True
                break
            slot = job_index % self.pool_size
            instance = instances[slot]
            if self.provider.health(instance).value != "healthy":
                instance = self.provider.acquire(slot=slot, now=now)
                instances[slot] = instance
                report.instances_acquired += 1

            completed = self._run_job_stagewise(run_id, job, instance, instances, slot, report, now, budget)
            now = report.wall_clock_seconds
            if completed:
                report.jobs_completed += 1
                job.status = JobStatus.COMPLETED
                self.store.save_job(run_id, job)
                job_index += 1
            elif report.budget_halted:
                break
            else:
                job.status = JobStatus.FAILED
                report.jobs_failed += 1
                self.store.save_job(run_id, job)
                job_index += 1

        report.ended_at = report.wall_clock_seconds
        report.total_cost_usd = self.cost.total()
        assert report.human_interventions == 0
        self.store.save_report(report)
        return report

    def _run_job_stagewise(
        self,
        run_id: str,
        job: Job,
        instance: Instance,
        instances: list[Instance],
        slot: int,
        report: RunReport,
        now: float,
        budget: float,
    ) -> bool:
        while job.current_stage + 1 < job.stage_count:
            stage = job.current_stage + 1
            job.status = JobStatus.RUNNING
            job.assigned_instance_id = instance.instance_id
            self.store.dispatch_once(run_id, job, instance.instance_id)
            self.store.save_job(run_id, job)

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
                report.recoveries += 1
                job.status = JobStatus.RECOVERING
                self.store.save_job(run_id, job)
                if report.total_cost_usd >= budget:
                    report.budget_halted = True
                    return False
                instance = self.provider.acquire(slot=slot, now=now)
                instances[slot] = instance
                report.instances_acquired += 1
                continue

            self._charge(instance, result.duration_s, report)
            now = end
            report.wall_clock_seconds = now
            if report.total_cost_usd > budget:
                report.budget_halted = True
                return False
            self.store.checkpoint_job(run_id, job, stage, result.output, result.duration_s)

        return True

    def _charge(self, instance: Instance, seconds: float, report: RunReport) -> None:
        self.cost.charge(instance, seconds)
        report.total_cost_usd = self.cost.total()

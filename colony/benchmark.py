from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .baseline import NaiveRunner
from .chaos import ChaosProfile, ChaosSchedule
from .controller import ColonyController
from .models import Job, RunReport
from .provider import ComputeProvider


@dataclass
class BenchmarkResult:
    chaos_profile: str
    seed: int
    naive: RunReport
    colony: RunReport

    @property
    def completion_rate_delta(self) -> float:
        return self.colony.completion_rate - self.naive.completion_rate

    @property
    def cost_delta(self) -> float:
        delta = self.colony.total_cost_usd - self.naive.total_cost_usd
        return 0.0 if abs(delta) < 0.005 else delta

    @property
    def wall_clock_delta(self) -> float:
        return self.colony.wall_clock_seconds - self.naive.wall_clock_seconds

    def to_table(self) -> str:
        lines = [
            "                  completion   cost     wall    recoveries  interventions",
            self._row("naive", self.naive),
            self._row("dflow-vast", self.colony),
            "",
            (
                f"completion delta: {self.completion_rate_delta * 100:+.0f} pts"
                f"     cost delta: {self.cost_delta:+.2f}"
                f"   under identical loss schedule (seed {self.seed})"
            ),
        ]
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "chaos_profile": self.chaos_profile,
                "seed": self.seed,
                "naive": self.naive.__dict__,
                "colony": self.colony.__dict__,
                "completion_rate_delta": self.completion_rate_delta,
                "cost_delta": self.cost_delta,
                "wall_clock_delta": self.wall_clock_delta,
            },
            indent=2,
            sort_keys=True,
        )

    def _row(self, label: str, report: RunReport) -> str:
        recoveries = "--" if report.runner == "naive" else str(report.recoveries)
        interventions = "--" if report.runner == "naive" else str(report.human_interventions)
        return (
            f"{label:<16} {report.completion_rate_pct:>6.0f}%"
            f"     ${report.total_cost_usd:>5.2f}"
            f"   {report.wall_clock_seconds:>5.0f}s"
            f"      {recoveries:>4}          {interventions:>4}"
        )


class Benchmark:
    def __init__(
        self,
        provider_factory: Callable[[], ComputeProvider],
        *,
        profile: ChaosProfile,
        db_dir: str | Path | None = None,
    ):
        self.provider_factory = provider_factory
        self.profile = profile
        self.db_dir = Path(db_dir or tempfile.mkdtemp(prefix="colony-"))

    def run(self, batch: list[Job], budget: float) -> BenchmarkResult:
        schedule = ChaosSchedule.generate(
            self.profile.seed,
            self.profile.duration_s,
            self.profile.loss_rate,
            self.profile.pool_size,
        )
        naive_batch = [self._clone_job(job) for job in batch]
        colony_batch = [self._clone_job(job) for job in batch]
        naive = NaiveRunner(
            self.provider_factory(),
            schedule,
            pool_size=self.profile.pool_size,
            db_path=self.db_dir / "naive.sqlite",
        ).run_batch(naive_batch, budget, run_id="naive")
        colony = ColonyController(
            self.provider_factory(),
            schedule,
            pool_size=self.profile.pool_size,
            db_path=self.db_dir / "colony.sqlite",
        ).run_batch(colony_batch, budget, run_id="colony")
        return BenchmarkResult(self.profile.name, self.profile.seed, naive, colony)

    def _clone_job(self, job: Job) -> Job:
        return Job(job.job_id, job.batch_id, dict(job.spec), job.stage_count)

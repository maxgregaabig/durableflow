from __future__ import annotations

from dataclasses import dataclass, field

from .benchmark import BenchmarkResult
from .models import RunReport


@dataclass(frozen=True)
class ScoreboardView:
    runner_label: str
    jobs_total: int
    jobs_completed: int
    jobs_recovering: int
    jobs_failed: int
    instances_healthy: int
    instances_lost: int
    spend_usd: float
    budget_usd: float
    recoveries: int
    interventions: int
    recent_events: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResultRow:
    label: str
    completion_rate_pct: float
    cost_usd: float
    wall_clock_s: float
    recoveries: int | str
    interventions: int | str


@dataclass(frozen=True)
class ComparisonView:
    naive_row: ResultRow
    colony_row: ResultRow
    completion_delta_pts: float
    cost_delta_usd: float
    wall_delta_s: float
    chaos_profile: str
    seed: int
    mode: str


def build_scoreboard_view(report: RunReport) -> ScoreboardView:
    return ScoreboardView(
        runner_label=report.runner,
        jobs_total=report.batch_size,
        jobs_completed=report.jobs_completed,
        jobs_recovering=report.recoveries,
        jobs_failed=report.jobs_failed,
        instances_healthy=max(0, report.instances_acquired - report.instances_lost),
        instances_lost=report.instances_lost,
        spend_usd=report.total_cost_usd,
        budget_usd=report.budget_usd,
        recoveries=report.recoveries,
        interventions=report.human_interventions,
    )


def build_comparison_view(result: BenchmarkResult) -> ComparisonView:
    return ComparisonView(
        naive_row=_row("naive", result.naive, baseline=True),
        colony_row=_row("dflow-vast", result.colony, baseline=False),
        completion_delta_pts=result.completion_rate_delta * 100.0,
        cost_delta_usd=result.cost_delta,
        wall_delta_s=result.wall_clock_delta,
        chaos_profile=result.chaos_profile,
        seed=result.seed,
        mode=result.colony.mode,
    )


def _row(label: str, report: RunReport, *, baseline: bool) -> ResultRow:
    return ResultRow(
        label=label,
        completion_rate_pct=report.completion_rate_pct,
        cost_usd=report.total_cost_usd,
        wall_clock_s=report.wall_clock_seconds,
        recoveries="--" if baseline else report.recoveries,
        interventions="--" if baseline else report.human_interventions,
    )

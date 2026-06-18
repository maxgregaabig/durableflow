from __future__ import annotations

from .views import ComparisonView, ScoreboardView


def render_scoreboard(view: ScoreboardView) -> str:
    events = "\n".join(f"  {event}" for event in view.recent_events[-5:])
    return (
        f"[{view.runner_label}] jobs {view.jobs_completed}/{view.jobs_total} "
        f"recovering {view.jobs_recovering} failed {view.jobs_failed} | "
        f"instances healthy {view.instances_healthy} lost {view.instances_lost} | "
        f"spend ${view.spend_usd:.2f}/${view.budget_usd:.2f} | "
        f"recoveries {view.recoveries} interventions {view.interventions}"
        + (f"\n{events}" if events else "")
    )


def render_comparison(view: ComparisonView) -> str:
    lines = [
        f"=== RESULT mode={view.mode} profile={view.chaos_profile} seed={view.seed} ===",
        "                  completion   cost     wall    recoveries  interventions",
        _render_row(view.naive_row),
        _render_row(view.colony_row),
        "",
        (
            f"completion delta: {view.completion_delta_pts:+.0f} pts"
            f"     cost delta: {view.cost_delta_usd:+.2f}"
            f"   under identical loss schedule (seed {view.seed})"
        ),
    ]
    return "\n".join(lines)


def _render_row(row) -> str:
    return (
        f"{row.label:<16} {row.completion_rate_pct:>6.0f}%"
        f"     ${row.cost_usd:>5.2f}"
        f"   {row.wall_clock_s:>5.0f}s"
        f"      {str(row.recoveries):>4}          {str(row.interventions):>4}"
    )

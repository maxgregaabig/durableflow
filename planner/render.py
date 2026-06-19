from __future__ import annotations

import json
from dataclasses import asdict

from .views import PlanTraceView


def render_plan_trace(view: PlanTraceView, *, format: str = "text") -> str:
    if format == "json":
        return json.dumps(asdict(view), sort_keys=True)
    lines = [view.headline]
    if view.confidence_note:
        lines.append(f"Confidence: {view.confidence_note}")
    if view.constraints_summary:
        lines.append("Constraints:")
        lines.extend(f"  - {item}" for item in view.constraints_summary)
    if view.chosen:
        lines.append(
            "Chosen: "
            f"{view.chosen.target_label} "
            f"(predicted ${view.chosen.predicted_cost_usd:.4f}, "
            f"p95 {view.chosen.predicted_latency_ms_p95} ms, "
            f"past success {view.chosen.past_success_rate:.0%})"
        )
    if view.escalation:
        lines.append(
            "Escalation: "
            f"{view.escalation.from_target} -> {view.escalation.to_target} "
            f"because {view.escalation.reason}."
        )
    if view.actual_vs_predicted:
        row = view.actual_vs_predicted
        lines.append(
            "Predicted vs actual: "
            f"${row.predicted_cost_usd:.4f} vs ${row.actual_cost_usd:.4f}; "
            f"{row.predicted_latency_ms_p95} ms p95 vs {row.actual_latency_ms} ms."
        )
    if view.considered:
        lines.append("Considered:")
        lines.extend(
            f"  - {row.target_label}: {row.verdict.lower()} - {row.reason}"
            for row in view.considered
        )
    if view.what_would_change:
        lines.append("What would need to change:")
        lines.extend(f"  - {item}" for item in view.what_would_change)
    return "\n".join(lines)

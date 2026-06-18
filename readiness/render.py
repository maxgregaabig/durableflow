from __future__ import annotations

from .view import ReadinessView


def render_readiness_markdown(view: ReadinessView) -> str:
    lines = [
        "# DurableFlow Agent Readiness Report",
        "",
        f"**VERDICT:** {view.verdict_line}",
    ]
    if view.primary_blocker:
        lines.extend(["", f"**Primary blocker:** {view.primary_blocker}"])
    lines.extend(
        [
            "",
            f"**Overall readiness:** naked {view.readiness_score_naked}/100, wrapped {view.readiness_score_wrapped}/100, delta {view.durability_delta:+d}",
            "",
            "| Category | Naked | Wrapped | Delta |",
            "|----------|-------|---------|-------|",
        ]
    )
    for row in view.category_rows:
        lines.append(f"| {row.label} | {row.naked}/100 | {row.wrapped}/100 | {row.delta:+d} |")
    if view.headline_metrics:
        lines.extend(["", "## What The Durability Layer Bought"])
        for metric in view.headline_metrics:
            lines.append(
                f"- {metric.label}: naked {metric.naked:g}, wrapped {metric.wrapped:g}, delta {metric.delta:+g}"
            )
    if view.detail_metrics:
        lines.extend(["", "## Detail Metrics"])
        for metric in view.detail_metrics:
            lines.append(
                f"- {metric.label}: naked {metric.naked:g}, wrapped {metric.wrapped:g}, delta {metric.delta:+g}"
            )
    lines.append("")
    return "\n".join(lines)


def render_readiness_cli(view: ReadinessView) -> None:
    print("DurableFlow Agent Readiness Report")
    print("Reference agent: support ticket triage (MiniReAct)")
    print()
    print(f"VERDICT: {view.verdict_line}")
    if view.primary_blocker:
        print(f"Blocker: {view.primary_blocker}")
    print()
    print(f"{'':24} NAKED      WRAPPED    DELTA")
    for row in view.category_rows:
        print(f"{row.label:24} {row.naked:3d} / 100  {row.wrapped:3d} / 100  {row.delta:+4d}")
    print("-" * 55)
    print(
        f"{'OVERALL READINESS':24} {view.readiness_score_naked:3d} / 100  "
        f"{view.readiness_score_wrapped:3d} / 100  {view.durability_delta:+4d}"
    )
    if view.headline_metrics:
        print()
        print("What the durability layer bought:")
        for metric in view.headline_metrics:
            print(f"  {metric.label:30} naked {metric.naked:g}   wrapped {metric.wrapped:g}")
    if view.detail_metrics:
        print()
        print("(full metric detail in readiness_report.md)")


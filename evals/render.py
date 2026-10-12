"""Markdown + CLI renderer for the eval gate report view (spec §3.5, Phase 4).

Accepts ONLY ``EvalGateReportView`` (the presentation contract). It MUST NOT
import domain DTO modules like ``evals.gate`` (SEM-EVAL-005, T-EVAL-010) — that
is enforced by a static import-scan test. Headings and primary labels avoid the
§3.6 technical-term blocklist (enforced by ``BLOCKLIST`` scan in tests).

Report section order is fixed by SEM-EVAL-001: verdict, then release blockers,
then case results, then evidence.
"""

from __future__ import annotations

from .view import EvalGateReportView

# Technical-term blocklist (spec §3.6). Forbidden in headings and primary
# labels. Kept here so the renderer and its tests share one source of truth.
BLOCKLIST: tuple[str, ...] = (
    "step_data",
    "SQLite",
    "ContextLedger",
    "telemetry dict",
    "ScoreResult",
    "raw payload",
    "UUIDv5",
    "WorkflowStore",
)


def render_eval_gate_report(view: EvalGateReportView) -> str:
    """Render an operator-facing markdown report from the view model.

    Section order (SEM-EVAL-001): verdict -> release blockers -> case results
    -> evidence -> next action.
    """
    assert_blocklist_clean(_headline_text(view))

    lines: list[str] = []
    lines.append(f"# Gate verdict: {_verdict_label(view.status)}")
    lines.append("")
    lines.append(f"**Gate:** {view.gate_name}")
    lines.append(_verdict_sentence(view))
    lines.append("")

    # Summary line in operator language.
    lines.append(
        f"- Cases: {view.summary.total_cases} total, "
        f"{view.summary.passed_cases} passed, {view.summary.failed_cases} failed"
    )
    lines.append(f"- Scorer results evaluated: {view.summary.scorer_count}")
    if view.summary.cost_delta is not None:
        lines.append(f"- Cost change vs baseline: {view.summary.cost_delta:+g}")
    if view.summary.latency_delta_ms is not None:
        lines.append(f"- Latency change vs baseline: {view.summary.latency_delta_ms:+d} ms")
    lines.append("")

    # Release blockers (spec §3.4: sort by severity, cite evidence paths).
    if view.failing_checks:
        lines.append("## Release blockers")
        lines.append("")
        for check in view.failing_checks:
            lines.append(
                f"- **{check.case_id}** failed **{_scorer_label(check.scorer_name)}**: "
                f"{check.user_facing_reason} "
                f"(threshold {check.threshold}, observed {check.observed}). "
                f"Evidence: `{check.evidence_path}`"
            )
        lines.append("")
    elif view.status == "passed":
        lines.append("## Release blockers")
        lines.append("")
        lines.append("None. No required scorer regressed.")
        lines.append("")
    else:
        lines.append("## Release blockers")
        lines.append("")
        lines.append("None yet — the gate is incomplete, not failed.")
        lines.append("")

    # Case results.
    if view.case_results:
        lines.append("## Case results")
        lines.append("")
        lines.append("| Case | Workflow | Status | Scorer results |")
        lines.append("|------|----------|--------|----------------|")
        for case in view.case_results:
            wf = case.workflow_id or "—"
            lines.append(
                f"| {case.case_id} | {wf} | {_case_status_label(case.status)} "
                f"| {case.score_summary} |"
            )
        lines.append("")

    # Evidence artifacts.
    if view.evidence:
        lines.append("## Evidence")
        lines.append("")
        for ev in view.evidence:
            lines.append(
                f"- `{ev.evidence_kind}` — `{ev.path}` (digest `{ev.digest}`, "
                f"id `{ev.evidence_id}`)"
            )
        lines.append("")

    # Next action (spec §3.4: map verdict to ship / inspect / fix).
    lines.append("## Next action")
    lines.append("")
    lines.append(f"**{_action_label(view.next_action.action_type)}:** {view.next_action.description}")
    lines.append("")
    return "\n".join(lines)


def render_cli_summary(view: EvalGateReportView) -> str:
    """One-line CLI verdict suitable for CI output (T-EVAL-008)."""
    blocker_count = len(view.failing_checks)
    return (
        f"gate={view.status} cases={view.summary.total_cases} "
        f"passed={view.summary.passed_cases} failed={view.summary.failed_cases} "
        f"blockers={blocker_count}"
    )


# ---------------------------------------------------------------------------
# Ubiquitous-language helpers (no backend terms leak past here)
# ---------------------------------------------------------------------------


def _verdict_label(status: str) -> str:
    return {"passed": "PASSED", "failed": "FAILED", "incomplete": "INCOMPLETE"}.get(status, status.upper())


def _verdict_sentence(view: EvalGateReportView) -> str:
    if view.status == "passed":
        return (
            f"All {view.summary.total_cases} case(s) passed every required scorer. "
            "The change is safe to ship."
        )
    if view.status == "failed":
        return (
            f"{len(view.failing_checks)} required scorer result(s) regressed across "
            f"{view.summary.failed_cases} case(s). Do not ship until resolved."
        )
    return "The gate could not reach a verdict. See the next action below."


def _scorer_label(name: str) -> str:
    # Turn a backend scorer name into a ubiquitous-language phrase.
    table = {
        "trace_completeness": "trace completeness",
        "context_lineage_completeness": "context fidelity",
        "approval_boundary": "safety boundary",
        "cost_threshold": "cost budget",
        "latency_threshold": "latency budget",
    }
    return table.get(name, name.replace("_", " "))


def _case_status_label(status: str) -> str:
    return {"passed": "passed", "failed": "failed", "skipped": "inconclusive"}.get(status, status)


def _action_label(action_type: str) -> str:
    return {
        "ship": "Ship",
        "inspect_failures": "Inspect failures",
        "rerun": "Rerun",
        "fix_spec": "Fix the spec",
    }.get(action_type, action_type)


# ---------------------------------------------------------------------------
# Blocklist self-check
# ---------------------------------------------------------------------------


def _headline_text(view: EvalGateReportView) -> str:
    """Concatenate the heading + primary-label text scanned by SEM-EVAL-004."""
    parts = [
        f"Gate verdict: {_verdict_label(view.status)}",
        view.gate_name,
        "Release blockers",
        "Case results",
        "Evidence",
        "Next action",
        _verdict_sentence(view),
        view.next_action.description,
    ]
    return " ".join(parts)


def assert_blocklist_clean(text: str) -> None:
    """Raise if any blocklisted term appears in ``text`` (spec §3.6)."""
    lowered = text.lower()
    for term in BLOCKLIST:
        if term.lower() in lowered:
            raise ValueError(f"blocklisted technical term in report text: {term!r}")


__all__ = [
    "BLOCKLIST",
    "assert_blocklist_clean",
    "render_cli_summary",
    "render_eval_gate_report",
]

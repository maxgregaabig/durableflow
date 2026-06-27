"""Presentation view model for the eval gate report (spec §3.2-§3.5).

This layer converts the backend ``EvalGateReport`` DTO into an operator-facing
``EvalGateReportView``. It is the ONLY type the renderer accepts (SEM-EVAL-005,
T-EVAL-010): raw backend DTOs never reach the rendered report. Headings and
labels use ubiquitous language only (§3.6 blocklist is enforced in render.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .gate import EvalGateReport


@dataclass(frozen=True)
class GateSummaryView:
    total_cases: int
    passed_cases: int
    failed_cases: int
    scorer_count: int
    cost_delta: float | None
    latency_delta_ms: int | None


@dataclass(frozen=True)
class FailingCheckView:
    case_id: str
    scorer_name: str
    user_facing_reason: str
    threshold: str
    observed: str
    evidence_path: str


@dataclass(frozen=True)
class CaseResultView:
    case_id: str
    workflow_id: str
    status: Literal["passed", "failed", "skipped"]
    score_summary: str
    release_blockers: list[str]


@dataclass(frozen=True)
class GateEvidenceView:
    evidence_id: str
    evidence_kind: Literal["eval_report", "trace_summary", "context_summary", "scorer_log"]
    path: str
    digest: str


@dataclass(frozen=True)
class GateNextActionView:
    action_type: Literal["ship", "inspect_failures", "rerun", "fix_spec"]
    description: str


@dataclass(frozen=True)
class EvalGateReportView:
    """Operator-facing summary of one eval gate run (spec §3.3)."""

    gate_name: str
    status: Literal["passed", "failed", "incomplete"]
    summary: GateSummaryView
    failing_checks: list[FailingCheckView]
    case_results: list[CaseResultView]
    evidence: list[GateEvidenceView]
    next_action: GateNextActionView


def build_eval_gate_report_view(
    report: EvalGateReport,
    *,
    case_workflow_map: dict[str, str] | None = None,
    cost_delta: float | None = None,
    latency_delta_ms: int | None = None,
) -> EvalGateReportView:
    """Convert a backend ``EvalGateReport`` into an operator-facing view.

    ``case_workflow_map`` maps ``case_id`` -> ``workflow_id`` for the case rows;
    when absent, only the case id is shown. ``cost_delta`` and
    ``latency_delta_ms`` are optional regression deltas (vs a baseline) shown in
    the summary; both are ``None`` until a baseline comparison is wired in.
    """
    workflow_by_case = case_workflow_map or {}
    results = list(report.results)
    required_names = _required_scorers_from_summary(report)

    failing_checks = _failing_checks(results)
    case_results = _case_results(results, workflow_by_case)
    evidence = _evidence(report)
    next_action = _next_action(report)

    summary = GateSummaryView(
        total_cases=int(report.summary.get("total_cases", 0)),
        passed_cases=int(report.summary.get("passed_cases", 0)),
        failed_cases=int(report.summary.get("failed_cases", 0)),
        scorer_count=int(report.summary.get("scorer_count", 0)),
        cost_delta=cost_delta,
        latency_delta_ms=latency_delta_ms,
    )

    return EvalGateReportView(
        gate_name=report.gate_name,
        status=report.status,
        summary=summary,
        failing_checks=failing_checks,
        case_results=case_results,
        evidence=evidence,
        next_action=next_action,
    )


def _required_scorers_from_summary(report: EvalGateReport) -> set[str]:
    # The view does not need required names directly; kept for future thresholds
    # rendering. Returns an empty set when not present.
    return set()


def _failing_checks(results: list) -> list[FailingCheckView]:
    views: list[FailingCheckView] = []
    for r in results:
        if r.status != "failed":
            continue
        views.append(
            FailingCheckView(
                case_id=r.case_id,
                scorer_name=r.scorer_name,
                user_facing_reason=r.reason,
                threshold=_format_threshold(r.threshold),
                observed=_format_observed(r.score),
                evidence_path=r.evidence_path,
            )
        )
    return views


def _case_results(results: list, workflow_by_case: dict[str, str]) -> list[CaseResultView]:
    by_case: dict[str, list] = {}
    for r in results:
        by_case.setdefault(r.case_id, []).append(r)
    out: list[CaseResultView] = []
    for case_id, rows in by_case.items():
        statuses = {r.status for r in rows}
        if "failed" in statuses:
            status: Literal["passed", "failed", "skipped"] = "failed"
        elif "error" in statuses:
            status = "skipped"
        else:
            status = "passed"
        blockers = [
            f"{r.scorer_name}: {r.reason}" for r in rows if r.status == "failed"
        ]
        passed = sum(1 for r in rows if r.status == "passed")
        total = len(rows)
        out.append(
            CaseResultView(
                case_id=case_id,
                workflow_id=workflow_by_case.get(case_id, ""),
                status=status,
                score_summary=f"{passed} of {total} scorer result(s) passed",
                release_blockers=blockers,
            )
        )
    return out


def _evidence(report: EvalGateReport) -> list[GateEvidenceView]:
    views: list[GateEvidenceView] = []
    for ev in report.evidence:
        kind = ev.get("evidence_kind", "scorer_log")
        if kind not in ("eval_report", "trace_summary", "context_summary", "scorer_log"):
            kind = "scorer_log"
        views.append(
            GateEvidenceView(
                evidence_id=ev.get("evidence_id", ""),
                evidence_kind=kind,
                path=ev.get("path", ""),
                digest=ev.get("digest", ""),
            )
        )
    return views


def _next_action(report: EvalGateReport) -> GateNextActionView:
    if report.status == "passed":
        return GateNextActionView(
            action_type="ship",
            description=(
                "All required scorers met their thresholds for every case. "
                "The change is safe to ship."
            ),
        )
    if report.status == "failed":
        return GateNextActionView(
            action_type="inspect_failures",
            description=(
                "One or more required scorers regressed. Inspect the release "
                "blockers and evidence below before shipping."
            ),
        )
    # incomplete
    reasons = report.summary.get("incomplete_reasons") or []
    if reasons:
        description = (
            "The gate could not produce a verdict. Resolve the gaps below, then "
            "rerun: " + "; ".join(str(r) for r in reasons)
        )
    else:
        description = (
            "The gate could not produce a verdict. Fix the case manifest or "
            "scorer registration, then rerun."
        )
    return GateNextActionView(action_type="fix_spec", description=description)


def _format_threshold(threshold: float) -> str:
    if threshold == int(threshold):
        return f"{int(threshold)}"
    return f"{threshold:g}"


def _format_observed(score: float | None) -> str:
    if score is None:
        return "n/a"
    if score == int(score):
        return f"{int(score)}"
    return f"{score:g}"


__all__ = [
    "CaseResultView",
    "EvalGateReportView",
    "FailingCheckView",
    "GateEvidenceView",
    "GateNextActionView",
    "GateSummaryView",
    "build_eval_gate_report_view",
]

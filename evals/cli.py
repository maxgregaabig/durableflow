"""Eval gate CLI: make-case | gate | render-report (spec §5, Phase 4).

CI mode exit codes (T-EVAL-008):
  - passed     -> 0
  - failed     -> 1
  - incomplete -> 2 (also used for invalid configuration)

Core machinery is stdlib-only. LangSmith export is optional and lazy-imported
only when explicitly requested (Phase 5, C-EVAL-009).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

from context.ledger import ContextLedger
from src.store import WorkflowStore

from .cases import build_eval_case_from_workflow
from .gate import EvalGateRunner
from .io import load_json, write_artifact
from .manifest import append_case_to_manifest, load_eval_manifest
from .registry import ScorerRegistry
from .render import render_cli_summary, render_eval_gate_report
from .scorers import (
    ApprovalBoundaryScorer,
    ContextLineageScorer,
    CostThresholdScorer,
    LatencyThresholdScorer,
    TraceCompletenessScorer,
)
from .view import build_eval_gate_report_view


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "make-case":
            return _cmd_make_case(args)
        if args.command == "gate":
            return _cmd_gate(args)
        if args.command == "render-report":
            return _cmd_render_report(args)
    except _CliError as exc:
        print(f"[eval-gate] {exc}", file=sys.stderr)
        return 2
    parser.print_help(sys.stderr)
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m evals.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    make = sub.add_parser("make-case", help="promote a completed workflow run into an eval case")
    make.add_argument("--db", required=True, help="workflow SQLite database path")
    make.add_argument("--workflow-id", required=True, help="completed workflow id")
    make.add_argument("--out", required=True, help="output path for the EvalCase JSON")
    make.add_argument("--manifest", default=None, help="manifest to append the case to")
    make.add_argument("--context-db", default=None, help="optional context ledger SQLite path")
    make.add_argument(
        "--telemetry-log",
        default=None,
        help="optional telemetry JSONL path (one event dict per line)",
    )

    gate = sub.add_parser("gate", help="run the eval gate over a manifest")
    gate.add_argument("--manifest", required=True, help="eval manifest path")
    gate.add_argument("--out", required=True, help="output path for the EvalGateReport JSON")
    gate.add_argument(
        "--render",
        default=None,
        help="optional markdown report output path (defaults to <out>.md)",
    )
    gate.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: exit 0/1/2 by verdict and print a one-line summary",
    )
    gate.add_argument(
        "--langsmith-export",
        action="store_true",
        help="enable optional LangSmith export (best-effort; never affects the verdict)",
    )

    render = sub.add_parser("render-report", help="render an existing report JSON as markdown")
    render.add_argument("--report", required=True, help="EvalGateReport JSON path")
    render.add_argument("--out", default="-", help="markdown output path ('-' for stdout)")
    return parser


# ---------------------------------------------------------------------------
# make-case
# ---------------------------------------------------------------------------


def _cmd_make_case(args: argparse.Namespace) -> int:
    store = WorkflowStore(args.db)
    context_ledger = ContextLedger(args.context_db) if args.context_db else None
    telemetry_events = _load_telemetry_events(args.telemetry_log) if args.telemetry_log else None
    result = build_eval_case_from_workflow(
        store,
        args.workflow_id,
        context_ledger=context_ledger,
        telemetry_events=telemetry_events,
    )
    if not result.accepted or result.case is None:
        # T-EVAL-002: no case written; user-facing reason recorded.
        print(f"[eval-gate] rejected: {result.reason}", file=sys.stderr)
        return 2
    case = result.case
    case_path, _ = write_artifact(case, args.out)
    if args.manifest:
        append_case_to_manifest(args.manifest, case_path)
        print(f"[eval-gate] appended case to manifest: {args.manifest}", file=sys.stderr)
    print(case_path)
    return 0


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------


def _cmd_gate(args: argparse.Namespace) -> int:
    manifest = load_eval_manifest(args.manifest)
    cases = _load_cases(manifest.cases)
    registry = _default_registry(manifest)
    export_hook = _maybe_export_hook(args)
    runner = EvalGateRunner(manifest, registry, export_hook=export_hook, gate_name="eval-gate")
    report = runner.run(cases)

    report_path, _ = write_artifact(report, args.out)
    # Stash the case->workflow map so the rendered view can show workflow ids.
    workflow_map = {c.case_id: c.workflow_id for c in cases}
    view = build_eval_gate_report_view(report, case_workflow_map=workflow_map)
    markdown = render_eval_gate_report(view)
    md_path = args.render or (str(args.out) + ".md")
    Path(md_path).write_text(markdown + "\n", encoding="utf-8")

    print(f"[eval-gate] report: {report_path}", file=sys.stderr)
    print(f"[eval-gate] markdown: {md_path}", file=sys.stderr)
    if args.ci:
        print(render_cli_summary(view))
        return _exit_code(report.status)
    # Non-CI: still surface blockers, but don't fail the shell.
    for blocker in report.release_blockers:
        print(f"[eval-gate] blocker: {blocker}", file=sys.stderr)
    return 0


def _exit_code(status: str) -> int:
    return {"passed": 0, "failed": 1, "incomplete": 2}.get(status, 2)


# ---------------------------------------------------------------------------
# render-report
# ---------------------------------------------------------------------------


def _cmd_render_report(args: argparse.Namespace) -> int:
    data = load_json(args.report)
    # Reconstruct the minimal view inputs from the persisted report JSON.
    status = data.get("status", "incomplete")
    if status not in ("passed", "failed", "incomplete"):
        status = "incomplete"
    view = _view_from_report_json(data, status)
    markdown = render_eval_gate_report(view)
    if args.out == "-":
        print(markdown)
    else:
        Path(args.out).write_text(markdown + "\n", encoding="utf-8")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_telemetry_events(path: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        import json

        events.append(json.loads(line))
    return events


def _load_cases(case_paths: list[str]) -> list:
    from .cases import EvalCase

    cases: list[EvalCase] = []
    for path in case_paths:
        data = load_json(path)
        cases.append(
            EvalCase(
                case_id=data["case_id"],
                workflow_id=data["workflow_id"],
                workflow_name=data.get("workflow_name", ""),
                created_at=data.get("created_at", ""),
                input_summary=data.get("input_summary", {}),
                expected=data.get("expected", {}),
                trace_summary=data.get("trace_summary", {}),
                context_summary=data.get("context_summary", {}),
                approval_summary=data.get("approval_summary", {}),
                cost_summary=data.get("cost_summary", {}),
                metadata=data.get("metadata", {}),
            )
        )
    return cases


def _default_registry(manifest) -> ScorerRegistry:
    """Register the generic platform scorers named in the manifest thresholds.

    App-specific scorers (e.g. task_success) are intentionally NOT registered
    here; a missing required app scorer correctly yields ``incomplete`` (§6.5.3).
    Cost/latency thresholds come from the manifest; defaults are conservative.
    """
    thresholds = dict(manifest.thresholds)
    scorers = [
        TraceCompletenessScorer(threshold=float(thresholds.get("trace_completeness", 1.0))),
        ContextLineageScorer(threshold=float(thresholds.get("context_lineage_completeness", 1.0))),
        ApprovalBoundaryScorer(threshold=float(thresholds.get("approval_boundary", 1.0))),
    ]
    if "cost_threshold" in thresholds:
        scorers.append(CostThresholdScorer(max_cost_usd=float(thresholds["cost_threshold"])))
    if "latency_threshold" in thresholds:
        scorers.append(LatencyThresholdScorer(max_latency_ms=float(thresholds["latency_threshold"])))
    return ScorerRegistry(scorers)


def _maybe_export_hook(args: argparse.Namespace):
    if not args.langsmith_export:
        return None
    # Lazy import: the integration stays optional. If the SDK or env is absent,
    # the hook is a no-op rather than an error (C-EVAL-009).
    try:
        from integrations.langsmith_eval_export import LangSmithEvalExportHook

        return LangSmithEvalExportHook.from_env()
    except Exception:  # noqa: BLE001 - export is best-effort and verdict-preserving
        return None


def _view_from_report_json(data: dict, status: str):
    from .view import (
        CaseResultView,
        EvalGateReportView,
        FailingCheckView,
        GateEvidenceView,
        GateNextActionView,
        GateSummaryView,
    )

    summary_data = data.get("summary", {}) or {}
    summary = GateSummaryView(
        total_cases=int(summary_data.get("total_cases", 0)),
        passed_cases=int(summary_data.get("passed_cases", 0)),
        failed_cases=int(summary_data.get("failed_cases", 0)),
        scorer_count=int(summary_data.get("scorer_count", 0)),
        cost_delta=summary_data.get("cost_delta"),
        latency_delta_ms=summary_data.get("latency_delta_ms"),
    )
    failing_checks = [
        FailingCheckView(
            case_id=r.get("case_id", ""),
            scorer_name=r.get("scorer_name", ""),
            user_facing_reason=r.get("reason", ""),
            threshold=str(r.get("threshold", "")),
            observed=str(r.get("score", "n/a")),
            evidence_path=r.get("evidence_path", ""),
        )
        for r in data.get("results", [])
        if r.get("status") == "failed"
    ]
    evidence = [
        GateEvidenceView(
            evidence_id=ev.get("evidence_id", ""),
            evidence_kind=ev.get("evidence_kind", "scorer_log"),
            path=ev.get("path", ""),
            digest=ev.get("digest", ""),
        )
        for ev in data.get("evidence", [])
    ]
    next_action = _next_action_from_status(status, summary_data.get("incomplete_reasons", []))
    return EvalGateReportView(
        gate_name=data.get("gate_name", "eval-gate"),
        status=status,
        summary=summary,
        failing_checks=failing_checks,
        case_results=[],  # render-report does not reload case rows; blockers carry detail
        evidence=evidence,
        next_action=next_action,
    )


def _next_action_from_status(status: str, incomplete_reasons: list):
    from .view import GateNextActionView

    if status == "passed":
        return GateNextActionView(
            action_type="ship",
            description="All required scorers met their thresholds for every case. The change is safe to ship.",
        )
    if status == "failed":
        return GateNextActionView(
            action_type="inspect_failures",
            description="One or more required scorers regressed. Inspect the release blockers and evidence below before shipping.",
        )
    if incomplete_reasons:
        description = (
            "The gate could not produce a verdict. Resolve the gaps below, then rerun: "
            + "; ".join(str(r) for r in incomplete_reasons)
        )
    else:
        description = "The gate could not produce a verdict. Fix the case manifest or scorer registration, then rerun."
    return GateNextActionView(action_type="fix_spec", description=description)


class _CliError(Exception):
    """Raised for user-facing CLI errors that map to exit code 2."""


if __name__ == "__main__":
    raise SystemExit(main())

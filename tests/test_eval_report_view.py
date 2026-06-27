"""Report view + renderer semantics (spec §9, Phase 4).

Covers T-EVAL-009 (pass/fail/incomplete reports map to correct next action) and
T-EVAL-010 (renderer imports no domain DTO modules; blocklist terms absent from
headings). Includes the architectural import-scan (SEM-EVAL-005).
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import get_type_hints

import pytest

from evals.gate import EvalGateReport, GateRunConfig, run_eval_gate
from evals.render import BLOCKLIST, render_eval_gate_report
from evals.view import (
    EvalGateReportView,
    build_eval_gate_report_view,
)
from tests.eval_conftest import build_report, make_fail_case, make_pass_case, pass_scorers


# ---------------------------------------------------------------------------
# T-EVAL-009: view builder maps verdicts to next actions
# ---------------------------------------------------------------------------


def test_passing_report_maps_to_ship_action(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "pass.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    view = build_eval_gate_report_view(report, case_workflow_map={case.case_id: case.workflow_id})

    assert view.status == "passed"
    assert view.next_action.action_type == "ship"
    assert view.summary.total_cases == 1
    assert view.summary.passed_cases == 1
    assert view.case_results[0].status == "passed"


def test_failing_report_maps_to_inspect_failures_action(tmp_path: Path) -> None:
    case = make_fail_case(tmp_path / "fail.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    view = build_eval_gate_report_view(report, case_workflow_map={case.case_id: case.workflow_id})

    assert view.status == "failed"
    assert view.next_action.action_type == "inspect_failures"
    assert view.failing_checks  # blockers surfaced
    assert all(c.evidence_path for c in view.failing_checks)  # SEM-EVAL-003


def test_incomplete_report_maps_to_fix_spec_action(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "inc.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "task_success"],
                          missing=["task_success"])
    view = build_eval_gate_report_view(report)

    assert view.status == "incomplete"
    assert view.next_action.action_type in ("fix_spec", "rerun")
    # Incomplete must never recommend shipping.
    assert view.next_action.action_type != "ship"


# ---------------------------------------------------------------------------
# SEM-EVAL-003: every failing check cites an evidence path
# ---------------------------------------------------------------------------


def test_every_failing_check_has_non_empty_evidence_path(tmp_path: Path) -> None:
    case = make_fail_case(tmp_path / "ev.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    view = build_eval_gate_report_view(report)
    assert view.failing_checks
    for check in view.failing_checks:
        assert check.evidence_path, f"failing check {check.scorer_name} lacks evidence path"


# ---------------------------------------------------------------------------
# SEM-EVAL-001: report section order is verdict -> blockers -> cases -> evidence
# ---------------------------------------------------------------------------


def test_rendered_report_section_order(tmp_path: Path) -> None:
    case = make_fail_case(tmp_path / "order.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    view = build_eval_gate_report_view(report, case_workflow_map={case.case_id: case.workflow_id})
    text = render_eval_gate_report(view)

    verdict_idx = text.index("Gate verdict")
    blockers_idx = text.index("## Release blockers")
    cases_idx = text.index("## Case results")
    evidence_idx = text.index("## Evidence")
    next_idx = text.index("## Next action")
    assert verdict_idx < blockers_idx < cases_idx < evidence_idx < next_idx


# ---------------------------------------------------------------------------
# SEM-EVAL-004 / T-EVAL-010: blocklist terms absent from headings + labels
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_kind", ["pass", "fail", "incomplete"])
def test_blocklist_terms_absent_from_headlines(tmp_path: Path, status_kind: str) -> None:
    if status_kind == "pass":
        case = make_pass_case(tmp_path / "bl_pass.sqlite")
        required = ["trace_completeness", "context_lineage_completeness", "approval_boundary"]
        missing = []
    elif status_kind == "fail":
        case = make_fail_case(tmp_path / "bl_fail.sqlite")
        required = ["trace_completeness", "context_lineage_completeness", "approval_boundary"]
        missing = []
    else:
        case = make_pass_case(tmp_path / "bl_inc.sqlite")
        required = ["trace_completeness", "task_success"]
        missing = ["task_success"]
    report = build_report([case], pass_scorers(), required=required, missing=missing)
    view = build_eval_gate_report_view(report)
    text = render_eval_gate_report(view)

    lowered = text.lower()
    for term in BLOCKLIST:
        assert term.lower() not in lowered, f"blocklisted term {term!r} present in report"


# ---------------------------------------------------------------------------
# T-EVAL-010 / SEM-EVAL-005: renderer accepts ONLY EvalGateReportView
# ---------------------------------------------------------------------------


def test_renderer_signature_only_accepts_view_model() -> None:
    sig = inspect.signature(render_eval_gate_report)
    params = list(sig.parameters.values())
    assert params, "renderer must take a parameter"
    # First parameter annotation must be the view model, not the domain DTO.
    annotation = params[0].annotation
    assert annotation is EvalGateReportView or (
        isinstance(annotation, str) and "EvalGateReportView" in annotation
    )


def test_render_module_does_not_import_domain_dtos() -> None:
    """SEM-EVAL-005: evals.render imports no backend DTO modules (gate/cases)."""
    import evals.render as render_mod

    source = Path(render_mod.__file__).read_text(encoding="utf-8")
    # Static check: the render module must not import gate/cases/io/redaction.
    forbidden = [
        "from evals.gate",
        "from evals.cases",
        "from .gate",
        "from .cases",
        "import evals.gate",
        "import evals.cases",
    ]
    for token in forbidden:
        assert token not in source, f"renderer imports domain DTO module: {token!r}"
    # The only permitted evals import is the view module.
    assert "from .view import" in source


def test_view_module_does_not_import_renderer() -> None:
    """View -> render would create a cycle; ensure view stays render-free."""
    import evals.view as view_mod

    source = Path(view_mod.__file__).read_text(encoding="utf-8")
    assert "from .render" not in source and "from evals.render" not in source

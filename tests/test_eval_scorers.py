"""Scorer protocol and generic platform scorers (spec §9, Phase 2).

Covers T-EVAL-004 (required scorer pass), T-EVAL-012 (scorer results carry
status/threshold/reason/evidence), and the generic-scorer invariant T-EVAL-014
(generic scorers do not require application-specific payloads).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.cases import EvalCase
from evals.registry import ScorerRegistry
from evals.scorers import (
    ApprovalBoundaryScorer,
    ContextLineageScorer,
    CostThresholdScorer,
    EvalScorer,
    LatencyThresholdScorer,
    ScoreResult,
    TraceCompletenessScorer,
)
from tests.eval_conftest import (
    make_completed_workflow,
    make_fail_case,
    make_pass_case,
)


# ---------------------------------------------------------------------------
# T-EVAL-004: required scorer pass; each scorer returns a full ScoreResult
# ---------------------------------------------------------------------------


def test_trace_completeness_passes_for_completed_workflow(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "pass.sqlite")
    result = TraceCompletenessScorer(min_steps=1).score(case)
    assert result.status == "passed"
    assert result.score == 1.0
    _assert_full_score_result(result, case.case_id, "trace_completeness")


def test_trace_completeness_fails_when_too_few_steps(tmp_path: Path) -> None:
    # Build a case whose trace_summary reports zero steps.
    case = EvalCase(
        case_id="c0", workflow_id="wf0", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 0, "step_names": []},
        context_summary={}, approval_summary={}, cost_summary={},
    )
    result = TraceCompletenessScorer(min_steps=2).score(case)
    assert result.status == "failed"
    assert result.score == 0.0
    assert "0 step" in result.reason


def test_context_lineage_scorer_passes_with_lineage(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "ctx.sqlite")
    result = ContextLineageScorer().score(case)
    assert result.status == "passed"
    assert "lineage complete" in result.reason


def test_context_lineage_scorer_neutral_when_optional_and_absent() -> None:
    case = EvalCase(
        case_id="c1", workflow_id="wf1", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={"available": False}, approval_summary={}, cost_summary={},
    )
    result = ContextLineageScorer(require_lineage=False).score(case)
    assert result.status == "passed"
    assert "neutral" in result.reason


def test_context_lineage_scorer_fails_when_required_and_absent() -> None:
    case = EvalCase(
        case_id="c2", workflow_id="wf2", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={"available": False}, approval_summary={}, cost_summary={},
    )
    result = ContextLineageScorer(require_lineage=True).score(case)
    assert result.status == "failed"
    assert "no context lineage" in result.reason


def test_context_lineage_scorer_fails_on_broken_lineage(tmp_path: Path) -> None:
    case = make_fail_case(tmp_path / "fail.sqlite")
    result = ContextLineageScorer().score(case)
    assert result.status == "failed"


def test_approval_boundary_scorer_with_approval_present_completed(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "app.sqlite")
    result = ApprovalBoundaryScorer().score(case)
    assert result.status == "passed"


def test_approval_boundary_fails_when_approval_present_but_not_completed() -> None:
    case = EvalCase(
        case_id="c3", workflow_id="wf3", workflow_name="t", created_at="now",
        input_summary={}, expected={"workflow_status": "rejected"},
        trace_summary={"step_count": 1},
        context_summary={}, approval_summary={"approval_present": True}, cost_summary={},
    )
    result = ApprovalBoundaryScorer().score(case)
    assert result.status == "failed"
    assert "rejected" in result.reason


# ---------------------------------------------------------------------------
# Budget scorers
# ---------------------------------------------------------------------------


def test_cost_threshold_passes_under_budget() -> None:
    case = EvalCase(
        case_id="c4", workflow_id="wf4", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={}, approval_summary={},
        cost_summary={"total_cost_usd": 0.002},
    )
    result = CostThresholdScorer(max_cost_usd=0.01).score(case)
    assert result.status == "passed"
    assert "within budget" in result.reason


def test_cost_threshold_fails_over_budget() -> None:
    case = EvalCase(
        case_id="c5", workflow_id="wf5", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={}, approval_summary={},
        cost_summary={"total_cost_usd": 0.5},
    )
    result = CostThresholdScorer(max_cost_usd=0.01).score(case)
    assert result.status == "failed"
    assert "exceeds budget" in result.reason


def test_latency_threshold_fails_over_budget() -> None:
    case = EvalCase(
        case_id="c6", workflow_id="wf6", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={}, approval_summary={},
        cost_summary={"total_latency_ms": 5000.0},
    )
    result = LatencyThresholdScorer(max_latency_ms=1000).score(case)
    assert result.status == "failed"


# ---------------------------------------------------------------------------
# T-EVAL-014: generic scorers need no application payload + protocol shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scorer",
    [
        TraceCompletenessScorer(),
        ContextLineageScorer(),
        ApprovalBoundaryScorer(),
        CostThresholdScorer(max_cost_usd=1.0),
        LatencyThresholdScorer(max_latency_ms=1000),
    ],
)
def test_every_generic_scorer_satisfies_protocol_and_needs_no_app_payload(scorer) -> None:
    assert isinstance(scorer, EvalScorer)
    assert isinstance(scorer.name, str) and scorer.name
    # Every generic scorer must score a minimal case without app-specific fields.
    minimal = EvalCase(
        case_id="c-min", workflow_id="wf-min", workflow_name="t", created_at="now",
        input_summary={}, expected={}, trace_summary={"step_count": 1},
        context_summary={}, approval_summary={}, cost_summary={},
    )
    result = scorer.score(minimal)
    _assert_full_score_result(result, "c-min", scorer.name)


def _assert_full_score_result(result: ScoreResult, case_id: str, scorer_name: str) -> None:
    assert isinstance(result, ScoreResult)
    assert result.case_id == case_id
    assert result.scorer_name == scorer_name
    assert result.status in ("passed", "failed", "skipped", "error")
    assert isinstance(result.threshold, float)
    assert isinstance(result.reason, str) and result.reason
    assert result.evidence_path.startswith("artifacts/eval-gate/scorer-logs/")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_resolves_registered_scorers() -> None:
    a = TraceCompletenessScorer()
    b = ContextLineageScorer()
    reg = ScorerRegistry([a, b])
    res = reg.resolve(["trace_completeness", "context_lineage_completeness"])
    assert {s.name for s in res.scorers} == {"trace_completeness", "context_lineage_completeness"}
    assert res.missing == []


def test_registry_reports_missing_scorers() -> None:
    reg = ScorerRegistry([TraceCompletenessScorer()])
    res = reg.resolve(["trace_completeness", "task_success"])
    assert res.missing == ["task_success"]


def test_registry_rejects_anonymous_scorer() -> None:
    class _NoName:
        name = ""  # type: ignore[assignment]
        def score(self, case): ...  # noqa: E704
    with pytest.raises(ValueError):
        ScorerRegistry().register(_NoName())  # type: ignore[arg-type]

"""Manifest validation and gate aggregation (spec §9, Phase 3).

Covers T-EVAL-003 (manifest validation), T-EVAL-005 (required scorer failure
blocks gate), T-EVAL-006 (missing required scorer -> incomplete),
T-EVAL-007 (scorer error handling), T-EVAL-012 (evidence digests).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.cases import EvalCase
from evals.gate import (
    EvalGateRunner,
    aggregate_score_results,
    run_eval_gate,
)
from evals.io import write_artifact
from evals.manifest import EvalManifest, new_manifest, validate_for_gate
from evals.registry import ScorerRegistry
from evals.scorers import (
    ContextLineageScorer,
    CostThresholdScorer,
    ScoreResult,
    TraceCompletenessScorer,
)
from tests.eval_conftest import (
    build_report,
    make_completed_workflow,
    make_fail_case,
    make_pass_case,
    pass_manifest,
    pass_scorers,
)


# ---------------------------------------------------------------------------
# T-EVAL-003: manifest validation (zero cases / zero required scorers)
# ---------------------------------------------------------------------------


def test_zero_case_manifest_cannot_pass() -> None:
    manifest = new_manifest(required_scorers=["trace_completeness"])
    validation = validate_for_gate(manifest)
    assert validation.ok is False
    assert any("no eval cases" in r for r in validation.reasons)


def test_zero_required_scorer_manifest_cannot_pass() -> None:
    manifest = EvalManifest(manifest_id="m", version=1, cases=["c.json"], required_scorers=[])
    validation = validate_for_gate(manifest)
    assert validation.ok is False
    assert any("no required scorers" in r for r in validation.reasons)


def test_runner_returns_incomplete_for_invalid_manifest(tmp_path: Path) -> None:
    manifest = new_manifest(required_scorers=[])  # no required scorers
    cases = [make_pass_case(tmp_path / "c.sqlite")]
    runner = EvalGateRunner(manifest, ScorerRegistry(pass_scorers()))
    report = runner.run(cases)
    assert report.status == "incomplete"
    assert report.summary["incomplete_reasons"]


# ---------------------------------------------------------------------------
# T-EVAL-004 (required scorer pass) + aggregation unit tests
# ---------------------------------------------------------------------------


def _flat_result(case_id: str, scorer: str, status: str, *, threshold: float = 1.0, score: float | None = 1.0) -> ScoreResult:
    return ScoreResult(
        case_id=case_id, scorer_name=scorer, score=score, threshold=threshold,
        status=status, reason="r", evidence_path=f"artifacts/eval-gate/{case_id}/{scorer}.json",
    )


def test_aggregate_passes_when_all_required_scorers_pass() -> None:
    results = [
        _flat_result("c1", "trace_completeness", "passed"),
        _flat_result("c1", "context_lineage_completeness", "passed"),
    ]
    agg = aggregate_score_results(
        results,
        required_scorers=["trace_completeness", "context_lineage_completeness"],
        missing_scorers=[],
        case_count=1,
    )
    assert agg.status == "passed"
    assert agg.release_blockers == []


def test_aggregate_passes_with_optional_scorer_failure() -> None:
    results = [
        _flat_result("c1", "trace_completeness", "passed"),
        _flat_result("c1", "optional_thing", "failed"),  # not required -> warning
    ]
    agg = aggregate_score_results(
        results, required_scorers=["trace_completeness"], missing_scorers=[], case_count=1
    )
    assert agg.status == "passed"
    # Optional failures do not become release blockers.
    assert agg.release_blockers == []


# ---------------------------------------------------------------------------
# T-EVAL-005: required scorer failure blocks gate
# ---------------------------------------------------------------------------


def test_required_scorer_failure_blocks_gate_and_becomes_blocker() -> None:
    results = [
        _flat_result("c1", "trace_completeness", "passed"),
        _flat_result("c1", "context_lineage_completeness", "failed", score=0.0),
    ]
    agg = aggregate_score_results(
        results,
        required_scorers=["trace_completeness", "context_lineage_completeness"],
        missing_scorers=[],
        case_count=1,
    )
    assert agg.status == "failed"
    assert any("context_lineage_completeness" in b for b in agg.release_blockers)


def test_end_to_end_failed_gate(tmp_path: Path) -> None:
    fail_case = make_fail_case(tmp_path / "fail.sqlite")
    report = build_report(
        [fail_case],
        [TraceCompletenessScorer(), ContextLineageScorer()],
        required=["trace_completeness", "context_lineage_completeness"],
    )
    assert report.status == "failed"
    assert any("context_lineage_completeness" in b for b in report.release_blockers)
    assert report.evidence  # failing checks produce evidence rows


# ---------------------------------------------------------------------------
# T-EVAL-006: missing required scorer -> incomplete
# ---------------------------------------------------------------------------


def test_missing_required_scorer_makes_gate_incomplete() -> None:
    results = [_flat_result("c1", "trace_completeness", "passed")]
    agg = aggregate_score_results(
        results,
        required_scorers=["trace_completeness", "task_success"],  # task_success missing
        missing_scorers=["task_success"],
        case_count=1,
    )
    assert agg.status == "incomplete"
    assert any("task_success" in r for r in agg.incomplete_reasons)


def test_runner_incomplete_when_required_scorer_unregistered(tmp_path: Path) -> None:
    manifest = new_manifest(required_scorers=["trace_completeness", "task_success"])
    registry = ScorerRegistry([TraceCompletenessScorer()])  # task_success not registered
    runner = EvalGateRunner(manifest, registry)
    report = runner.run([make_pass_case(tmp_path / "c.sqlite")])
    assert report.status == "incomplete"
    assert any("task_success" in r for r in report.summary["incomplete_reasons"])


# ---------------------------------------------------------------------------
# T-EVAL-007: scorer error handling -> incomplete unless a failure blocks
# ---------------------------------------------------------------------------


class _BoomScorer:
    name = "boom_scorer"

    def score(self, case: EvalCase) -> ScoreResult:
        raise RuntimeError("boom")


def test_scorer_exception_becomes_error_result_and_incomplete_gate(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "err.sqlite")
    report = build_report(
        [case], [_BoomScorer()], required=["boom_scorer"],
    )
    assert report.status == "incomplete"
    assert report.results[0].status == "error"
    assert "boom" in report.results[0].reason


def test_required_failure_dominates_scorer_error(tmp_path: Path) -> None:
    """§6.5 rule 2: error -> incomplete, unless a failure already blocks."""
    case = make_pass_case(tmp_path / "err2.sqlite")
    fail_scorer = ContextLineageScorer(threshold=1.0)
    # fail_case lineage is broken so context scorer fails; boom errors too.
    fail_case = make_fail_case(tmp_path / "fail2.sqlite")
    report = build_report(
        [fail_case], [ContextLineageScorer(), _BoomScorer()],
        required=["context_lineage_completeness", "boom_scorer"],
    )
    assert report.status == "failed"  # failure dominates the error


def test_scorer_returning_non_score_result_becomes_error(tmp_path: Path) -> None:
    class _BadScorer:
        name = "bad_scorer"
        def score(self, case):  # type: ignore[no-untyped-def]
            return {"not": "a score result"}

    case = make_pass_case(tmp_path / "bad.sqlite")
    report = build_report([case], [_BadScorer()], required=["bad_scorer"])
    assert report.status == "incomplete"
    assert report.results[0].status == "error"


# ---------------------------------------------------------------------------
# T-EVAL-012: evidence artifact digests
# ---------------------------------------------------------------------------


def test_report_evidence_has_path_and_digest_for_each_failing_check(tmp_path: Path) -> None:
    fail_case = make_fail_case(tmp_path / "ev.sqlite")
    report = build_report(
        [fail_case], [ContextLineageScorer()], required=["context_lineage_completeness"],
    )
    assert report.status == "failed"
    assert report.evidence, "expected at least one evidence row"
    for ev in report.evidence:
        assert ev["path"], "evidence path must be non-empty"
        assert ev["digest"].startswith("sha256:"), "evidence digest must be sha256-prefixed"
        assert ev["evidence_kind"] == "scorer_log"


def test_evidence_digest_is_deterministic_for_same_failure(tmp_path: Path) -> None:
    from evals.gate import GateRunConfig
    case = make_fail_case(tmp_path / "det.sqlite")
    r1 = run_eval_gate([case], [ContextLineageScorer()],
                       GateRunConfig(required_scorers=["context_lineage_completeness"], missing_scorers=[]))
    r2 = run_eval_gate([case], [ContextLineageScorer()],
                       GateRunConfig(required_scorers=["context_lineage_completeness"], missing_scorers=[]))
    assert r1.evidence[0]["digest"] == r2.evidence[0]["digest"]


def test_full_passing_gate_run_end_to_end(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "full.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    assert report.status == "passed"
    assert report.release_blockers == []
    assert report.export_status == "not_configured"

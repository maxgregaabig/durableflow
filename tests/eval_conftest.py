"""Shared fixtures for eval gate tests (spec §10.1 test modules).

Builds deterministic DurableFlow workflow + context-ledger state and promotes
it into ``EvalCase`` artifacts for pass / fail / incomplete gate scenarios. No
network, no optional dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from context.ledger import ContextLedger
from src.store import StepResult, WorkflowStatus, WorkflowStore

from evals.cases import build_eval_case_from_workflow
from evals.gate import EvalGateReport, GateRunConfig, run_eval_gate
from evals.manifest import EvalManifest, new_manifest, save_eval_manifest
from evals.scorers import (
    ApprovalBoundaryScorer,
    ContextLineageScorer,
    CostThresholdScorer,
    LatencyThresholdScorer,
    ScoreResult,
    TraceCompletenessScorer,
)


def make_completed_workflow(
    db_path: Path,
    *,
    workflow_id: str = "wf-pass-001",
    workflow_type: str = "inbox_triage",
    step_count: int = 3,
    cost_usd: float = 0.001,
    latency_ms: float = 100.0,
    with_approval: bool = True,
    seed_context: bool = True,
) -> tuple[WorkflowStore, str]:
    """Create a store + completed workflow with step results + optional ledger."""
    store = WorkflowStore(db_path)
    state = store.create_workflow(workflow_type, workflow_id=workflow_id)
    for i in range(step_count):
        name = f"step_{i}"
        if with_approval and i == step_count - 1:
            name = "approval_gate"
        store.save_checkpoint(
            state.workflow_id,
            i,
            StepResult(
                name,
                {"result": f"output-{i}"},
                duration_ms=latency_ms / step_count,
                cost_usd=cost_usd / step_count,
                model_used="mock-primary",
            ),
        )
    store.update_status(state.workflow_id, WorkflowStatus.COMPLETED)

    if seed_context:
        ledger = ContextLedger.from_store(store)
        artifact = ledger.record_artifact(
            state.workflow_id,
            "source_artifact",
            "email-042",
            "email",
            "content",
            "mock_emails:email-042",
            8,
        )
        ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "observed")
        ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "retrieved",
                            metadata={"retrieval_method": "tfidf"})
        ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "selected")
        ledger.record_event(state.workflow_id, "step_0", artifact.artifact_id, "consumed")
        decision = ledger.record_decision(
            state.workflow_id, "step_0", None, "prompt-text", "response-text",
            "mock-primary", 12, 4, cost_usd,
        )
        ledger.record_lineage(
            decision.decision_id, artifact.artifact_id, "explicit_model_attribution", 1.0
        )
    return store, state.workflow_id


def make_incomplete_workflow(db_path: Path, *, workflow_id: str = "wf-incomplete") -> WorkflowStore:
    store = WorkflowStore(db_path)
    store.create_workflow("inbox_triage", workflow_id=workflow_id)
    # Status left as PENDING -> not COMPLETED.
    return store


def make_pass_case(db_path: Path, *, workflow_id: str = "wf-pass-001"):
    store, wid = make_completed_workflow(db_path, workflow_id=workflow_id)
    result = build_eval_case_from_workflow(
        store, wid, context_ledger=ContextLedger.from_store(store)
    )
    assert result.accepted and result.case is not None
    return result.case


def make_fail_case(db_path: Path, *, workflow_id: str = "wf-fail-001"):
    """A completed workflow whose context lineage is broken (no consumed)."""
    store = WorkflowStore(db_path)
    state = store.create_workflow("inbox_triage", workflow_id=workflow_id)
    store.save_checkpoint(state.workflow_id, 0, StepResult("step_0", {"ok": True}, 50.0, 0.001, "mock-primary"))
    store.save_checkpoint(state.workflow_id, 1, StepResult("step_1", {"ok": True}, 50.0, 0.001, "mock-primary"))
    store.update_status(state.workflow_id, WorkflowStatus.COMPLETED)
    # Ledger exists but has NO consumed / influential lineage -> context scorer fails.
    ledger = ContextLedger.from_store(store)
    ledger.record_artifact(state.workflow_id, "source_artifact", "src-1", "email", "x", None, 4)
    return build_eval_case_from_workflow(store, workflow_id, context_ledger=ledger).case


def pass_scorers() -> list:
    return [
        TraceCompletenessScorer(threshold=1.0),
        ContextLineageScorer(threshold=1.0),
        ApprovalBoundaryScorer(threshold=1.0),
    ]


def pass_manifest(tmp_path: Path, *, thresholds: dict[str, float] | None = None) -> EvalManifest:
    manifest = new_manifest(
        required_scorers=[
            "trace_completeness",
            "context_lineage_completeness",
            "approval_boundary",
        ],
        thresholds=thresholds
        or {
            "trace_completeness": 1.0,
            "context_lineage_completeness": 1.0,
            "approval_boundary": 1.0,
        },
    )
    path = tmp_path / "manifest.json"
    save_eval_manifest(manifest, path)
    return load_manifest(path)


def load_manifest(path: Path) -> EvalManifest:
    from evals.manifest import load_eval_manifest

    return load_eval_manifest(path)


def build_report(cases: list, scorers: list, *, required: list[str], missing: list[str] | None = None) -> EvalGateReport:
    config = GateRunConfig(required_scorers=required, missing_scorers=missing or [])
    return run_eval_gate(cases, scorers, config)


def write_case_fixture(case, fixtures_dir: Path) -> Path:
    from evals.io import write_artifact

    cases_dir = fixtures_dir / "cases"
    path, _ = write_artifact(case, cases_dir / f"{case.case_id}.json")
    return Path(path)


def write_report_fixture(report: EvalGateReport, fixtures_dir: Path) -> Path:
    from evals.io import write_artifact

    reports_dir = fixtures_dir / "reports"
    path, _ = write_artifact(report, reports_dir / f"{report.report_id}.json")
    return Path(path)

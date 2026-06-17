from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


ROOT = Path(__file__).resolve().parents[1]


def build_runtime(tmp_path: Path) -> tuple[WorkflowStore, ApprovalGate, WorkflowEngine, TelemetryLogger]:
    store = WorkflowStore(tmp_path / "integration.sqlite")
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    telemetry = TelemetryLogger(echo=False)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    return store, approval, engine, telemetry


def test_t_int_001_full_golden_path_with_mock_providers(tmp_path: Path) -> None:
    store, approval, engine, telemetry = build_runtime(tmp_path)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL

    approval.approve(approval.list_pending()[0].gate_id, decided_by="test")
    state = engine.resume(state.workflow_id)

    assert state.status == WorkflowStatus.COMPLETED
    assert {row["step_name"] for row in store.step_results(state.workflow_id)} == {
        "ingest_email",
        "select_context",
        "triage_llm",
        "draft_reply",
        "approval_gate",
        "send_reply",
    }
    assert len([event for event in telemetry.events if event["workflow_id"] == state.workflow_id]) >= 6


def test_t_int_002_crash_recovery_demo_runs_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "examples" / "crash_resume_demo.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "simulated process crash" in result.stdout
    assert "resuming wf-001 from step: triage_llm" in result.stdout
    assert "workflow wf-001 complete" in result.stdout


def test_t_int_003_approval_rejection_end_to_end(tmp_path: Path) -> None:
    store, approval, engine, _telemetry = build_runtime(tmp_path)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    approval.reject(approval.list_pending()[0].gate_id, "not approved", decided_by="test")
    state = engine.resume(state.workflow_id)

    assert state.status == WorkflowStatus.REJECTED
    assert store.side_effect_count(state.workflow_id, "send_reply") == 0

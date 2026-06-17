from __future__ import annotations

from pathlib import Path

from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


def runtime(tmp_path: Path) -> tuple[WorkflowStore, ApprovalGate, WorkflowEngine]:
    store = WorkflowStore(tmp_path / "runtime.sqlite")
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), workflow.dependencies())
    workflow.register(engine)
    return store, approval, engine


def test_workflow_pauses_at_approval_gate(tmp_path: Path) -> None:
    store, approval, engine = runtime(tmp_path)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL
    assert len(approval.list_pending()) == 1


def test_operator_approves_and_workflow_completes(tmp_path: Path) -> None:
    store, approval, engine = runtime(tmp_path)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    approval.approve(approval.list_pending()[0].gate_id)
    state = engine.resume(state.workflow_id)
    assert state.status == WorkflowStatus.COMPLETED
    assert store.side_effect_count(state.workflow_id, "send_reply") == 1


def test_operator_rejects_and_send_does_not_execute(tmp_path: Path) -> None:
    store, approval, engine = runtime(tmp_path)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    approval.reject(approval.list_pending()[0].gate_id, "not ready")
    state = engine.resume(state.workflow_id)
    assert state.status == WorkflowStatus.REJECTED
    assert store.side_effect_count(state.workflow_id, "send_reply") == 0


def test_approval_persists_across_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.sqlite"
    store = WorkflowStore(db_path)
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage")
    engine.execute(state.workflow_id)

    restarted_store = WorkflowStore(db_path)
    restarted_approval = ApprovalGate(restarted_store)
    pending = restarted_approval.list_pending()
    assert len(pending) == 1
    assert pending[0].workflow_id == state.workflow_id


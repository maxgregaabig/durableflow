from __future__ import annotations

from pathlib import Path

from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.model_router import ModelProvider, RoutingPolicy
from src.store import StepResult, WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


def test_resume_starts_after_last_checkpoint(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "resume.sqlite")
    calls: list[str] = []
    state = store.create_workflow("test")

    def step(name: str):
        def fn(state, step_data, dependencies):
            calls.append(name)
            return StepResult(name, {"ok": True}, 1.0)

        return fn

    engine = WorkflowEngine(store, TelemetryLogger(echo=False))
    engine.register_step("one", step("one"))
    engine.register_step("two", step("two"))
    store.save_checkpoint(state.workflow_id, 0, StepResult("one", {"ok": True}, 1.0))

    engine.resume(state.workflow_id)
    assert calls == ["two"]


def test_crashed_running_workflow_is_detected(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "crash.sqlite")
    state = store.create_workflow("test")
    store.save_checkpoint(state.workflow_id, 1, StepResult("select_context", {}, 1.0))
    store.mark_stale_for_demo(state.workflow_id, seconds_old=120)
    engine = WorkflowEngine(store, TelemetryLogger(echo=False))
    crashed = engine.recover_crashed(stale_after_seconds=30)
    assert [entry.workflow_id for entry in crashed] == [state.workflow_id]
    assert store.load_workflow(state.workflow_id).status == WorkflowStatus.CRASHED


def test_completed_workflow_is_not_reexecuted(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "completed.sqlite")
    state = store.create_workflow("test")
    store.update_status(state.workflow_id, WorkflowStatus.COMPLETED)
    calls: list[str] = []
    engine = WorkflowEngine(store, TelemetryLogger(echo=False))
    engine.register_step("one", lambda state, data, deps: calls.append("one"))
    engine.resume(state.workflow_id)
    assert calls == []


def test_idempotent_send_skips_duplicate_side_effect(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "idempotent.sqlite")
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage")
    state = engine.execute(state.workflow_id)
    approval.approve(approval.list_pending()[0].gate_id)
    state = engine.resume(state.workflow_id)

    before = store.side_effect_count(state.workflow_id, "send_reply")
    result = workflow.send_reply(state, state.step_data, workflow.dependencies())
    after = store.side_effect_count(state.workflow_id, "send_reply")
    assert before == after == 1
    assert result.output["idempotent_skip"] is True


def test_informational_message_does_not_send_side_effect(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "informational.sqlite")
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage", initial_data={"email_id": "email-050"})
    state = engine.execute(state.workflow_id)

    assert state.status == WorkflowStatus.COMPLETED
    assert store.side_effect_count(state.workflow_id, "send_reply") == 0
    send = store.step_results(state.workflow_id)[-1]
    assert send["step_name"] == "send_reply"
    assert send["output"]["skipped"] is True


def test_fallback_telemetry_is_recorded(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "fallback.sqlite")
    approval = ApprovalGate(store)
    telemetry = TelemetryLogger(echo=False)
    workflow = InboxTriageWorkflow(
        store,
        approval_gate=approval,
        policy=RoutingPolicy(
            [
                ModelProvider("primary", "p", 0.01, 0.02, fail=True),
                ModelProvider("secondary", "s", 0.01, 0.02),
            ]
        ),
    )
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage")
    engine.execute(state.workflow_id)

    summary = telemetry.summarize_workflow(state.workflow_id)
    assert summary["fallback_count"] >= 1


def test_timeout_fallback_telemetry_is_recorded(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "timeout-fallback.sqlite")
    approval = ApprovalGate(store)
    telemetry = TelemetryLogger(echo=False)
    workflow = InboxTriageWorkflow(
        store,
        approval_gate=approval,
        policy=RoutingPolicy(
            [
                ModelProvider(
                    "primary",
                    "p",
                    0.01,
                    0.02,
                    timeout_seconds=0.001,
                    mock_delay_seconds=0.01,
                ),
                ModelProvider("secondary", "s", 0.01, 0.02),
            ]
        ),
    )
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage")
    engine.execute(state.workflow_id)

    fallback_events = [
        event
        for event in telemetry.events
        if event["event_type"] == "model_fallback"
        and event["workflow_id"] == state.workflow_id
    ]
    assert fallback_events
    assert "timed out" in fallback_events[0]["metadata"]["error"]

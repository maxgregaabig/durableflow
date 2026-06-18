from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

from src.approval import ApprovalGate
from src.engine import ApprovalRejectionPolicy, PauseForApproval, WorkflowEngine, WorkflowStep
from src.store import StepResult, WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger


def test_register_steps_accepts_workflow_step_objects(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "steps.sqlite")
    state = store.create_workflow("test")
    calls: list[str] = []
    engine = WorkflowEngine(store, TelemetryLogger(echo=False))

    def step(name: str):
        def fn(_state, _step_data, _dependencies):
            calls.append(name)
            return StepResult(name, {"ok": True}, 1.0)

        return fn

    engine.register_steps(
        [
            WorkflowStep("one", step("one")),
            WorkflowStep("two", step("two")),
        ]
    )

    state = engine.execute(state.workflow_id)

    assert state.status == WorkflowStatus.COMPLETED
    assert calls == ["one", "two"]


def test_rejected_approval_can_continue_for_extension_steps(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "approval-continue.sqlite")
    approval = ApprovalGate(store)
    dependencies = {
        "approval_gate": approval,
        "approval_rejection_policies": {
            "agent_write": ApprovalRejectionPolicy.CONTINUE,
        },
    }
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), dependencies)
    state = store.create_workflow("agent")
    calls: list[str] = []

    def agent_write(state, _step_data, _dependencies):
        gate_id = approval.request_approval(
            state.workflow_id,
            "agent_write",
            {"tool_name": "update_ticket"},
        )
        return PauseForApproval(gate_id, "agent_write", {"tool_name": "update_ticket"})

    def observe_denial(_state, step_data, _dependencies):
        calls.append("continued")
        assert step_data["agent_write"]["approved"] is False
        return StepResult("observe_denial", {"observed": "write denied by operator"}, 1.0)

    engine.register_steps(
        [
            ("agent_write", agent_write),
            ("observe_denial", observe_denial),
        ]
    )

    state = engine.execute(state.workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL

    approval.reject(approval.list_pending()[0].gate_id, "policy denied")
    state = engine.resume(state.workflow_id)

    assert state.status == WorkflowStatus.COMPLETED
    assert calls == ["continued"]


def test_generic_telemetry_event_is_json() -> None:
    stream = StringIO()
    telemetry = TelemetryLogger(stream=stream, echo=True)

    telemetry.log_event(
        "tool_timeout",
        "wf",
        "agent_turn_0",
        duration_ms=100.0,
        metadata={"tool_name": "lookup_kb"},
    )

    event = json.loads(stream.getvalue())
    assert event["event_type"] == "tool_timeout"
    assert event["step_name"] == "agent_turn_0"
    assert event["metadata"]["tool_name"] == "lookup_kb"

from __future__ import annotations

import sqlite3
import pytest

from context import ContextLedger
from context.audit_view import build_context_audit_view, render_context_audit
from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


def test_ctx_led_001_artifact_registration_reuses_duplicate(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    first = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "hello",
        "mock_emails:email-042",
        1,
        {"unused": "first"},
    )
    second = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "hello",
        "mock_emails:email-042",
        1,
        {"unused": "second"},
    )

    assert second.artifact_id == first.artifact_id


def test_ctx_led_002_event_append_and_duplicate_lifecycle_idempotency(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)
    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "content",
        "mock_emails:email-042",
        4,
    )

    selected = ledger.record_event(
        state.workflow_id,
        "select_context",
        artifact.artifact_id,
        "selected",
    )
    duplicate = ledger.record_event(
        state.workflow_id,
        "select_context",
        artifact.artifact_id,
        "selected",
    )
    consumed = ledger.record_event(state.workflow_id, "triage_llm", artifact.artifact_id, "consumed")

    assert duplicate.event_id == selected.event_id
    assert consumed.event_id != selected.event_id
    assert [event.event_type for event in ledger.audit_workflow(state.workflow_id).events] == [
        "selected",
        "consumed",
    ]


def test_ctx_led_003_validation_and_privacy(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    try:
        ledger.record_artifact(state.workflow_id, "raw_content", "x", "email", "secret", None, 1)
    except ValueError as exc:
        assert "artifact_role" in str(exc)
    else:
        raise AssertionError("invalid artifact role was accepted")

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-001",
        "incoming_email",
        "sensitive raw body",
        "mock_emails:email-001",
        3,
    )
    for event_args in [
        (state.workflow_id, "step", artifact.artifact_id, "decision_recorded"),
        (state.workflow_id, "step", None, "selected"),
    ]:
        try:
            ledger.record_event(*event_args)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid event was accepted: {event_args}")

    with sqlite3.connect(store.db_path) as conn:
        row = conn.execute(
            "SELECT * FROM context_artifacts WHERE artifact_id = ?",
            (artifact.artifact_id,),
        ).fetchone()
    assert "sensitive raw body" not in str(tuple(row))


def test_ctx_decision_and_lineage_rules(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)
    source = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "content",
        "mock_emails:email-042",
        4,
    )
    prompt = ledger.record_artifact(
        state.workflow_id,
        "prompt_artifact",
        "triage_llm:prompt",
        "prompt",
        "prompt",
        "workflow:wf:prompt",
        4,
    )
    ledger.record_event(state.workflow_id, "triage_llm", source.artifact_id, "consumed")
    ledger.record_event(state.workflow_id, "triage_llm", prompt.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        '{"influential_artifact_ids": ["x"]}',
        "mock-fast",
        10,
        3,
        0.01,
    )
    assert decision.prompt_digest != "prompt"
    assert decision.response_digest != '{"influential_artifact_ids": ["x"]}'
    assert decision.input_tokens == 10
    assert decision.output_tokens == 3
    assert decision.cost_usd == 0.01

    lineage = ledger.record_lineage(
        decision.decision_id,
        source.artifact_id,
        "explicit_model_attribution",
        1.0,
        "model_response:digest:influential_artifact_ids",
    )
    assert lineage.artifact_id == source.artifact_id
    try:
        ledger.record_lineage(
            decision.decision_id,
            prompt.artifact_id,
            "explicit_model_attribution",
            1.0,
        )
    except ValueError as exc:
        assert "source_artifact" in str(exc)
    else:
        raise AssertionError("prompt lineage was accepted")


def test_decision_recorded_system_event_is_idempotent(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    first = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        "response",
        "mock-fast",
        10,
        3,
        0.01,
    )
    second = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        "response",
        "mock-fast",
        10,
        3,
        0.01,
    )

    decision_events = [
        event
        for event in ledger.audit_workflow(state.workflow_id).events
        if event.event_type == "decision_recorded"
    ]
    assert second.decision_id == first.decision_id
    assert len(decision_events) == 1


def test_ctx_int_inbox_records_context_and_audit(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "inbox.sqlite")
    approval = ApprovalGate(store)
    ledger = ContextLedger.from_store(store)
    telemetry = TelemetryLogger(echo=False)
    workflow = InboxTriageWorkflow(store, approval_gate=approval, context_ledger=ledger)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    state = store.create_workflow("inbox_triage")

    state = engine.execute(state.workflow_id)
    approval.approve(approval.list_pending()[0].gate_id, decided_by="test")
    state = engine.resume(state.workflow_id)

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.selected_count > 0
    assert audit.consumed_count > 0
    assert audit.decision_count == 2
    assert audit.influential_count > 0
    assert all(decision.step_result_id is not None for decision in audit.decisions)
    assert {
        lineage.influence_type for lineage in audit.lineage
    } == {"deterministic_fixture_attribution"}
    assert any(event["event_type"] == "context_lineage_recorded" for event in telemetry.events)

    rendered = render_context_audit(build_context_audit_view(audit))
    assert "Context Audit Trace" in rendered
    assert "v0.1 audit boundary:" in rendered
    assert "context_artifacts" not in rendered
    assert "Q3 board deck" not in rendered


def test_ctx_res_001_engine_resume_after_select_context_failure_does_not_duplicate_selected_events(
    tmp_path,
) -> None:
    store = WorkflowStore(tmp_path / "resume.sqlite")
    ledger = ContextLedger.from_store(store)
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval, context_ledger=ledger)
    telemetry = TelemetryLogger(echo=False)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    original_select_context = workflow.select_context
    failed_once = False

    def crash_after_select_context(state, step_data, dependencies):
        nonlocal failed_once
        result = original_select_context(state, step_data, dependencies)
        if not failed_once:
            failed_once = True
            raise RuntimeError("simulated crash after context selection")
        return result

    engine.replace_step("select_context", crash_after_select_context)
    state = store.create_workflow("inbox_triage")
    try:
        engine.execute(state.workflow_id)
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
    else:
        raise AssertionError("simulated crash did not fire")
    state = engine.resume(state.workflow_id)

    audit = ledger.audit_workflow(state.workflow_id)
    selected_events = [event for event in audit.events if event.event_type == "selected"]
    assert len(selected_events) == len({event.artifact_id for event in selected_events})
    assert state.current_step >= 2


def test_ctx_led_assembly_001_retrieved_event_valid_metadata(tmp_path) -> None:
    """retrieved event with valid metadata is accepted."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    event = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 0.82, "rank_position": 4},
    )
    assert event.event_type == "retrieved"
    assert event.metadata["retrieval_method"] == "bm25"


def test_ctx_led_assembly_002_retrieved_event_missing_required_key(tmp_path) -> None:
    """retrieved event without retrieval_method is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata missing required keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_score": 0.82},
        )


def test_ctx_led_assembly_003_retrieved_event_empty_string_rejected(tmp_path) -> None:
    """retrieved event with empty retrieval_method is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="failed type validation"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": ""},
        )


def test_ctx_led_assembly_004_retrieved_event_unknown_key_rejected(tmp_path) -> None:
    """retrieved event with unknown key is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata contains unknown keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25", "unknown_field": "value"},
        )

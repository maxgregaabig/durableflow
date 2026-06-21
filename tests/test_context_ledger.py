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


def test_ctx_led_assembly_005_retrieved_event_invalid_rank_position(tmp_path) -> None:
    """retrieved event with zero rank_position is rejected."""
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
            metadata={"retrieval_method": "bm25", "rank_position": 0},
        )


def test_ctx_led_assembly_006_retrieved_event_negative_rank_rejected(tmp_path) -> None:
    """retrieved event with negative rank_position is rejected."""
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
            metadata={"retrieval_method": "bm25", "rank_position": -1},
        )


def test_ctx_led_assembly_007_type_validation_int_float_accepted(tmp_path) -> None:
    """retrieval_score accepts both int and float."""
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
    # Test int score
    event_int = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 82},
    )
    assert event_int.metadata["retrieval_score"] == 82

    # Test float score
    event_float = ledger.record_event(
        state.workflow_id,
        "test_step_2",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 0.82},
    )
    assert event_float.metadata["retrieval_score"] == 0.82


def test_ctx_led_assembly_008_rejected_event_valid_metadata(tmp_path) -> None:
    """rejected event with valid metadata is accepted."""
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
        "rejected",
        metadata={"rejection_reason": "token_budget", "retrieval_score": 0.12, "rank_position": 37},
    )
    assert event.event_type == "rejected"
    assert event.metadata["rejection_reason"] == "token_budget"


def test_ctx_led_assembly_009_rejected_event_missing_required_key(tmp_path) -> None:
    """rejected event without rejection_reason is rejected."""
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
            "rejected",
            metadata={"retrieval_score": 0.12},
        )


def test_ctx_led_assembly_010_rejected_event_empty_string_rejected(tmp_path) -> None:
    """rejected event with empty rejection_reason is rejected."""
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
            "rejected",
            metadata={"rejection_reason": ""},
        )


def test_ctx_led_assembly_011_rejected_event_unknown_key_rejected(tmp_path) -> None:
    """rejected event with unknown key is rejected."""
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
            "rejected",
            metadata={"rejection_reason": "token_budget", "unknown_field": "value"},
        )


def test_ctx_led_assembly_020_audit_counts_includes_retrieved_rejected(tmp_path) -> None:
    """Audit counts include retrieved and rejected events."""
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
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "observed",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "selected",
    )

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.observed_count == 1
    assert audit.retrieved_count == 1
    assert audit.selected_count == 1
    assert audit.rejected_count == 0


def test_ctx_led_assembly_021_audit_counts_unique_artifacts(tmp_path) -> None:
    """Audit counts deduplicate artifacts by (workflow_id, step_name, artifact_id, event_type)."""
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

    # Record retrieved event twice - should be deduplicated
    event1 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    event2 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    # Same event should be returned (idempotency)
    assert event1.event_id == event2.event_id

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.retrieved_count == 1  # Not 2


def test_ctx_led_assembly_022_audit_counts_cross_step_deduplication(tmp_path) -> None:
    """Same artifact retrieved in different steps counts separately."""
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

    # Same artifact, retrieved in different steps
    ledger.record_event(
        state.workflow_id,
        "step_a",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    ledger.record_event(
        state.workflow_id,
        "step_b",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "hybrid"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    # Deduplication is per (workflow_id, step_name, artifact_id, event_type)
    # So these count as 2 unique retrieved events
    assert audit.retrieved_count == 2


def test_ctx_led_assembly_023_audit_counts_multiple_artifacts(tmp_path) -> None:
    """Audit counts correctly sum multiple artifacts."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifacts = []
    for i in range(3):
        artifact = ledger.record_artifact(
            state.workflow_id,
            "source_artifact",
            f"test-source-{i}",
            "test_type",
            None,
            f"test-ref-{i}",
            100,
        )
        artifacts.append(artifact)

    # All retrieved
    for artifact in artifacts:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25"},
        )

    # First two selected, third rejected
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[0].artifact_id,
        "selected",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[1].artifact_id,
        "selected",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[2].artifact_id,
        "rejected",
        metadata={"rejection_reason": "token_budget"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.retrieved_count == 3
    assert audit.selected_count == 2
    assert audit.rejected_count == 1

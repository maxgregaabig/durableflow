from __future__ import annotations

from context.ledger import ContextLedger
from src.store import WorkflowStore


def _decision_with_source(tmp_path):
    store = WorkflowStore(tmp_path / "lineage.sqlite")
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
    ledger.record_event(state.workflow_id, "triage_llm", source.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        '{"influential_artifact_ids": ["email-042"]}',
        "mock-fast",
        10,
        3,
        0.01,
    )
    return store, state, ledger, source, decision


def test_ctx_lin_002_free_text_inference_rejected(tmp_path) -> None:
    _store, _state, ledger, source, decision = _decision_with_source(tmp_path)

    try:
        ledger.record_lineage(decision.decision_id, source.artifact_id, "free_text_inference", 1.0)
    except ValueError as exc:
        assert "influence_type" in str(exc)
    else:
        raise AssertionError("unsupported free-text influence mode was accepted")


def test_ctx_lin_001_explicit_influence_lineage(tmp_path) -> None:
    _store, _state, ledger, source, decision = _decision_with_source(tmp_path)

    lineage = ledger.record_lineage(
        decision.decision_id,
        source.artifact_id,
        "explicit_model_attribution",
        1.0,
        "model_response:digest:influential_artifact_ids",
    )

    assert lineage.decision_id == decision.decision_id
    assert lineage.artifact_id == source.artifact_id
    assert lineage.influence_type == "explicit_model_attribution"


def test_deterministic_fixture_attribution_is_allowed(tmp_path) -> None:
    _store, _state, ledger, source, decision = _decision_with_source(tmp_path)

    lineage = ledger.record_lineage(
        decision.decision_id,
        source.artifact_id,
        "deterministic_fixture_attribution",
        1.0,
        "model_response:digest:fixture_map",
    )

    assert lineage.influence_type == "deterministic_fixture_attribution"


def test_ctx_lin_003_foreign_workflow_artifact_rejected(tmp_path) -> None:
    _store, _state, ledger, _source, decision = _decision_with_source(tmp_path)
    foreign_state = _store.create_workflow("test")
    foreign = ledger.record_artifact(
        foreign_state.workflow_id,
        "source_artifact",
        "email-999",
        "prior_email",
        "foreign content",
        "mock_emails:email-999",
        4,
    )
    ledger.record_event(foreign_state.workflow_id, "triage_llm", foreign.artifact_id, "consumed")

    try:
        ledger.record_lineage(
            decision.decision_id,
            foreign.artifact_id,
            "explicit_model_attribution",
            1.0,
        )
    except ValueError as exc:
        assert "decision workflow" in str(exc)
    else:
        raise AssertionError("foreign artifact lineage was accepted")


def test_lineage_recorded_system_event_is_idempotent(tmp_path) -> None:
    _store, state, ledger, source, decision = _decision_with_source(tmp_path)

    ledger.record_lineage(
        decision.decision_id,
        source.artifact_id,
        "explicit_model_attribution",
        1.0,
    )
    ledger.record_lineage(
        decision.decision_id,
        source.artifact_id,
        "explicit_model_attribution",
        1.0,
    )

    lineage_events = [
        event
        for event in ledger.audit_workflow(state.workflow_id).events
        if event.event_type == "lineage_recorded"
    ]
    assert len(lineage_events) == 1

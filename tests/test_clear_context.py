"""CLEAR context lineage integration test (CLEAR-CTX-001).

When the context ledger is enabled, one implement lap records observed,
selected, consumed, and credited (lineage) events plus a decision.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from context.ledger import ContextLedger
from factory import ShipBlockedError
from tests.clear_conftest import make_engine


def test_clear_ctx_001_artifact_lineage_for_implement_lap(tmp_path: Path) -> None:
    eng, store, approval, _ws, _wf = make_engine(
        tmp_path, register_context_ledger=True
    )
    ledger = ContextLedger.from_store(store)
    workflow_id = "wf-ctx"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    audit = ledger.audit_workflow(workflow_id)
    event_types = {e.event_type for e in audit.events}

    # Observed: every artifact that entered the workflow.
    assert "observed" in event_types
    # Selected + consumed: generated files mounted into the implement decision.
    assert "selected" in event_types
    assert "consumed" in event_types
    # A model decision was recorded.
    assert any(e.event_type == "decision_recorded" for e in audit.events)
    # Credited == lineage rows (the ledger has no 'credited' event type).
    assert len(audit.lineage) >= 1, "expected at least one credited (lineage) artifact"
    assert any(
        line.influence_type == "explicit_model_attribution" for line in audit.lineage
    )


def test_clear_ctx_001_lineage_targets_only_selected_or_consumed(tmp_path: Path) -> None:
    """Spec §6.7: lineage is explicit and only to selected/consumed artifacts."""
    eng, store, approval, _ws, _wf = make_engine(
        tmp_path, register_context_ledger=True
    )
    ledger = ContextLedger.from_store(store)
    workflow_id = "wf-lineage"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    audit = ledger.audit_workflow(workflow_id)
    selected_or_consumed = {
        e.artifact_id
        for e in audit.events
        if e.event_type in ("selected", "consumed") and e.artifact_id
    }
    credited = {line.artifact_id for line in audit.lineage}
    # Every credited artifact was first selected/consumed.
    assert credited.issubset(selected_or_consumed)


def test_context_ledger_disabled_is_graceful(tmp_path: Path) -> None:
    """Without a context ledger, the workflow still runs end-to-end."""
    eng, store, approval, _ws, _wf = make_engine(tmp_path)  # no ledger
    workflow_id = "wf-noleddger"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass
    # phase_runner produced output despite no ledger.
    pr = store.load_workflow(workflow_id).step_data.get("phase_runner", {})
    assert pr.get("phase_state") is not None


def test_completion_golden_path_records_context_lineage(tmp_path: Path) -> None:
    """The thesis path: a completed run records selected/consumed/credited lineage.

    Spec §6.7 makes context "required for the full educational thesis."
    This locks that in: the completion golden path (the thesis surface)
    must produce observed, selected, consumed, decision, and credited
    (lineage) events.
    """
    from factory import claim_register
    from factory.verification_ledger import MetaClaimVerifier, VerificationLedger

    eng, store, approval, ws_root, _wf = make_engine(
        tmp_path, register_context_ledger=True
    )
    ledger = ContextLedger.from_store(store)
    workflow_id = "wf-thesis"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    with pytest.raises(ShipBlockedError):
        eng.resume(workflow_id)

    # Record meta verdicts and resume to completion.
    vledger = VerificationLedger(ws_root, workflow_id)
    meta = MetaClaimVerifier(vledger)
    meta.finalize_build()
    for spec in claim_register():
        if not spec.deferred:
            meta.write_evidence(spec.claim_id, f"PASS {spec.claim_id}")
    meta.record_all_verified()
    state = eng.resume(workflow_id)
    assert state.status.value == "completed"

    audit = ledger.audit_workflow(workflow_id)
    event_types = {e.event_type for e in audit.events}
    assert "observed" in event_types
    assert "selected" in event_types
    assert "consumed" in event_types
    assert "decision_recorded" in event_types
    assert len(audit.lineage) >= 1, "thesis completion must credit at least one artifact"

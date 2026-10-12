"""CLEAR planning integration tests.

Covers CLEAR-INT-001 (planning artifacts created before approval) and
CLEAR-INT-002 (workflow pauses at plan_approval and does not enter
phase_runner before approval), plus the plan-rejection no-back-edge rule.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.store import WorkflowStatus
from tests.clear_conftest import make_engine


def _new_engine(tmp_path: Path):
    return make_engine(tmp_path)


def test_clear_int_001_planning_artifacts_before_approval(tmp_path: Path) -> None:
    eng, store, approval, ws_root, _wf = _new_engine(tmp_path)

    state = store.create_workflow("clear", workflow_id="wf-plan")
    state = eng.execute(state.workflow_id)

    # Spec: pauses at plan_approval before any code edits.
    assert state.status == WorkflowStatus.PAUSED_APPROVAL
    # All five planning artifacts exist on disk.
    for artifact in ("prd.md", "design.html", "stack.md", "plan.md", "test.md"):
        assert (ws_root / artifact).exists(), f"missing planning artifact: {artifact}"


def test_clear_int_001_no_code_edits_before_approval(tmp_path: Path) -> None:
    eng, store, _approval, ws_root, _wf = _new_engine(tmp_path)

    state = store.create_workflow("clear", workflow_id="wf-plan")
    eng.execute(state.workflow_id)

    # No generated feature code or tests exist yet (phase_runner not run).
    assert not (ws_root / "src").exists() or not any((ws_root / "src").iterdir())
    # phase_runner macro step has not produced a step_result yet.
    step_names = {row["step_name"] for row in store.step_results(state.workflow_id)}
    assert "phase_runner" not in step_names
    assert "ship" not in step_names


def test_clear_int_002_pauses_at_plan_approval(tmp_path: Path) -> None:
    eng, store, approval, _ws_root, _wf = _new_engine(tmp_path)

    state = store.create_workflow("clear", workflow_id="wf-pause")
    state = eng.execute(state.workflow_id)

    assert state.status == WorkflowStatus.PAUSED_APPROVAL
    # current_step points at plan_approval (index 5 of the 8-step pipeline).
    assert eng.steps[state.current_step] == "plan_approval"
    # A pending approval request exists for plan_approval.
    request = approval.get_for_workflow(state.workflow_id, "plan_approval")
    assert request is not None
    assert request.status == "pending"


def test_clear_int_002_does_not_enter_phase_runner_before_approval(tmp_path: Path) -> None:
    eng, store, _approval, _ws_root, _wf = _new_engine(tmp_path)

    state = store.create_workflow("clear", workflow_id="wf-pause")
    eng.execute(state.workflow_id)

    step_names = [row["step_name"] for row in store.step_results(state.workflow_id)]
    # Planning steps ran, but phase_runner and ship did not.
    assert step_names[-1] == "plan_approval"
    assert "phase_runner" not in step_names
    assert "ship" not in step_names


def test_plan_rejection_does_not_jump_engine_index_backward(tmp_path: Path) -> None:
    """Spec §4.1: rejection records next_action=replan with no back-edge."""
    eng, store, approval, _ws_root, _wf = _new_engine(tmp_path)

    state = store.create_workflow("clear", workflow_id="wf-reject")
    state = eng.execute(state.workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL

    request = approval.get_for_workflow(state.workflow_id, "plan_approval")
    approval.reject(request.gate_id, "scope too broad")

    state = eng.resume(state.workflow_id)
    # Rejected -> terminal REJECTED; macro-step history is append-only.
    assert state.status == WorkflowStatus.REJECTED
    step_indices = [row["step_index"] for row in store.step_results(state.workflow_id)]
    # Indices are monotonically non-decreasing (no back-edge).
    assert step_indices == sorted(step_indices)
    # No phase_runner entry appeared after rejection.
    assert "phase_runner" not in {r["step_name"] for r in store.step_results(state.workflow_id)}


def test_planning_artifacts_registered_in_context_ledger(tmp_path: Path) -> None:
    """When the context ledger is present, planning artifacts are registered."""
    from context.ledger import ContextLedger

    eng, store, _approval, _ws_root, _wf = make_engine(
        tmp_path, register_context_ledger=True
    )
    ledger = ContextLedger.from_store(store)

    state = store.create_workflow("clear", workflow_id="wf-ctx")
    eng.execute(state.workflow_id)

    audit = ledger.audit_workflow(state.workflow_id)
    sources = {a.source for a in audit.artifacts}
    # Planning artifacts were observed.
    assert "prd.md" in sources or any("prd" in s for s in sources)
    assert any(a.source == "plan.md" for a in audit.artifacts)


def test_report_approval_pauses_before_release(tmp_path: Path) -> None:
    """Spec §2.1 item 7: optional operator report approval before release.

    With the gate on, the pipeline is ... phase_runner -> report_approval
    (pauses) -> ship. The operator can review, then approve to release.
    """
    from factory import ShipBlockedError, claim_register
    from factory.verification_ledger import MetaClaimVerifier, VerificationLedger

    eng, store, approval, ws_root, _wf = make_engine(
        tmp_path, require_report_approval=True
    )
    workflow_id = "wf-report-gate"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Resume: phase_runner runs, then report_approval PAUSES (before ship).
    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL
    request = approval.get_for_workflow(workflow_id, "report_approval")
    assert request is not None and request.status == "pending"
    # ship has not run yet.
    assert "ship" not in store.load_workflow(workflow_id).step_data

    # Approve the report. Ship then runs but blocks on meta-claims.
    approval.approve(request.gate_id, "operator")
    with pytest.raises(ShipBlockedError):
        eng.resume(workflow_id)

    # Record independent meta verdicts, then resume to completion.
    ledger = VerificationLedger(ws_root, workflow_id)
    meta = MetaClaimVerifier(ledger)
    meta.finalize_build()
    for spec in claim_register():
        if not spec.deferred:
            meta.write_evidence(spec.claim_id, f"PASS {spec.claim_id}")
    meta.record_all_verified()

    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.COMPLETED
    assert store.load_workflow(workflow_id).step_data["ship"]["shipped"] is True


def test_report_approval_rejection_blocks_release(tmp_path: Path) -> None:
    """Rejecting the report approval prevents release (engine -> REJECTED)."""
    eng, store, approval, _ws_root, _wf = make_engine(
        tmp_path, require_report_approval=True
    )
    workflow_id = "wf-report-rej"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Resume to the report_approval pause.
    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.PAUSED_APPROVAL
    request = approval.get_for_workflow(workflow_id, "report_approval")
    approval.reject(request.gate_id, "report not acceptable")

    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.REJECTED
    assert "ship" not in store.load_workflow(workflow_id).step_data

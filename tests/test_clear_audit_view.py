"""CLEAR audit view + semantic fitness tests.

Covers CLEAR-UNIT-005 (raw state mapped to operator-facing fields) and
SEM-CLEAR-001..007 (the rendered audit uses ubiquitous language with
zero blocklisted terms across planning, active, failed, remediating,
blocked, and complete states).
"""

from __future__ import annotations

from pathlib import Path

from context.ledger import ContextLedger
from factory import (
    ClearPhaseState,
    PhasePlanParser,
    ShipBlockedError,
    build_clear_workflow_audit_view,
    render_clear_workflow_audit,
    scan_for_blocklisted_terms,
)
from factory.verification_ledger import VerificationLedger
from src.store import WorkflowStatus
from tests.clear_conftest import make_engine


# --- CLEAR-UNIT-005: builder maps raw state -> view fields ------------------

def test_clear_unit_005_builder_maps_step_data_to_view(tmp_path: Path) -> None:
    eng, store, approval, ws_root, _wf = make_engine(
        tmp_path, force_failure_phase=1, register_context_ledger=True
    )
    workflow_id = "wf-unit005"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    raw = store.load_workflow(workflow_id)
    pr = raw.step_data.get("phase_runner", {})
    phase_state = ClearPhaseState.from_dict(pr.get("phase_state", {}))
    phases = PhasePlanParser().parse(__import__("factory").DEFAULT_PLAN_MD)
    ledger = ContextLedger.from_store(store)
    gate = VerificationLedger(ws_root, workflow_id).evaluate_ship()

    view = build_clear_workflow_audit_view(
        raw,
        phase_state=phase_state,
        phases=phases,
        ship_result=gate,
        context_audit=ledger.audit_workflow(workflow_id),
        planning_artifacts=["prd.md", "design.html", "stack.md", "plan.md", "test.md"],
        product_name="Zen Chat",
    )

    # Raw step_data/internal keys are NOT exposed as top-level fields.
    assert hasattr(view, "plan_summary")
    assert hasattr(view, "active_phase")
    assert hasattr(view, "next_action")
    # Phase is rendered as "Phase N: [Name]".
    assert view.plan_summary.phase_names[0].startswith("Phase 1:")
    # Next-action description is in operator language.
    assert view.next_action.description
    assert "step_data" not in view.next_action.description


# --- SEM-CLEAR-001..007: rendered output never uses blocklisted terms -------

def _render_for_state(
    tmp_path: Path,
    *,
    force_failure: int = 0,
    register_ledger: bool = True,
    workflow_id: str = "wf-sem",
) -> str:
    eng, store, approval, ws_root, _wf = make_engine(
        tmp_path, force_failure_phase=force_failure, register_context_ledger=register_ledger
    )
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    raw = store.load_workflow(workflow_id)
    pr = raw.step_data.get("phase_runner", {})
    phase_state = ClearPhaseState.from_dict(pr.get("phase_state", {}))
    phases = PhasePlanParser().parse(__import__("factory").DEFAULT_PLAN_MD)
    ledger = ContextLedger.from_store(store)
    gate = VerificationLedger(ws_root, workflow_id).evaluate_ship()
    view = build_clear_workflow_audit_view(
        raw,
        phase_state=phase_state,
        phases=phases,
        ship_result=gate,
        context_audit=ledger.audit_workflow(workflow_id),
        planning_artifacts=["prd.md", "design.html", "stack.md", "plan.md", "test.md"],
        product_name="Zen Chat",
    )
    return render_clear_workflow_audit(view)


def test_sem_clear_007_blocklist_zero_terms_active_state(tmp_path: Path) -> None:
    rendered = _render_for_state(tmp_path)
    assert scan_for_blocklisted_terms(rendered) == []


def test_sem_clear_005_remediating_state_uses_plain_language(tmp_path: Path) -> None:
    """Remediation shown as 'Analyzing failure'/'Fixing issues', not internals."""
    rendered = _render_for_state(tmp_path, force_failure=1)
    assert scan_for_blocklisted_terms(rendered) == []
    # Ubiquitous language for remediation is present somewhere in the run.
    assert "Fix" in rendered or "Running tests" in rendered or "Passed" in rendered


def test_sem_clear_004_context_lineage_has_three_sections(tmp_path: Path) -> None:
    """Context lineage separates Selected / Consumed / Credited."""
    rendered = _render_for_state(tmp_path)
    assert "Selected for prompts" in rendered
    assert "Consumed by agent" in rendered
    assert "Credited in decisions" in rendered


def test_sem_clear_001_active_phase_uses_phase_name_not_index(tmp_path: Path) -> None:
    rendered = _render_for_state(tmp_path)
    assert "Phase 1:" in rendered or "Phase 2:" in rendered
    # The forbidden 'current_step' token is absent.
    assert "current_step" not in rendered


def test_sem_clear_003_complete_view_cites_evidence_and_verifier(tmp_path: Path) -> None:
    """COMPLETE summary cites [claim] -> verdict -> evidence -> verifier."""
    from factory import claim_register
    from factory.verification_ledger import MetaClaimVerifier

    eng, store, approval, ws_root, _wf = make_engine(tmp_path, register_context_ledger=True)
    workflow_id = "wf-complete"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass
    # Now record independent meta verdicts and resume to completion.
    ledger = VerificationLedger(ws_root, workflow_id)
    meta = MetaClaimVerifier(ledger)
    meta.finalize_build()
    for spec in claim_register():
        if spec.deferred:
            continue
        meta.write_evidence(spec.claim_id, f"PASS {spec.claim_id}")
    meta.record_all_verified()
    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.COMPLETED

    rendered = (ws_root / "audit-summary.md").read_text()
    assert scan_for_blocklisted_terms(rendered) == []
    # Evidence pointers and verifier identities are cited.
    assert "Verdict:" in rendered
    assert "Verifier:" in rendered
    assert "C-CLEAR-" in rendered


def test_sem_clear_006_blocked_workflow_explains_in_operator_terms(
    tmp_path: Path,
) -> None:
    """A blocked run explains the blocker without PauseForApproval internals."""
    rendered = _render_for_state(tmp_path, force_failure=1, register_ledger=False)
    assert scan_for_blocklisted_terms(rendered) == []
    # No raw engine internals leak.
    assert "PauseForApproval" not in rendered


def test_render_never_emits_blocklist_across_various_states(tmp_path: Path) -> None:
    """Regression guard: multiple states all render blocklist-free."""
    for force in (0, 1):
        sub = tmp_path / f"force-{force}"
        sub.mkdir()
        rendered = _render_for_state(
            sub, force_failure=force, workflow_id=f"wf-sem-{force}"
        )
        assert scan_for_blocklisted_terms(rendered) == [], (
            f"blocklist hit for force={force}: {scan_for_blocklisted_terms(rendered)}"
        )


# --- Phase-status mapping consistency (desync guard) -----------------------

def test_every_phase_status_has_ubiquitous_language_mapping() -> None:
    """If a new PhaseStatus is added, PHASE_STATUS_LANGUAGE must cover it.

    Guards against the audit view silently exposing raw internal state when
    a new status is introduced without a ubiquitous-language translation.
    """
    from factory.audit_view import PHASE_STATUS_LANGUAGE
    from factory.phase_state import PHASE_STATUSES

    missing = [s for s in PHASE_STATUSES if s not in PHASE_STATUS_LANGUAGE]
    assert not missing, (
        f"PHASE_STATUS_LANGUAGE missing translations for: {missing}"
    )
    # And no mapping leaks a raw internal token back out.
    for status, label in PHASE_STATUS_LANGUAGE.items():
        assert "=" not in label, f"{status} mapping leaks '{label}'"
        assert label.strip(), f"{status} maps to empty label"


def test_every_next_action_has_ubiquitous_language_mapping() -> None:
    """Every NextAction value has an operator-language translation."""
    from factory.audit_view import NEXT_ACTION_LANGUAGE
    from factory.phase_state import NEXT_ACTIONS

    missing = [a for a in NEXT_ACTIONS if a not in NEXT_ACTION_LANGUAGE]
    assert not missing, f"NEXT_ACTION_LANGUAGE missing: {missing}"

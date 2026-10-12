"""CLEAR remediation integration: forced failure -> Five Whys -> re-assess.

Covers CLEAR-INT-004 and C-CLEAR-005: an automated test failure triggers
remediation without human approval, writes a report + Five Whys root
cause, updates the feature, and re-assesses the same phase.
"""

from __future__ import annotations

from pathlib import Path

from factory import ClearPhaseState, ShipBlockedError
from tests.clear_conftest import make_engine


def _run_phase_runner(tmp_path: Path, *, force_failure_phase: int, max_attempts: int = 3):
    eng, store, approval, ws_root, _wf = make_engine(
        tmp_path,
        force_failure_phase=force_failure_phase,
        max_attempts=max_attempts,
    )
    workflow_id = "wf-rem"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass  # ship blocks on meta-claims; remediation already happened.
    return store, ws_root, workflow_id


def test_clear_int_004_forced_failure_triggers_remediation(tmp_path: Path) -> None:
    store, ws_root, workflow_id = _run_phase_runner(tmp_path, force_failure_phase=1)

    pr = store.load_workflow(workflow_id).step_data.get("phase_runner", {})
    phase_state = ClearPhaseState.from_dict(pr.get("phase_state", {}))

    by_attempt: dict[int, list[tuple[str, str]]] = {}
    for lap in phase_state.lap_history:
        if lap.phase == 1:
            by_attempt.setdefault(lap.attempt, []).append((lap.lap_kind, lap.status))

    # attempt 1 fails assessment, remediates; attempt 2 re-assesses and passes.
    assert ("assess", "failed") in by_attempt.get(1, [])
    assert ("remediate", "passed") in by_attempt.get(1, [])
    assert ("assess", "passed") in by_attempt.get(2, [])

    # Five Whys root-cause artifact is on disk.
    assert (ws_root / "phase_1_five_whys.md").exists()
    # A phase report naming the failure is on disk.
    assert (ws_root / "phase_1_report.md").exists()
    # Phase 1 ultimately passed.
    assert 1 in phase_state.completed_phases


def test_clear_int_004_remediation_requires_no_human_approval(tmp_path: Path) -> None:
    """Remediation runs autonomously; no approval is requested mid-phase."""
    store, _ws_root, workflow_id = _run_phase_runner(tmp_path, force_failure_phase=1)

    # The only approval step in the pipeline is plan_approval; remediation
    # never paused the workflow for a second human decision.
    rows = store.step_results(workflow_id)
    assert all(
        "approval" not in r["step_name"] or r["step_name"] == "plan_approval"
        for r in rows
    )


def test_clear_int_004_attempt_limit_blocks(tmp_path: Path) -> None:
    """Exceeding max_attempts sets blocked status (spec §6.4)."""
    store, _ws_root, workflow_id = _run_phase_runner(
        tmp_path, force_failure_phase=1, max_attempts=1
    )

    pr = store.load_workflow(workflow_id).step_data.get("phase_runner", {})
    assert pr.get("blocked") is True


def test_clear_int_004_report_contains_failed_assertion_and_log_path(
    tmp_path: Path,
) -> None:
    """Spec §3.5 SEM-CLEAR-002: report surfaces the failed assertion + log path.

    Each attempt keeps its own report; the failed attempt-1 report is
    preserved alongside the passing attempt-2 report.
    """
    _store, ws_root, _workflow_id = _run_phase_runner(tmp_path, force_failure_phase=1)

    failed_report = (ws_root / "phase_1_attempt_1_report.md").read_text()
    assert "Test command:" in failed_report
    assert "FAILED" in failed_report
    assert ".log" in failed_report  # archived log pointer, not prose-only


def test_clear_int_004_root_cause_names_failed_claim(tmp_path: Path) -> None:
    """The Five Whys artifact names the failed claim and a correction."""
    _store, ws_root, _workflow_id = _run_phase_runner(tmp_path, force_failure_phase=1)

    five_whys = (ws_root / "phase_1_five_whys.md").read_text()
    assert "Failed claim" in five_whys
    assert "Proposed correction" in five_whys

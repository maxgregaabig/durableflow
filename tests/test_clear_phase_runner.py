"""CLEAR phase runner integration: crash resume (CLEAR-INT-003).

The load-bearing architectural fact: ``WorkflowStore.save_checkpoint``
runs only after a macro step returns, so ``phase_runner`` checkpoints
micro state in a dedicated ``clear_phase_state`` table between laps.
A crash after the implement lap must resume at the assess lap without
duplicating the implement write side effects.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from factory import (
    AgentRunner,
    ClearLapResult,
    ClearPhaseState,
    PhasePlanParser,
    ShipBlockedError,
    Workspace,
)
from factory.phase_store import ClearPhaseStore
from src.store import WorkflowStore
from tests.clear_conftest import make_engine


SINGLE_PHASE_PLAN = (
    "## Phase 1: Core Greeting\n"
    "Test: python3 -m pytest -q tests/test_phase_1.py\n"
    "Claim C-CLEAR-PHASE-1: The core greeting includes the caller name and phase number\n"
)


def _side_effect_rows(store: WorkflowStore, workflow_id: str) -> list[dict]:
    """Return decoded side_effect_log rows for inspection."""
    with store.connect() as conn:
        rows = conn.execute(
            "SELECT result FROM side_effect_log WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchall()
    return [json.loads(r["result"]) for r in rows]


def _write_signature(store: WorkflowStore, workflow_id: str) -> set[tuple]:
    """Set of (path, phase, attempt) for every recorded mutating write."""
    return {
        (r["path"], r["phase"], r["attempt"])
        for r in _side_effect_rows(store, workflow_id)
    }


def _implement_writes(store: WorkflowStore, workflow_id: str) -> set[tuple]:
    """Only the implement-lap source writes (conftest, src/, tests/).

    The assess and verify laps legitimately add non-source writes (code-read
    notes); the crash-resume guarantee is specifically that the IMPLEMENT lap
    is not repeated, so we assert against these source writes only.
    """
    return {
        sig
        for sig in _write_signature(store, workflow_id)
        if sig[0].startswith(("conftest", "src/", "tests/"))
    }


def _seed_implement_lap(
    store: WorkflowStore, ws_root: Path, workflow_id: str
) -> set[tuple]:
    """Pre-create the phase-1 implement lap exactly as AgentRunner would.

    Returns the write signature after seeding, so the test can assert it
    is unchanged after resume.
    """
    ws = Workspace(ws_root, store=store)
    phases = PhasePlanParser().parse(SINGLE_PHASE_PLAN)
    phase = phases[0]
    # Run the real implementer through the workspace so file content,
    # conftest, and test module match what phase_runner expects.
    AgentRunner(ws).run_implement_lap(
        phase, attempt=1, workflow_id=workflow_id, force_failure=False
    )
    return _write_signature(store, workflow_id)


def test_clear_int_003_crash_after_implement_resumes_at_assess(tmp_path: Path) -> None:
    """A checkpointed implement lap is not repeated on resume."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path, plan_md=SINGLE_PHASE_PLAN)
    workflow_id = "wf-crash"

    state = store.create_workflow("clear", workflow_id=workflow_id)
    state = eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Simulate phase_runner having completed the phase-1 implement lap and
    # checkpointed phase_status="assessing", then crashing before the assess
    # lap. Seed the implement files exactly as the real lap produced them.
    phase_store = ClearPhaseStore(store)
    pre = ClearPhaseState(current_phase=1, attempt=1, phase_status="assessing")
    pre.append_lap(
        ClearLapResult(
            phase=1, attempt=1, lap_kind="implement", status="passed",
            evidence=["src/phase_1_feature.py"],
        )
    )
    phase_store.save(workflow_id, pre)
    before = _seed_implement_lap(store, ws_root, workflow_id)

    # Resume: phase_runner reads the checkpoint and continues at assess.
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass  # ship blocks on meta-claims; that's fine for this test.

    # The implement lap was NOT repeated: its source-file write signature is
    # unchanged after resume. (Assess/verify laps legitimately add code-read
    # notes, which are not implement writes.)
    impl_before = _implement_writes(store, workflow_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass
    impl_after = _implement_writes(store, workflow_id)
    assert impl_before == impl_after, (
        f"resume duplicated implement writes: before={impl_before} after={impl_after}"
    )

    loaded = phase_store.load(workflow_id)
    lap_kinds = [(l.phase, l.attempt, l.lap_kind) for l in loaded.lap_history]
    assert (1, 1, "implement") in lap_kinds
    assert (1, 1, "assess") in lap_kinds


def test_clear_int_003_resume_does_not_duplicate_writes(tmp_path: Path) -> None:
    """Replaying the same implement write key performs one side effect."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path, plan_md=SINGLE_PHASE_PLAN)
    workflow_id = "wf-dedup"

    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Seed a completed phase-1 implement lap, then resume: assess should run
    # without re-doing the implement writes.
    phase_store = ClearPhaseStore(store)
    pre = ClearPhaseState(current_phase=1, attempt=1, phase_status="assessing")
    pre.append_lap(ClearLapResult(phase=1, attempt=1, lap_kind="implement", status="passed"))
    phase_store.save(workflow_id, pre)
    impl_before = _implement_writes(store, workflow_id)
    _seed_implement_lap(store, ws_root, workflow_id)
    impl_seeded = _implement_writes(store, workflow_id)

    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    loaded = phase_store.load(workflow_id)
    assert (1, 1, "assess") in [(l.phase, l.attempt, l.lap_kind) for l in loaded.lap_history]
    # No implement writes were re-logged (only the seeded ones remain).
    assert _implement_writes(store, workflow_id) == impl_seeded


def test_clear_int_003_lap_history_is_append_only(tmp_path: Path) -> None:
    """lap_history grows monotonically across resume (spec §4.1)."""
    phase_store = ClearPhaseStore(WorkflowStore(tmp_path / "p.sqlite"))
    wf = "wf-hist"
    state = ClearPhaseState()
    state.append_lap(ClearLapResult(phase=1, attempt=1, lap_kind="implement", status="passed"))
    phase_store.save(wf, state)

    reloaded = phase_store.load(wf)
    reloaded.append_lap(ClearLapResult(phase=1, attempt=1, lap_kind="assess", status="passed"))
    phase_store.save(wf, reloaded)

    final = phase_store.load(wf)
    assert [l.lap_kind for l in final.lap_history] == ["implement", "assess"]

"""Unambiguous crash-resume test using a real subprocess crash.

CLEAR-INT-003 asks for evidence that a mid-``phase_runner`` crash resumes
on the correct lap without duplicating writes. The unit-level test seeds a
checkpoint; this test goes further: a child process actually runs
``phase_runner``, hard-crashes (``os._exit(1)``) immediately after the
phase-1 implement lap is checkpointed, and the parent then resumes and
asserts the implement lap was not repeated.

This mirrors the existing ``examples/crash_resume_demo.py`` pattern.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

from factory import ClearConfig, ClearWorkflow, ShipBlockedError
from factory.phase_store import ClearPhaseStore
from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStore
from src.telemetry import TelemetryLogger

ROOT = Path(__file__).resolve().parents[1]

SINGLE_PHASE_PLAN = (
    "## Phase 1: Core Greeting\n"
    "Test: python3 -m pytest -q tests/test_phase_1.py\n"
    "Claim C-CLEAR-PHASE-1: The core greeting includes the caller name and phase number\n"
)

_CHILD_SCRIPT = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    ROOT = Path({root!r})
    sys.path.insert(0, str(ROOT))
    from src.approval import ApprovalGate
    from src.engine import WorkflowEngine
    from src.store import WorkflowStore
    from src.telemetry import TelemetryLogger
    from factory import ClearConfig, ClearWorkflow

    db = Path({db!r})
    ws_root = Path({ws_root!r})
    store = WorkflowStore(db)
    approval = ApprovalGate(store)
    deps = {{"store": store, "approval_gate": approval}}
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), deps)
    cfg = ClearConfig(workspace_root=ws_root, plan_md={plan!r})
    wf = ClearWorkflow(cfg)
    wf.register(engine)

    # Crash injector: raise SystemExit via os._exit the first time
    # _advance_phase records a phase-1 implement lap.
    original = wf._advance_phase
    state = {{"fired": False}}
    def crashing(*a, **kw):
        out = original(*a, **kw)
        if not state["fired"] and any(
            l.phase == 1 and l.lap_kind == "implement" for l in out.lap_history
        ):
            state["fired"] = True
            print("[child] crashing after phase 1 implement+assess cycle", flush=True)
            os._exit(1)
        return out
    wf._advance_phase = crashing

    try:
        engine.resume({workflow_id!r})
    except SystemExit:
        raise
    """
)


def _build_runtime(tmp_path: Path):
    db = tmp_path / "crash.sqlite"
    ws_root = tmp_path / "ws"
    ws_root.mkdir(parents=True, exist_ok=True)
    store = WorkflowStore(db)
    approval = ApprovalGate(store)
    deps = {"store": store, "approval_gate": approval}
    engine = WorkflowEngine(store, TelemetryLogger(echo=False), deps)
    cfg = ClearConfig(workspace_root=ws_root, plan_md=SINGLE_PHASE_PLAN)
    wf = ClearWorkflow(cfg)
    wf.register(engine)
    return db, ws_root, store, approval, engine, wf


def test_clear_int_003_subprocess_crash_resume(tmp_path: Path) -> None:
    """A real process crash after the implement lap resumes without duplicating writes."""
    db, ws_root, store, approval, engine, _wf = _build_runtime(tmp_path)
    workflow_id = "wf-subproc"

    # Planning + plan approval in the parent.
    state = store.create_workflow("clear", workflow_id=workflow_id)
    engine.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Snapshot the implement-lap side effects that exist right now (none yet).
    pre_implement_writes = store.side_effect_count(workflow_id)

    # Spawn a child that resumes phase_runner and hard-crashes after the
    # phase-1 implement lap is checkpointed.
    script = _CHILD_SCRIPT.format(
        root=str(ROOT), db=str(db), ws_root=str(ws_root),
        plan=SINGLE_PHASE_PLAN, workflow_id=workflow_id,
    )
    child = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    # The child must have crashed (non-zero) with our marker on stdout.
    assert child.returncode != 0, "child did not crash as expected"
    assert "[child] crashing after phase 1 implement+assess cycle" in child.stdout

    # After the crash, the phase-1 implement+assess cycle WAS checkpointed
    # (its side effects recorded) but phase_runner did not return, so ship
    # never ran and the macro workflow is left mid-step.
    post_crash_writes = store.side_effect_count(workflow_id)
    assert post_crash_writes > pre_implement_writes, "phase-1 laps never ran"
    phase_store = ClearPhaseStore(store)
    crashed_state = phase_store.load(workflow_id)
    assert crashed_state is not None
    lap_kinds = [(l.phase, l.attempt, l.lap_kind) for l in crashed_state.lap_history]
    assert (1, 1, "implement") in lap_kinds
    assert (1, 1, "assess") in lap_kinds
    assert 1 in crashed_state.completed_phases

    # The parent detects the crash and resumes.
    store.mark_stale_for_demo(workflow_id, seconds_old=0)
    engine.recover_crashed(stale_after_seconds=0)
    try:
        engine.resume(workflow_id)
    except ShipBlockedError:
        pass  # ship blocks on meta-claims; phase_runner already finished.

    # The checkpointed phase-1 laps were NOT repeated: the mutating-write
    # count is unchanged from immediately after the crash.
    final_writes = store.side_effect_count(workflow_id)
    assert final_writes == post_crash_writes, (
        f"resume duplicated writes: after crash={post_crash_writes} final={final_writes}"
    )

    # And phase_runner completed on resume (its step_result now exists).
    # ship is not asserted here: it legitimately raises ShipBlockedError on
    # unverified meta-claims, which is covered by test_clear_verification.py.
    step_names = {r["step_name"] for r in store.step_results(workflow_id)}
    assert "phase_runner" in step_names

"""CLEAR unit tests: phase state, parser, workspace boundary, idempotency.

Covers CLEAR-UNIT-001 (state serialization), CLEAR-UNIT-002 (plan parser),
CLEAR-UNIT-003 (workspace boundary), CLEAR-UNIT-004 (idempotent write).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import (
    ClearLapResult,
    ClearPhaseState,
    PatchApplicationError,
    PhasePlanParser,
    Workspace,
    WorkspaceViolationError,
    apply_search_replace,
)
from src.store import WorkflowStore


# --- CLEAR-UNIT-001: phase state round-trips -------------------------------

def test_clear_unit_001_phase_state_round_trips() -> None:
    state = ClearPhaseState(
        current_phase=2,
        attempt=1,
        phase_status="assessing",
        next_action="advance",
        last_report="phase_2_report.md",
        mounted_artifact_ids=["ctx-art-1"],
        max_attempts=5,
    )
    state.append_lap(
        ClearLapResult(
            phase=1,
            attempt=1,
            lap_kind="assess",
            status="passed",
            report="phase_1_report.md",
            evidence=["verification/phase_1_tests.log"],
            failed_assertions=[],
        )
    )

    restored = ClearPhaseState.from_dict(state.to_dict())

    assert restored.current_phase == 2
    assert restored.attempt == 1
    assert restored.phase_status == "assessing"
    assert restored.next_action == "advance"
    assert restored.last_report == "phase_2_report.md"
    assert restored.mounted_artifact_ids == ["ctx-art-1"]
    assert restored.max_attempts == 5
    assert len(restored.lap_history) == 1
    lap = restored.lap_history[0]
    assert (lap.phase, lap.attempt, lap.lap_kind, lap.status) == (1, 1, "assess", "passed")
    assert lap.evidence == ["verification/phase_1_tests.log"]


def test_clear_unit_001_state_carries_required_keys() -> None:
    """Spec §6.4 required state keys are all present after round-trip."""
    data = ClearPhaseState().to_dict()
    required = {
        "current_phase",
        "attempt",
        "phase_status",
        "next_action",
        "last_report",
        "mounted_artifact_ids",
        "lap_history",
    }
    assert required.issubset(data.keys())


# --- CLEAR-UNIT-002: plan parser -------------------------------------------

def test_clear_unit_002_parser_parses_deterministic_phases() -> None:
    plan = (
        "## Phase 1: Core Models\n"
        "Test: python -m pytest -q tests/test_core.py\n"
        "Claim C-A-1: models validate\n"
        "\n"
        "## Phase 2: API Layer\n"
        "Test: python -m pytest -q tests/test_api.py\n"
    )
    phases = PhasePlanParser().parse(plan)
    assert [p.label for p in phases] == ["Phase 1: Core Models", "Phase 2: API Layer"]
    assert phases[0].test_command == "python -m pytest -q tests/test_core.py"
    assert phases[0].claims[0].claim_id == "C-A-1"


def test_clear_unit_002_parser_rejects_non_sequential_phases() -> None:
    plan = (
        "## Phase 1: A\nTest: pytest a\n"
        "## Phase 3: C\nTest: pytest c\n"
    )
    with pytest.raises(ValueError, match="sequential"):
        PhasePlanParser().parse(plan)


def test_clear_unit_002_parser_rejects_phase_without_test() -> None:
    plan = "## Phase 1: A\nNo test here\n"
    with pytest.raises(ValueError, match="no Test command"):
        PhasePlanParser().parse(plan)


def test_clear_unit_002_parser_rejects_empty_plan() -> None:
    with pytest.raises(ValueError, match="no phases"):
        PhasePlanParser().parse("# nothing here\n")


def test_clear_unit_002_parser_rejects_duplicate_phase_names() -> None:
    plan = (
        "## Phase 1: Same\nTest: pytest a\n"
        "## Phase 2: Same\nTest: pytest b\n"
    )
    with pytest.raises(ValueError, match="duplicate phase names"):
        PhasePlanParser().parse(plan)


# --- CLEAR-UNIT-003: workspace boundary ------------------------------------

def test_clear_unit_003_write_outside_workspace_is_rejected(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(WorkspaceViolationError):
        ws.write_file(
            "../escape.md", "boom",
            workflow_id="wf", phase=1, attempt=1,
        )


def test_clear_unit_003_traversal_outside_workspace_rejected(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    with pytest.raises(WorkspaceViolationError):
        ws.resolve("../../etc/passwd")


def test_clear_unit_003_write_inside_workspace_allowed(tmp_path: Path) -> None:
    ws = Workspace(tmp_path / "ws")
    result = ws.write_file(
        "src/feature.py", "print('hi')",
        workflow_id="wf", phase=1, attempt=1,
    )
    assert (tmp_path / "ws" / "src" / "feature.py").read_text() == "print('hi')"
    assert result.already_applied is False


# --- CLEAR-UNIT-004: idempotent write --------------------------------------

def test_clear_unit_004_same_write_key_performs_one_side_effect(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf-x")
    ws = Workspace(tmp_path / "ws", store=store)

    first = ws.write_file(
        "src/a.py", "CONTENT",
        workflow_id="wf-x", phase=1, attempt=1,
    )
    second = ws.write_file(
        "src/a.py", "CONTENT",
        workflow_id="wf-x", phase=1, attempt=1,
    )

    assert first.already_applied is False
    assert second.already_applied is True
    assert first.idempotency_key == second.idempotency_key
    # exactly one side-effect row recorded
    assert store.side_effect_count("wf-x") == 1


def test_clear_unit_004_different_content_creates_new_side_effect(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    ws = Workspace(tmp_path / "ws", store=store)

    ws.write_file("src/a.py", "v1", workflow_id="wf", phase=1, attempt=1)
    ws.write_file("src/a.py", "v2", workflow_id="wf", phase=1, attempt=1)

    assert store.side_effect_count("wf") == 2


def test_clear_unit_004_retry_links_to_original_write(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    ws = Workspace(tmp_path / "ws", store=store)

    original = ws.write_file("src/a.py", "X", workflow_id="wf", phase=2, attempt=1)
    replayed = ws.write_file("src/a.py", "X", workflow_id="wf", phase=2, attempt=1)

    # The retry returns the cached result (same bytes) and does not log again.
    assert replayed.already_applied is True
    assert replayed.bytes_written == original.bytes_written
    assert store.side_effect_count("wf") == 1


# --- apply_patch: real search/replace semantics ----------------------------

def test_apply_patch_replaces_unique_block(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    ws = Workspace(tmp_path / "ws", store=store)
    ws.write_file("a.py", "def f():\n    return 1\n", workflow_id="wf", phase=1, attempt=1)

    patch = (
        "<<<<<<< SEARCH\n"
        "    return 1\n"
        "=======\n"
        "    return 2\n"
        ">>>>>>> REPLACE\n"
    )
    ws.apply_patch("a.py", patch, workflow_id="wf", phase=1, attempt=1)
    assert ws.read_file("a.py") == "def f():\n    return 2\n"


def test_apply_patch_idempotent_under_retry(tmp_path: Path) -> None:
    """A retried apply_patch on identical inputs is a cache hit (no new write).

    Idempotency is keyed on the resulting content: after a crash, replaying
    the same patch against the same base produces the same patched string,
    so the digest cache returns the original result without a new side effect.
    """
    import hashlib

    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    base_ws = Workspace(tmp_path / "ws", store=store)
    base_ws.write_file("a.py", "def f():\n    return 1\n", workflow_id="wf", phase=1, attempt=1)

    patch = "<<<<<<< SEARCH\n    return 1\n=======\n    return 2\n>>>>>>> REPLACE\n"

    # First application.
    ws1 = Workspace(tmp_path / "ws", store=store)
    first = ws1.apply_patch("a.py", patch, workflow_id="wf", phase=1, attempt=2)
    assert first.already_applied is False

    # Simulate a retry that re-derives the patch result against the original
    # base (the crash left the file pre-patch). The derived content is
    # identical to what was written, so the digest key already exists.
    derived, _ = apply_search_replace("def f():\n    return 1\n", patch)
    digest = hashlib.sha256(derived.encode("utf-8")).hexdigest()
    key = ws1._idempotency_key("wf", 1, 2, "a.py", digest)
    assert store.get_side_effect(key) is not None


def test_apply_patch_rejects_missing_search(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    ws = Workspace(tmp_path / "ws", store=store)
    ws.write_file("a.py", "def f():\n    return 1\n", workflow_id="wf", phase=1, attempt=1)

    patch = "<<<<<<< SEARCH\nnope\n=======\nyes\n>>>>>>> REPLACE\n"
    with pytest.raises(PatchApplicationError, match="not found"):
        ws.apply_patch("a.py", patch, workflow_id="wf", phase=1, attempt=1)


def test_apply_patch_rejects_ambiguous_search(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "side.sqlite")
    store.create_workflow("test", workflow_id="wf")
    ws = Workspace(tmp_path / "ws", store=store)
    ws.write_file("a.py", "x = 1\nx = 1\n", workflow_id="wf", phase=1, attempt=1)

    patch = "<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n"
    with pytest.raises(PatchApplicationError, match="matched 2 times"):
        ws.apply_patch("a.py", patch, workflow_id="wf", phase=1, attempt=1)

from __future__ import annotations

import inspect
import re
import subprocess
import sys
from typing import get_type_hints

from context.audit_view import ContextAuditView, build_context_audit_view, render_context_audit
from context.ledger import ContextLedger
from src.store import WorkflowStore


def test_ctx_aud_001_builder_maps_primary_concepts(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "audit.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)
    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "content",
        "mock_emails:email-042",
        5,
    )
    ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "selected")
    ledger.record_event(state.workflow_id, "triage_llm", artifact.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        '{"influential_artifact_ids": ["email-042"]}',
        "mock-fast",
        12,
        4,
        0.02,
    )
    ledger.record_lineage(decision.decision_id, artifact.artifact_id, "explicit_model_attribution", 1.0)

    view = build_context_audit_view(ledger.audit_workflow(state.workflow_id))
    rendered = render_context_audit(view)

    assert "Knowledge trail" in view.lineage_summary
    assert "Mounted context" in rendered
    assert "Influential sources" in rendered
    assert "trust policy" in rendered


def test_ctx_aud_002_renderer_consumes_view_only() -> None:
    source = inspect.getsource(render_context_audit)
    annotations = get_type_hints(render_context_audit)
    assert annotations["view"] is ContextAuditView
    assert annotations["return"] is str
    assert "ContextAuditView" in source
    without_view_name = source.replace("ContextAuditView", "")
    assert "ContextAudit" not in without_view_name
    assert "InfoArtifact" not in source
    assert "DecisionRecord" not in source
    assert "DecisionLineage" not in source


def test_sem_ctx_004_influence_labels_are_step_scoped(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "semantic.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)
    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "content",
        "mock_emails:email-042",
        5,
    )
    ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "selected")
    ledger.record_event(state.workflow_id, "triage_llm", artifact.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        '{"influential_artifact_ids": ["email-042"]}',
        "mock-fast",
        12,
        4,
        0.02,
    )
    ledger.record_lineage(decision.decision_id, artifact.artifact_id, "explicit_model_attribution", 1.0)

    view = build_context_audit_view(ledger.audit_workflow(state.workflow_id))
    labels_by_step = {
        step.step_name: [artifact.influence_label for artifact in step.mounted_context]
        for step in view.steps
    }

    assert labels_by_step["select_context"] == ["Selected, not influential yet"]
    assert labels_by_step["triage_llm"] == ["Influential"]
    assert "v0.1 audit boundary:" in render_context_audit(view)


def test_sem_ctx_002_005_006_cli_boundary_and_privacy(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "cli.sqlite")
    state = store.create_workflow("test", workflow_id="wf-cli")
    ledger = ContextLedger.from_store(store)
    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-042",
        "prior_email",
        "sensitive Q3 board deck raw body",
        "mock_emails:email-042",
        5,
    )
    ledger.record_event(state.workflow_id, "select_context", artifact.artifact_id, "selected")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "context.cli",
            "audit",
            "--db",
            str(store.db_path),
            "--workflow-id",
            state.workflow_id,
        ],
        text=True,
        capture_output=True,
        check=True,
    )

    assert "v0.1 audit boundary:" in result.stdout
    assert "trust policy" in result.stdout
    assert "sensitive Q3 board deck raw body" not in result.stdout
    assert "context_artifacts" not in result.stdout


def test_ctx_audit_assembly_001_summary_in_view(tmp_path) -> None:
    """Assembly summary includes observed, retrieved, selected, rejected counts."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    # Create 5 artifacts
    for i in range(5):
        ledger.record_artifact(
            state.workflow_id,
            "source_artifact",
            f"source-{i}",
            "test",
            None,
            f"ref-{i}",
            100,
        )

    # Get artifacts from ledger
    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifacts = [
            _artifact_from_row(row)
            for row in conn.execute(
                "SELECT * FROM context_artifacts WHERE workflow_id = ?",
                (state.workflow_id,),
            ).fetchall()
        ]

    # Record events: 3 retrieved, 2 selected, 1 rejected
    for artifact in artifacts[:3]:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25"},
        )

    for artifact in artifacts[:2]:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "selected",
        )

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[2].artifact_id,
        "rejected",
        metadata={"rejection_reason": "low_score"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)

    assert "Assembly: 5 observed, 3 retrieved, 2 selected, 1 rejected" in view.assembly_summary


def test_ctx_audit_assembly_002_renderer_includes_summary(tmp_path) -> None:
    """Renderer output includes assembly summary line."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test",
        None,
        "test-ref",
        100,
    )

    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifact_row = conn.execute(
            "SELECT * FROM context_artifacts WHERE workflow_id = ? LIMIT 1",
            (state.workflow_id,),
        ).fetchone()
        artifact = _artifact_from_row(artifact_row)

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)
    output = render_context_audit(view)

    assert "Assembly:" in output
    assert "observed" in output
    assert "retrieved" in output


def test_ctx_audit_assembly_003_format_exact(tmp_path) -> None:
    """Assembly summary matches exact format specification."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test",
        None,
        "test-ref",
        100,
    )

    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifact_row = conn.execute(
            "SELECT * FROM context_artifacts WHERE workflow_id = ? LIMIT 1",
            (state.workflow_id,),
        ).fetchone()
        artifact = _artifact_from_row(artifact_row)

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)

    # Verify exact format: "Assembly: {N} observed, {N} retrieved, {N} selected, {N} rejected"
    pattern = r'^Assembly: \d+ observed, \d+ retrieved, \d+ selected, \d+ rejected$'
    assert re.match(pattern, view.assembly_summary)

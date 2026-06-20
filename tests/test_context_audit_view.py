from __future__ import annotations

import inspect
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

"""Tests for the generic context-exporter hook in WorkflowEngine.

Verifies the engine fans out to ``dependencies["context_exporters"]`` after
context decision linking (spec §10.3) and at completion, swallows exporter
failures, and that the protocol lives in core without importing LangSmith.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from context.ledger import ContextLedger
from src.engine import ContextExporter, WorkflowEngine
from src.store import StepResult, WorkflowStore
from src.telemetry import TelemetryLogger


class _RecordingExporter:
    def __init__(self) -> None:
        self.incremental: list[tuple[str, str]] = []
        self.final: list[str] = []
        self.raise_on_increment = False

    def export_incremental(self, *, workflow_id: str, step_name: str, context_ledger: Any) -> None:
        if self.raise_on_increment:
            raise RuntimeError("exporter boom")
        self.incremental.append((workflow_id, step_name))

    def export_final(self, *, workflow_id: str, context_ledger: Any) -> None:
        self.final.append(workflow_id)


def _pass_step(name: str):
    def _fn(state, data, deps):  # noqa: ANN001
        return StepResult(name, {"ok": True}, duration_ms=1.0)

    return _fn


def test_context_export_protocol_is_runtime_checkable() -> None:
    assert isinstance(_RecordingExporter(), ContextExporter)


def test_engine_calls_incremental_export_after_each_step(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.sqlite")
    ledger = ContextLedger.from_store(store)
    exporter = _RecordingExporter()
    engine = WorkflowEngine(
        store,
        TelemetryLogger(echo=False),
        dependencies={"context_ledger": ledger, "context_exporters": [exporter]},
    )
    engine.register_steps([("a", _pass_step("a")), ("b", _pass_step("b"))])
    state = store.create_workflow("wf-exp")
    engine.execute(state.workflow_id)
    assert exporter.incremental == [(state.workflow_id, "a"), (state.workflow_id, "b")]
    assert exporter.final == [state.workflow_id]


def test_engine_runs_without_context_exporters_unchanged(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.sqlite")
    engine = WorkflowEngine(store, TelemetryLogger(echo=False))
    engine.register_steps([("a", _pass_step("a"))])
    state = store.create_workflow("wf-plain")
    result = engine.execute(state.workflow_id)
    assert result.status.value == "completed"


def test_engine_swallows_exporter_failures(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.sqlite")
    ledger = ContextLedger.from_store(store)
    exporter = _RecordingExporter()
    exporter.raise_on_increment = True
    engine = WorkflowEngine(
        store,
        TelemetryLogger(echo=False),
        dependencies={"context_ledger": ledger, "context_exporters": [exporter]},
    )
    engine.register_steps([("a", _pass_step("a"))])
    state = store.create_workflow("wf-fail")
    # Must not raise despite the exporter throwing.
    result = engine.execute(state.workflow_id)
    assert result.status.value == "completed"


def test_engine_does_not_call_exporters_without_ledger(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "w.sqlite")
    exporter = _RecordingExporter()
    engine = WorkflowEngine(
        store,
        TelemetryLogger(echo=False),
        dependencies={"context_exporters": [exporter]},  # no context_ledger
    )
    engine.register_steps([("a", _pass_step("a"))])
    state = store.create_workflow("wf-noledger")
    engine.execute(state.workflow_id)
    assert exporter.incremental == []
    assert exporter.final == []

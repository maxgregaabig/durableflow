"""Shared helpers for CLEAR factory tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from factory import ClearConfig, ClearWorkflow
from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStore
from src.telemetry import TelemetryLogger


def make_engine(
    tmp_path: Path,
    *,
    workspace_root: Path | None = None,
    config: ClearConfig | None = None,
    register_context_ledger: bool = False,
    **config_overrides: Any,
) -> tuple[WorkflowEngine, WorkflowStore, ApprovalGate, Path, ClearWorkflow]:
    """Build a fully wired engine + ClearWorkflow for ad-hoc tests.

    ``config_overrides`` are forwarded to :class:`ClearConfig` (e.g.
    ``force_failure_phase=1``, ``max_attempts=1``, ``plan_md=...``) when no
    explicit ``config`` is supplied.
    """
    store = WorkflowStore(tmp_path / "clear.sqlite")
    approval = ApprovalGate(store)
    ws_root = workspace_root or (tmp_path / "ws")
    ws_root.mkdir(parents=True, exist_ok=True)

    deps: dict[str, Any] = {"store": store, "approval_gate": approval}
    if register_context_ledger:
        from context.ledger import ContextLedger

        deps["context_ledger"] = ContextLedger.from_store(store)

    eng = WorkflowEngine(store, TelemetryLogger(echo=False), deps)
    cfg = config if config is not None else ClearConfig(workspace_root=ws_root, **config_overrides)
    wf = ClearWorkflow(cfg)
    wf.register(eng)
    return eng, store, approval, ws_root, wf

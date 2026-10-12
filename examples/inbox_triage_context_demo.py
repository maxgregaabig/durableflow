from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context import ContextLedger, build_context_audit_view, render_context_audit
from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


def main() -> None:
    db_path = ROOT / "examples" / "inbox_triage_context_demo.sqlite"
    if db_path.exists():
        db_path.unlink()
    telemetry_path = db_path.with_suffix(".telemetry.jsonl")
    if telemetry_path.exists():
        telemetry_path.unlink()

    store = WorkflowStore(db_path)
    approval = ApprovalGate(store)
    ledger = ContextLedger.from_store(store)
    telemetry = TelemetryLogger(path=telemetry_path, echo=False)
    workflow = InboxTriageWorkflow(store, approval_gate=approval, context_ledger=ledger)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)

    state = store.create_workflow("inbox_triage", workflow_id="wf-context-demo")
    state = engine.execute(state.workflow_id)
    pending = approval.list_pending()
    if pending:
        approval.approve(pending[0].gate_id, decided_by="context-demo")
        state = engine.resume(state.workflow_id)

    print(f"[engine] workflow {state.workflow_id} {state.status.value}")
    print(f"[audit] sqlite:    {db_path}")
    print(f"[audit] telemetry: {telemetry_path}")
    print()
    print(render_context_audit(build_context_audit_view(ledger.audit_workflow(state.workflow_id))))


if __name__ == "__main__":
    main()

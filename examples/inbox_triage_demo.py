from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


def build_runtime(db_path: Path) -> tuple[WorkflowStore, ApprovalGate, WorkflowEngine, TelemetryLogger]:
    store = WorkflowStore(db_path)
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    telemetry = TelemetryLogger(path=db_path.with_suffix(".telemetry.jsonl"), echo=False)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    return store, approval, engine, telemetry


def main() -> None:
    db_path = ROOT / "examples" / "inbox_triage_demo.sqlite"
    if db_path.exists():
        db_path.unlink()
    store, approval, engine, telemetry = build_runtime(db_path)
    state = store.create_workflow("inbox_triage", workflow_id="wf-inbox-demo")

    print(f"[engine] workflow {state.workflow_id} started")
    state = engine.execute(state.workflow_id)
    for result in store.step_results(state.workflow_id):
        if result["step_name"] == "approval_gate" and result["output"].get("pending"):
            print("[engine] step: approval_gate ...... paused (awaiting approval)")
        else:
            print(
                f"[engine] step: {result['step_name']:<18} complete "
                f"({result['duration_ms']:.0f}ms, ${result['cost_usd']:.4f})"
            )

    pending = approval.list_pending()
    if pending:
        request = pending[0]
        print("[approval] draft reply:")
        print(request.payload["draft"])
        decision = input("[approval] approve draft? [y/N] ").strip().lower()
        if decision == "y":
            approval.approve(request.gate_id, decided_by="demo-operator")
            state = engine.resume(state.workflow_id)
            print("[engine] step: approval_gate ...... approved")
            send = store.step_results(state.workflow_id)[-1]
            print(
                f"[engine] step: {send['step_name']:<18} complete "
                f"({send['duration_ms']:.0f}ms, ${send['cost_usd']:.4f})"
            )
        else:
            approval.reject(request.gate_id, "operator rejected in demo", decided_by="demo-operator")
            state = engine.resume(state.workflow_id)

    print(f"[engine] workflow {state.workflow_id} {state.status.value}")
    step_rows = store.step_results(state.workflow_id)
    unique_steps = {row["step_name"] for row in step_rows}
    total_cost = sum(float(row["cost_usd"]) for row in step_rows)
    total_latency = sum(float(row["duration_ms"]) for row in step_rows)
    summary = telemetry.summarize_workflow(state.workflow_id)
    print("\n--- summary ---")
    print(f"total steps:     {len(unique_steps)}")
    print(f"total cost:      ${total_cost:.4f}")
    print(f"total latency:   {total_latency:.0f}ms")
    print(f"fallbacks:       {summary['fallback_count']}")
    print(f"telemetry:       {db_path.with_suffix('.telemetry.jsonl')}")

    if state.status == WorkflowStatus.REJECTED:
        print("send skipped after rejection")


if __name__ == "__main__":
    main()

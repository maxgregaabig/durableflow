from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.approval import ApprovalGate
from src.engine import WorkflowEngine
from src.store import WorkflowStore
from src.telemetry import TelemetryLogger
from src.workflows import InboxTriageWorkflow


DB_PATH = ROOT / "examples" / "crash_resume_demo.sqlite"


def build_runtime(echo_telemetry: bool = False) -> tuple[WorkflowStore, ApprovalGate, WorkflowEngine, TelemetryLogger]:
    store = WorkflowStore(DB_PATH)
    approval = ApprovalGate(store)
    workflow = InboxTriageWorkflow(store, approval_gate=approval)
    telemetry = TelemetryLogger(path=DB_PATH.with_suffix(".telemetry.jsonl"), echo=echo_telemetry)
    engine = WorkflowEngine(store, telemetry, workflow.dependencies())
    workflow.register(engine)
    return store, approval, engine, telemetry


def remove_demo_artifacts() -> None:
    for path in [
        DB_PATH,
        DB_PATH.with_name(DB_PATH.name + "-wal"),
        DB_PATH.with_name(DB_PATH.name + "-shm"),
        DB_PATH.with_suffix(".telemetry.jsonl"),
    ]:
        if path.exists():
            path.unlink()


def child_crash() -> None:
    store, _approval, engine, _telemetry = build_runtime()
    if not DB_PATH.exists():
        store.create_workflow("inbox_triage", workflow_id="wf-001")

    def crash_during_triage(state, step_data, dependencies):
        for result in store.step_results("wf-001"):
            print(
                f"[engine] step: {result['step_name']:<18} complete "
                f"({result['duration_ms']:.0f}ms, ${result['cost_usd']:.4f})",
                flush=True,
            )
        print("[engine] step: triage_llm ............ started", flush=True)
        print(f"[crash]  simulated process crash (PID {os.getpid()})", flush=True)
        os._exit(1)

    engine.replace_step("triage_llm", crash_during_triage)
    print("[engine] workflow wf-001 started", flush=True)
    engine.execute("wf-001")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--child-crash":
        child_crash()
        return

    remove_demo_artifacts()

    store = WorkflowStore(DB_PATH)
    store.create_workflow("inbox_triage", workflow_id="wf-001")
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child-crash"],
        check=False,
        text=True,
        capture_output=True,
    )
    print(child.stdout, end="")
    if child.returncode == 0:
        raise RuntimeError("crash child unexpectedly exited successfully")

    print("\n--- restarting engine ---\n")
    store, approval, engine, telemetry = build_runtime()
    store.mark_stale_for_demo("wf-001", seconds_old=120)
    crashed = engine.recover_crashed(stale_after_seconds=30)
    for state in crashed:
        last_step = engine.steps[state.current_step] if state.current_step >= 0 else "none"
        next_step = engine.steps[state.current_step + 1]
        print(f"[engine] detected crashed workflow {state.workflow_id} (last checkpoint: {last_step})")
        print(f"[engine] resuming {state.workflow_id} from step: {next_step}")

    state = engine.resume("wf-001")
    printed = {row["step_name"] for row in store.step_results("wf-001")[:2]}
    for result in store.step_results("wf-001"):
        if result["step_name"] in printed and result["step_index"] < 2:
            continue
        if result["step_name"] == "approval_gate" and result["output"].get("pending"):
            print("[engine] step: approval_gate ...... paused (awaiting approval)")
        elif result["step_name"] not in {"ingest_email", "select_context"}:
            print(
                f"[engine] step: {result['step_name']:<18} complete "
                f"({result['duration_ms']:.0f}ms, ${result['cost_usd']:.4f})"
            )

    pending = approval.list_pending()
    if pending:
        print("[approval] auto-approving for demo")
        approval.approve(pending[0].gate_id, decided_by="crash-demo")
        state = engine.resume("wf-001")
        print("[engine] step: approval_gate ...... approved")
        send = store.step_results("wf-001")[-1]
        print(
            f"[engine] step: {send['step_name']:<18} complete "
            f"({send['duration_ms']:.0f}ms, ${send['cost_usd']:.4f})"
        )

    print(f"[engine] workflow {state.workflow_id} complete")
    step_rows = store.step_results("wf-001")
    unique_steps = {row["step_name"] for row in step_rows}
    total_cost = sum(float(row["cost_usd"]) for row in step_rows)
    total_latency = sum(float(row["duration_ms"]) for row in step_rows)
    summary = telemetry.summarize_workflow("wf-001")
    print("\n--- summary ---")
    print(f"total steps:     {len(unique_steps)}")
    print(f"total cost:      ${total_cost:.4f}")
    print(f"total latency:   {total_latency:.0f}ms")
    print(f"fallbacks:       {summary['fallback_count']}")
    print(f"crash recoveries: {summary['crash_recoveries']}")


if __name__ == "__main__":
    main()

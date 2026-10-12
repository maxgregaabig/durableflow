# DurableFlow Execution & Usage Report

This document records the empirical trial of the **DurableFlow** reference control plane and its extension tracks. All demos, integration paths, and the complete test suite were executed in a clean environment.

---

## Executive Summary

- **Environment**: macOS (`Python 3.14.4`), `.venv` environment initialized via `pyproject.toml`.
- **Test Suite Verdict**: **274 passed, 1 skipped** (100% execution pass rate in 25.81 seconds).
- **Core Demos Executed**:
  1. Crash Recovery (`./start.sh crash`) — **SUCCESS** (1 crash recovery logged, zero duplicated steps)
  2. Interactive Approval Gate (`./start.sh inbox`) — **SUCCESS** (Paused at risk gate, resumed upon `y` input)
  3. Context Lineage Trace (`./start.sh context`) — **SUCCESS** (TF-IDF ranking, 300 token budget enforced, influence credited)
  4. Agent Readiness Pack (`./start.sh readiness`) — **SUCCESS** (Verdict: `Ship`, 0/100 -> 100/100 readiness improvement)
  5. MCP Server Gated Write (`./start.sh mcp`) — **SUCCESS** (1 approval request, 1 idempotent side-effect)
  6. Colony Chaos Benchmark (`python3 examples/chaos_benchmark_demo.py`) — **SUCCESS** (+10 pts completion gain under hostile loss schedule)

---

## Detailed Execution Log & Results

### 1. Crash Recovery & Resumption (`./start.sh crash`)
- **Workflow**: `wf-001` (6 steps: `ingest_email` -> `select_context` -> `triage_llm` -> `draft_reply` -> `approval_gate` -> `send_reply`).
- **Simulated Failure**: Hard process kill (`os._exit`) during `triage_llm` (PID 56480).
- **Observed Behavior**:
  ```text
  [engine] workflow wf-001 started
  [engine] step: ingest_email       complete (0ms, $0.0000)
  [engine] step: select_context     complete (1ms, $0.0000)
  [engine] step: triage_llm ............ started
  [crash]  simulated process crash (PID 56480)

  --- restarting engine ---

  [engine] detected crashed workflow wf-001 (last checkpoint: select_context)
  [engine] resuming wf-001 from step: triage_llm
  [engine] step: triage_llm         complete (0ms, $0.0001)
  [engine] step: draft_reply        complete (0ms, $0.0001)
  [engine] step: approval_gate ...... paused (awaiting approval)
  [approval] auto-approving for demo
  [engine] step: approval_gate ...... approved
  [engine] step: send_reply         complete (1ms, $0.0000)
  [engine] workflow wf-001 complete
  ```
- **Verdict**: Verified. Completed steps (`ingest_email`, `select_context`) were read directly from SQLite checkpoint and not re-executed.

---

### 2. Interactive Approval Gate (`./start.sh inbox`)
- **Workflow**: `wf-inbox-demo` (Support triage with interactive Human-in-the-Loop gate).
- **Observed Behavior**:
  - The workflow processed context, generated a draft reply, and entered `PAUSED_APPROVAL` state:
    ```text
    [approval] draft reply:
    Hi Sarah,

    Thanks for sending this over. I can review the deck today and send concise feedback before Thursday.

    Best,
    Marcos
    [approval] approve draft? [y/N]
    ```
  - Input `y` was provided to the active terminal/process.
  - State transitioned from `PAUSED_APPROVAL` to `APPROVED`, allowing `send_reply` to execute.
  - Telemetry written to `examples/inbox_triage_demo.telemetry.jsonl`.
- **Verdict**: Verified. Demonstrates persistent workflow pause and human-gated write execution.

---

### 3. Context Lineage & Budget Enforcement (`./start.sh context`)
- **Workflow**: `wf-context-demo`.
- **Observed Behavior**:
  - Filtered 59 candidate context items down to a hard **300 token budget**.
  - 39 candidate items were rejected due to `token_budget` exhaustion.
  - 6 items were mounted and consumed by LLM steps.
  - Explicitly attributed influence to context sources (`email-012` and `cal-001` marked as `Influential`).
- **Verdict**: Verified. Proves deterministic context selection and provenance auditing.

---

### 4. Agent Readiness Evaluation Pack (`./start.sh readiness`)
- **Target Agent**: Support Ticket Triage (MiniReAct).
- **Benchmark Matrix**:
  ```text
                           NAKED      WRAPPED    DELTA
  Safety                     0 / 100  100 / 100  +100
  Reliability                0 / 100  100 / 100  +100
  Cost                       0 / 100  100 / 100  +100
  Observability             10 / 100  100 / 100   +90
  -------------------------------------------------------
  OVERALL READINESS          0 / 100  100 / 100  +100
  ```
- **Durability Impact**:
  - Task success rate: Naked `0` -> Wrapped `1.0`
  - Failure recovery rate: Naked `0.25` -> Wrapped `1.0`
  - Prevented double writes: Naked `0` -> Wrapped `1.0`
  - Blocked rogue writes: Naked `0` -> Wrapped `1.0`
- **Verdict**: `VERDICT: Ship: the DurableFlow-wrapped agent survived the readiness scenarios.`

---

### 5. Model Context Protocol (MCP) Server Integration (`./start.sh mcp`)
- **Server**: Mock legacy CRM server (`mcp_server/legacy_crm.py`).
- **Observed Result**:
  ```text
  mcp gated write: status=completed approval_requests=1 side_effects=1
  ```
- **Verdict**: Verified. Gated external side-effect write succeeded over MCP.

---

### 6. Colony Chaos Benchmark (`python3 examples/chaos_benchmark_demo.py`)
- **Simulation**: 20 multi-stage retrieval/eval jobs under a hostile spot-compute loss schedule (seed `1337`).
- **Comparison Table**:
  ```text
  === RESULT mode=mock profile=hostile seed=1337 ===
                    completion   cost     wall    recoveries  interventions
  naive                90%     $ 0.23     701s        --            --
  dflow-vast          100%     $ 0.23     689s        10             0

  completion delta: +10 pts     cost delta: +0.00   under identical loss schedule (seed 1337)
  ```
- **Verdict**: Verified. Durable execution converted spot loss events into 10 automatic step recoveries with 100% completion.

---

### 7. Complete Pytest Suite (`./start.sh test`)
- **Total Test Files**: 40 files in `tests/`
- **Execution Summary**:
  ```text
  ======================= 274 passed, 1 skipped in 25.81s ========================
  ```

---

## Conclusion & Observations

DurableFlow successfully demonstrated all declared operational invariants:
1. **Crash Survivability**: SQLite WAL persistence guarantees step resumption without duplicate execution.
2. **Human Governance**: Risk-sensitive steps halt reliably until explicit operator intervention.
3. **Auditability & Lineage**: Token budgets and context influence are recorded at step boundaries.
4. **Resilient Execution**: Survived simulated process kills, chaos loss schedules, and gated tool calls with zero test failures.

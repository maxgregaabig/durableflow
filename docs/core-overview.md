# DurableFlow Core: Architecture & Mental Model

> **The Throughline:** Most agent demos optimize for *intelligence* (prompts, tool calling, reasoning loops). **DurableFlow** is an educational lab and reference runtime that optimizes for *survivability and inspectability* — the operational mechanics needed to ensure multi-step LLM workflows survive process crashes, model outages, context window limits, human approval pauses, and duplicate side effects.
>
> *(Based on the architectural throughline in [walkthrough.md](walkthrough.md) and the staged curriculum in [learning-path.md](learning-path.md). This document covers **the core runtime** in `src/`, excluding extensions like Colony, Readiness, Context lineage, or Planner.)*

---

## 1. The Core Spine: 3 Invariants

Everything in the DurableFlow core hangs off three load-bearing operational invariants:

```mermaid
flowchart TD
    subgraph S1 ["1. The Checkpoint (Stage 1)"]
        direction TB
        C1["<b>Atomic SQLite Transaction</b><br/>• Append row to <code>step_results</code><br/>• Update <code>workflows.current_step = index</code><br/>• Merge step output into <code>workflows.step_data</code> JSON"]
        C2["<b>Guaranteed Bound:</b><br/>Failure costs at most 1 step, not the whole run.<br/>Resume starts at <code>current_step + 1</code>."]
        C1 --> C2
    end

    subgraph S2 ["2. Two Status Layers (Stage 2)"]
        direction TB
        L1["<b>Execution State:</b> <code>workflows.status</code><br/>(<code>pending</code> → <code>running</code> → <code>paused_approval</code> → <code>completed</code>)"]
        L2["<b>Human Decision State:</b> <code>approval_queue.status</code><br/>(<code>pending</code> → <code>approved</code> / <code>rejected</code>)"]
        L3["<b>Decoupled Progression:</b><br/>Operator calling <code>approve()</code> only updates the queue row.<br/>The workflow resumes only when <code>engine.resume()</code> is called."]
        L1 <--> L2
        L2 --> L3
    end

    subgraph S3 ["3. The Crash Window & Replay Guard (Stage 3)"]
        direction TB
        W1["<b>The Window:</b><br/><code>remote effect happens ────> local checkpoint commits</code><br/>(Crash can occur mid-send)"]
        W2["<b>Replay Suppression:</b><br/>Deterministic SHA-256 key in <code>side_effect_log</code>.<br/>Retries reuse logged result rather than double-sending."]
        W1 --> W2
    end
```

---

## 2. High-Level Core Architecture

The core runtime sits between user/driver code and durable SQLite storage:

```mermaid
flowchart TD
    %% DRIVERS
    subgraph Drivers ["1. Drivers & Entry Points (examples/)"]
        CrashDemo["<b>Crash Demo</b> (crash_resume_demo.py)<br/>• Subprocess real <code>os._exit</code> kill<br/>• Stale detection & resume from checkpoint"]
        InboxDemo["<b>Inbox Demo</b> (inbox_triage_demo.py)<br/>• Golden path & interactive HITL<br/>• Approval vs rejection branches"]
        Tests["<b>Pytest Suite</b> (tests/)<br/>• Deterministic local fixtures<br/>• Zero API keys required"]
    end

    %% RUNTIME
    subgraph CoreRuntime ["2. Core Durable Runtime (src/)"]
        direction TB
        Engine["<b>WorkflowEngine</b> (src/engine.py)<br/>• Linear step runner (0 … N)<br/>• Step registration (<code>register_step</code>)<br/>• Durable checkpoint coordination<br/>• Pause / resume orchestrator"]

        subgraph Primitives ["6 Core Operational Primitives"]
            direction LR
            Context["<b>ContextSelector</b><br/>(src/context_selector.py)<br/>• TF-IDF relevance scoring<br/>• Hard token budget packing"]
            Router["<b>ModelRouter</b><br/>(src/model_router.py)<br/>• Primary / Secondary fallback<br/>• USD cost & token tracking"]
            Approval["<b>ApprovalGate</b><br/>(src/approval.py)<br/>• Human-in-the-Loop (HITL)<br/>• Two-phase state separation"]
            Idempotency["<b>Idempotency Guard</b><br/>(src/workflows.py)<br/>• SHA-256 key hashing<br/>• Local replay suppression"]
        end

        Telemetry["<b>TelemetryLogger</b> (src/telemetry.py)<br/>• Structured JSONL audit events<br/>• Step, fallback, approval & crash logs"]
    end

    %% PERSISTENCE
    subgraph Storage ["3. Durable Persistence Layer (SQLite WAL - src/store.py)"]
        Store["<b>WorkflowStore</b><br/>(Single Source of Truth — Zero In-Memory Only State)"]
        subgraph Tables ["4 Core SQLite Tables"]
            T_WF[("<b>workflows</b><br/>workflow_id (PK)<br/>current_step (last completed index)<br/>step_data (accumulated JSON)<br/>status (running/paused/completed)")]
            T_SR[("<b>step_results</b><br/>id (PK), workflow_id (FK)<br/>step_index, step_name, output JSON<br/>duration_ms, cost_usd, model_used")]
            T_AQ[("<b>approval_queue</b><br/>gate_id (PK), workflow_id (FK)<br/>step_name, payload JSON<br/>status (pending/approved/rejected)")]
            T_SE[("<b>side_effect_log</b><br/>idempotency_key (PK)<br/>workflow_id (FK), step_name<br/>result JSON, executed_at")]
        end
    end

    %% REFERENCE VEHICLE
    subgraph ReferenceWorkflow ["4. Reference Vehicle: Inbox Triage Workflow (src/workflows.py)"]
        direction LR
        S0["Step 0<br/><b>ingest_email</b>"] --> S1["Step 1<br/><b>select_context</b>"]
        S1 --> S2["Step 2<br/><b>triage_llm</b>"]
        S2 --> S3["Step 3<br/><b>draft_reply</b>"]
        S3 --> S4["Step 4<br/><b>approval_gate</b>"]
        S4 --> S5["Step 5<br/><b>send_reply</b>"]
    end

    %% CONNECTIONS
    Drivers --> Engine
    Engine --> ReferenceWorkflow

    S1 -. uses .-> Context
    S2 -. uses .-> Router
    S3 -. uses .-> Router
    S4 -. uses .-> Approval
    S5 -. uses .-> Idempotency

    Engine --> Store
    Approval --> Store
    Idempotency --> Store
    Engine --> Telemetry

    Store --> T_WF
    Store --> T_SR
    Store --> T_AQ
    Store --> T_SE
```

---

## 3. Step Execution & Survivability Lifecycle

The runtime processes registered steps sequentially. If a step pauses for approval or if the process dies mid-execution, state is preserved in SQLite:

```mermaid
flowchart TD
    Start([Execute / Resume Workflow]) --> LoadState["Load Workflow State from SQLite<br/>(current_step index N, default -1)"]
    LoadState --> Advance["Advance to Step N + 1"]
    
    subgraph StepLoop ["Step Execution & Operational Guards"]
        direction TB
        NeedContext{"Requires Context?"}
        NeedContext -- Yes --> BudgetContext["<b>ContextSelector:</b><br/>TF-IDF rank & greedily pack<br/>under caller token budget (e.g. 300)"]
        NeedContext -- No --> NeedLLM
        BudgetContext --> NeedLLM{"Requires LLM Call?"}
        
        NeedLLM -- Yes --> CallPrimary["<b>ModelRouter:</b><br/>Call primary model provider"]
        CallPrimary --> PrimaryOK{"Primary Success?"}
        PrimaryOK -- Yes --> CalcCost["Record tokens & USD cost"]
        PrimaryOK -- No (Timeout / 5xx) --> CallFallback["Fallback to secondary model<br/>(Log fallback telemetry event)"]
        CallFallback --> CalcCost
        NeedLLM -- No --> NeedGate
        CalcCost --> NeedGate{"Requires Human Gate?"}

        NeedGate -- Yes --> RequestApproval["<b>ApprovalGate:</b><br/>Insert pending row in approval_queue"]
        RequestApproval --> PauseFlow["Return <code>PauseForApproval</code><br/>Checkpoint pending result at Step N+1<br/>Set workflows.status = paused_approval"]
        
        NeedGate -- No --> NeedSideEffect{"External Side Effect?"}
        
        NeedSideEffect -- Yes --> HashKey["Compute SHA-256 Idempotency Key:<br/><code>sha256(workflow_id:step_name:payload_hash)</code>"]
        HashKey --> KeyInLog{"Key in side_effect_log?"}
        KeyInLog -- Yes --> ReplaySkip["<b>Replay Suppressed:</b><br/>Return cached result (no new network call)"]
        KeyInLog -- No --> ExecAction["Execute mock action once &<br/>write row to side_effect_log"]
        NeedSideEffect -- No --> ReturnResult["Produce StepResult"]
        ReplaySkip --> ReturnResult
        ExecAction --> ReturnResult
    end

    Advance --> StepLoop

    PauseFlow --> PausedState[("<b>Workflow Paused in SQLite</b><br/>Process can safely terminate or sleep")]
    PausedState --> OperatorAction["Operator inspects payload & calls<br/><code>ApprovalGate.approve()</code> or <code>reject()</code>"]
    OperatorAction --> ResumeCall["<code>WorkflowEngine.resume(workflow_id)</code>"]
    ResumeCall --> Advance

    ReturnResult --> Checkpoint["<b>Durable Checkpoint (Atomic Transaction):</b><br/>1. Insert row into <code>step_results</code><br/>2. Update <code>workflows.current_step = N + 1</code><br/>3. Merge output into <code>workflows.step_data</code> JSON<br/>4. Emit <code>step_complete</code> JSONL telemetry"]

    Checkpoint --> HasMore{"More steps registered?"}
    HasMore -- Yes --> Advance
    HasMore -- No --> Done([Set status = COMPLETED])

    subgraph CrashRecovery ["Process Crash Resilience Boundary"]
        CrashEvent["💥 <b>Process Crash</b> (os._exit / SIGKILL / Reboot)"] -.-> DetectStale["<code>WorkflowEngine.recover_crashed()</code><br/>Query stale running workflows in SQLite"]
        DetectStale -.-> ResumeCrash["<code>WorkflowEngine.resume()</code><br/>Resumes from last completed checkpoint<br/><b>Completed steps (0…N) are NEVER re-run</b>"]
        ResumeCrash -.-> LoadState
    end
```

---

## 4. Following One Run: State Evolution

Tracing an action-required email through the 6-step reference workflow (`InboxTriageWorkflow`):

| Moment | `current_step` | Workflow Status | SQLite Durable Evidence | What Happens Next |
|---|:---:|---|---|---|
| **Created** | `-1` | `pending` | Initial input in `step_data` JSON | `execute()` marks it `running` |
| **Steps 0–3 Finished** (`ingest_email` → `draft_reply`) | `3` | `running` | 4 rows in `step_results`; outputs in `step_data` | Step 4 (`approval_gate`) runs |
| **Approval Requested** | `4` | `paused_approval` | Pending gate in `approval_queue`; **1st result at step 4** (`pending: true`) | Engine returns; process may exit |
| **Operator Approves** | `4` | `paused_approval` | `approval_queue.status = approved` (with actor/time) | `resume()` reads the queue decision |
| **Engine Resumes** | `4` | `approved → running` | **2nd result at step 4** (`approved: true`); updates `step_data` | Step 5 (`send_reply`) runs |
| **Mock Send Finished** | `5` | `completed` | Row in `side_effect_log`; send result checkpointed | Emits `workflow_complete` telemetry |

> [!NOTE]
> **Why Step Index 4 Appears Twice in `step_results`:**
> A pause is itself a durable event. Step index `4` records the pause when approval is requested, and appends the decided result when approved. `current_step` ends at `5` because all 6 steps (0 through 5) completed.

---

## 5. The 5 Questions Every Reviewer Can Answer

1. **What failure is DurableFlow designed to survive?**
   Process crashes (`os._exit`), transient model timeouts/5xx, context window overflows, operator delays during approval, and duplicate side effects on restart.
2. **What exactly is persisted after each step, and where?**
   Every completed step commits an atomic transaction: appends a row to `step_results`, updates `workflows.current_step`, merges output into `workflows.step_data` JSON, and logs JSONL telemetry.
3. **How do approval and side-effect state differ from execution state?**
   `workflows.status` tracks linear engine execution; `approval_queue.status` tracks operator decisions; `side_effect_log` tracks external idempotency keys. They move independently.
4. **Why is inbox triage the reference workflow rather than the product?**
   It exercises every operational primitive in one linear path (retrieval, model routing, human gate, side-effect). It is the reference vehicle, not the product.
5. **If a crash happens mid-step, what is lost?**
   Only the in-progress step is lost. All previous steps are frozen in SQLite and will never be re-executed when `resume()` is called.

---

## Related Documentation

- [Learning Path](learning-path.md) — The 9-stage curriculum to master the repo in dependency order.
- [Walkthrough & Index](walkthrough.md) — Comprehensive repository walkthrough and spec catalog.
- [Architecture Details](dflow-arch.md) — Subsystem diagrams, state machines, and invariants.
- [Agentic Loop](agent-loop.md) — How reason-act-observe loops bridge into `WorkflowEngine`.
- [Exercises](exercises.md) — Guided tasks for inspecting SQLite and testing fallback.

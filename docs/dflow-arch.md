# DurableFlow Architecture

Visual architecture for **Durable Flow**: Python stdlib, SQLite persistence, mock model providers by default, and CLI demos.

**Related docs:** [README](../README.md) (quick start) · [dflow-spec.md](dflow-spec.md) (requirements and acceptance criteria)

## How To Read This Document

Each section is a Mermaid diagram plus brief prose. The diagrams describe **what runs today**, not a production target.

**Two status layers.** Workflow progress lives in `workflows.status` (e.g. `paused_approval`, `running`, `completed`). Operator decisions live separately in `approval_queue.status` (`pending`, `approved`, `rejected`). Calling `ApprovalGate.approve()` or `reject()` updates the queue only; `WorkflowEngine.resume()` reads that decision and updates workflow status.

**Checkpoint semantics.** `workflows.current_step` is the **integer index** of the last completed step (0 = `ingest_email`, 1 = `select_context`, …). `execute()` and `resume()` continue at `current_step + 1`. Each completed step appends its output to `step_data` (JSON dict keyed by step name).

**Registration, not delegation.** `InboxTriageWorkflow.register(engine)` binds step functions onto `WorkflowEngine`. At runtime the engine invokes registered callables; it does not call a separate workflow service object.

**Demo-only helpers.** `WorkflowStore.mark_stale_for_demo()` and `WorkflowEngine.replace_step()` exist for the crash demo and tests. Production crash detection relies on stale `running` workflows; `replace_step()` injects failure without mutating private engine state.

## Core Invariants

1. **Checkpoint after every completed step** — `save_checkpoint()` writes to `step_results` and merges output into `step_data` before the next step runs.
2. **Pause on human gate** — a step returning `PauseForApproval` persists a pending checkpoint and sets `paused_approval`; execution stops until `resume()`.
3. **Idempotency before side effects** — `send_reply` checks `side_effect_log` before executing; duplicate keys return the logged result.
4. **Hard token budget** — `ContextSelector` never returns items whose summed `token_count` exceeds the budget (4096 in inbox triage).
5. **No in-memory-only workflow state** — all durable state lives in SQLite (`workflows`, `step_results`, `approval_queue`, `side_effect_log`).

SQLite uses WAL mode and `PRAGMA busy_timeout = 30000` for local durability. There is no concurrent multi-workflow execution in this reference runtime.

## System Context

```mermaid
flowchart LR
    Operator[Operator] --> CLI[CLI demos / start.sh]
    CLI --> Engine[WorkflowEngine]
    Engine --> Steps[Registered step functions]
    Steps --> WorkflowLogic[InboxTriageWorkflow methods]
    WorkflowLogic --> Selector[ContextSelector]
    WorkflowLogic --> Router[ModelRouter]
    WorkflowLogic --> Approval[ApprovalGate]
    WorkflowLogic --> Store[WorkflowStore]
    Engine --> Telemetry[TelemetryLogger]
    Store --> SQLite[(SQLite)]
    Approval --> SQLite
    Telemetry --> JSONL[telemetry JSONL]
    WorkflowLogic --> MockData[Mock email and calendar data]
    Router --> MockProviders[Mock model providers]
    Router -. optional .-> Anthropic[Anthropic API]
```

The engine orchestrates registered steps. Step bodies live on `InboxTriageWorkflow` and call selector, router, approval, and store through a shared dependencies dict (including telemetry injected by the engine).

## Extension Pattern

Sibling extension packages may use the fixed-step `WorkflowEngine` when their work naturally maps to registered steps, or they may wrap the lower-level `WorkflowStore` directly when their domain has its own execution loop. In both cases, extensions keep their schemas additive, store durable checkpoints through `WorkflowStore`, and use `TelemetryLogger.log_event()` for domain-specific events.

Current implemented examples follow both shapes: Readiness registers agent turns as deterministic workflow steps, while Colony adds `colony_*` tables and checkpoints job stages through `WorkflowStore.save_checkpoint()`. Draft extensions such as Target Planner should follow the same boundary: no core table rewrites, no hidden in-memory state, and no new claim in this architecture document until the implementation exists.

## Module Dependencies

```mermaid
flowchart TD
    Examples[examples/*.py] --> Engine[src/engine.py]
    Examples --> Store[src/store.py]
    Examples --> Workflows[src/workflows.py]
    Examples --> Approval[src/approval.py]
    Examples --> Telemetry[src/telemetry.py]

    Engine --> Store
    Engine --> Telemetry

    Workflows --> Store
    Workflows --> Approval
    Workflows --> Router[src/model_router.py]
    Workflows --> Selector[src/context_selector.py]

    Approval --> Store

    Tests[tests/*.py] --> Engine
    Tests --> Store
    Tests --> Workflows
    Tests --> Approval
    Tests --> Router
    Tests --> Selector
    Tests --> Telemetry
```

`engine.py` does not import `workflows.py`. Demos and tests construct `InboxTriageWorkflow`, call `register(engine)` to bind step functions, and pass `workflow.dependencies()` into the engine constructor.

## Inbox Triage Workflow

Step indices shown in parentheses. Checkpoints occur after each completed step.

```mermaid
flowchart TD
    Start([create_workflow]) --> Ingest[ingest_email index 0]
    Ingest --> CP0[(checkpoint)]
    CP0 --> Context[select_context index 1]
    Context --> CP1[(checkpoint)]
    CP1 --> Triage[triage_llm index 2]
    Triage --> CP2[(checkpoint)]
    CP2 --> Decision{classification action_required?}
    Decision -- no --> DraftSkip[draft_reply skipped index 3]
    Decision -- yes --> Draft[draft_reply index 3]
    Draft --> CP3[(checkpoint)]
    DraftSkip --> CP3
    CP3 --> HasDraft{draft present?}
    HasDraft -- no --> GateSkip[approval_gate skipped index 4]
    HasDraft -- yes --> GateRun[approval_gate index 4]
    GateRun --> NeedsHuman{PauseForApproval?}
    NeedsHuman -- yes --> Pause[workflows.status paused_approval]
    Pause --> Operator[operator approve or reject via ApprovalGate]
    Operator --> Resume[engine.resume]
    Resume --> ApprovedPath[checkpoint approval decision]
    ApprovedPath --> Send[send_reply index 5]
    GateSkip --> SendSkip[send_reply skipped index 5]
    Resume --> RejectedTerminal([workflows.status rejected])
    Send --> Idempotency[idempotency check]
    Idempotency --> SideEffect[(side_effect_log)]
    SideEffect --> Complete([workflows.status completed])
    SendSkip --> Complete
```

Informational or fyi messages skip draft, approval queue, and send. Rejection is recorded during `resume()`, not by re-entering `approval_gate`.

## Golden Path Sequence

Action-required email with operator approval before send.

```mermaid
sequenceDiagram
    participant Demo as inbox_triage_demo.py
    participant Engine as WorkflowEngine
    participant Steps as registered steps
    participant Selector as ContextSelector
    participant Router as ModelRouter
    participant Approval as ApprovalGate
    participant Store as WorkflowStore
    participant Telemetry as TelemetryLogger

    Demo->>Store: create_workflow("inbox_triage")
    Demo->>Engine: execute(workflow_id)
    Engine->>Telemetry: log_step_start(ingest_email)
    Engine->>Steps: ingest_email()
    Steps-->>Engine: StepResult(email)
    Engine->>Store: save_checkpoint(index 0)
    Engine->>Telemetry: log_step_complete()

    Engine->>Telemetry: log_step_start(select_context)
    Engine->>Steps: select_context()
    Steps->>Selector: select(query, corpus, budget=4096)
    Selector-->>Steps: ranked ContextItems
    Steps-->>Engine: StepResult(context)
    Engine->>Store: save_checkpoint(index 1)
    Engine->>Telemetry: log_step_complete()

    Engine->>Telemetry: log_step_start(triage_llm)
    Engine->>Steps: triage_llm()
    Steps->>Router: route(classification prompt)
    Router-->>Steps: ModelResponse
    Steps->>Telemetry: log_fallback() if was_fallback
    Steps-->>Engine: StepResult(classification)
    Engine->>Store: save_checkpoint(index 2)

    Engine->>Steps: draft_reply()
    Steps->>Router: route(draft prompt)
    Router-->>Steps: ModelResponse(draft)
    Steps->>Telemetry: log_fallback() if was_fallback
    Steps-->>Engine: StepResult(draft)
    Engine->>Store: save_checkpoint(index 3)

    Engine->>Steps: approval_gate()
    Steps->>Approval: request_approval(draft payload)
    Steps-->>Engine: PauseForApproval
    Engine->>Store: save_checkpoint(pending, index 4)
    Engine->>Store: update_status(paused_approval)
    Engine->>Telemetry: log_approval_request()

    Demo->>Approval: approve(gate_id)
    Note over Approval: approval_queue.status = approved<br/>workflows.status still paused_approval
    Demo->>Engine: resume(workflow_id)
    Engine->>Telemetry: log_resume(triage_llm successor step)
    Engine->>Store: save_checkpoint(approved, index 4)
    Engine->>Telemetry: log_approval_decision(approved)
    Engine->>Store: update_status(running)

    Engine->>Steps: send_reply()
    Steps->>Store: get_side_effect(idempotency_key)
    Steps->>Store: log_side_effect(result)
    Steps-->>Engine: StepResult(sent)
    Engine->>Store: save_checkpoint(index 5)
    Engine->>Store: update_status(completed)
    Engine->>Telemetry: log_workflow_complete()
```

## Crash Recovery Sequence

Process-level crash during `triage_llm` (index 2). Parent resumes at index 2, not from ingest.

```mermaid
sequenceDiagram
    participant Parent as crash_resume_demo parent
    participant Child as subprocess --child-crash
    participant Engine as WorkflowEngine
    participant Store as WorkflowStore
    participant Telemetry as TelemetryLogger

    Parent->>Store: create_workflow("wf-001")
    Parent->>Child: subprocess run
    Child->>Engine: replace_step(triage_llm, crash_fn)
    Child->>Engine: execute("wf-001")
    Engine->>Store: checkpoint index 0 ingest_email
    Engine->>Store: checkpoint index 1 select_context
    Child--xChild: os._exit(1) before triage checkpoint
    Note over Store: workflows.status still running<br/>current_step = 1

    Parent->>Store: mark_stale_for_demo (demo helper)
    Parent->>Engine: recover_crashed(stale_after_seconds=30)
    Engine->>Store: detect stale running workflow
    Store-->>Engine: status crashed, current_step index 1
    Engine->>Telemetry: log_crash(last_checkpoint=1)

    Parent->>Engine: resume("wf-001")
    Engine->>Store: load current_step=1, resume at index 2 triage_llm
    Engine->>Store: checkpoint remaining steps
    Engine->>Store: update_status(completed)
```

## Workflow State Machine

States in `workflows.status`. Approval queue updates are separate until `resume()` applies them.

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> running: execute()
    running --> paused_approval: PauseForApproval
    running --> completed: all steps finished
    running --> failed: uncaught step exception
    running --> crashed: detect_crashed stale running

    paused_approval --> running: resume after approve
    paused_approval --> rejected: resume after reject
    crashed --> running: resume()

    note right of paused_approval
        approve/reject updates approval_queue only.
        resume reads queue and sets
        workflows.status.
    end note

    completed --> [*]
    rejected --> [*]
    failed --> [*]
```

Brief intermediate `approved` on the workflow row may appear inside `_resume_index_after_approval()` before the next step runs; externally the workflow returns to `running`.

## Approval Gate

Two layers: gate queue (`approval_queue`) and workflow status (`workflows`).

```mermaid
flowchart TD
    DraftOut[draft_reply output] --> HasDraft{draft present?}
    HasDraft -- no --> SkipGate[approval_gate StepResult skipped]
    SkipGate --> SkipSend[send_reply skipped no queue entry]

    HasDraft -- yes --> Request[request_approval]
    Request --> Queue[(approval_queue status pending)]
    Request --> Pause[engine sets workflows.status paused_approval]

    Pause --> Operator{operator via ApprovalGate}
    Operator --> ApproveRow[approval_queue.status approved]
    Operator --> RejectRow[approval_queue.status rejected]

    ApproveRow --> ResumeApprove[engine.resume]
    RejectRow --> ResumeReject[engine.resume]

    ResumeApprove --> CheckpointApproved[checkpoint approval_gate approved]
    CheckpointApproved --> SendStep[send_reply]

    ResumeReject --> CheckpointRejected[checkpoint approval_gate rejected]
    CheckpointRejected --> Terminal([workflows.status rejected])
```

## SQLite Persistence Model

```mermaid
erDiagram
    workflows ||--o{ step_results : records
    workflows ||--o{ approval_queue : waits_on
    workflows ||--o{ side_effect_log : protects

    workflows {
        TEXT workflow_id PK
        TEXT workflow_type
        INTEGER current_step
        TEXT step_data
        TEXT status
        TEXT created_at
        TEXT updated_at
    }

    step_results {
        INTEGER id PK
        TEXT workflow_id FK
        INTEGER step_index
        TEXT step_name
        TEXT output
        REAL duration_ms
        REAL cost_usd
        TEXT model_used
        TEXT created_at
    }

    approval_queue {
        TEXT gate_id PK
        TEXT workflow_id FK
        TEXT step_name
        TEXT payload
        TEXT status
        TEXT requested_at
        TEXT decided_at
        TEXT decided_by
        TEXT rejection_reason
    }

    side_effect_log {
        TEXT idempotency_key PK
        TEXT workflow_id FK
        TEXT step_name
        TEXT result
        TEXT executed_at
    }
```

`step_data` is a JSON object accumulating each step's output by step name. `current_step` is the last completed step index.

## Model Routing And Fallback

Mock providers support `fail=True` and `mock_delay_seconds` exceeding `timeout_seconds` to simulate timeout. Real Anthropic calls use the SDK client timeout.

```mermaid
flowchart TD
    Prompt[Prompt + system message] --> Policy[RoutingPolicy]
    Policy --> Primary[Primary provider]
    Primary --> PrimaryOK{success?}
    PrimaryOK -- yes --> Cost1[estimate tokens and cost]
    PrimaryOK -- timeout --> TimeoutFB{fallback_on_timeout?}
    PrimaryOK -- error --> ErrorFB{fallback_on_error?}
    TimeoutFB -- no --> Error[ModelRoutingError]
    ErrorFB -- no --> Error
    PrimaryOK -- no --> Retry{retry_count left?}
    Retry -- yes --> Primary
    Retry -- no --> TimeoutFB
    TimeoutFB -- yes --> Secondary[Secondary provider]
    ErrorFB -- yes --> Secondary
    Secondary --> SecondaryOK{success?}
    SecondaryOK -- yes --> Cost2[estimate tokens and cost]
    SecondaryOK -- no --> Error
    Cost1 --> Response[ModelResponse was_fallback=false]
    Cost2 --> FallbackResponse[ModelResponse was_fallback=true]
    FallbackResponse --> WorkflowLog[InboxTriageWorkflow logs model_fallback via telemetry]
```

## Context Selection Under Token Budget

```mermaid
flowchart TD
    Query[Incoming email subject + body] --> Terms[Normalize terms]
    Corpus[Mock emails + calendar events] --> Items[ContextItem list]
    Items --> TokenCounts[Approximate token counts word_count / 0.75]
    Items --> Scores[TF-IDF relevance scores]
    Terms --> Scores
    Scores --> Sort[Sort by score descending]
    Sort --> Pack[Greedy budget packing]
    TokenCounts --> Pack
    Budget[4096 token budget in inbox triage] --> Pack
    Pack --> Selected[Selected context]
    Selected --> Constraint{sum token_count <= budget}
```

## Idempotent Send

Key format in code: `sha256("{workflow_id}:send_reply:{payload_hash}")`.

```mermaid
flowchart TD
    SendStep[send_reply] --> SkipCheck{draft or approval skipped?}
    SkipCheck -- yes --> NoOp[StepResult sent=false skipped]
    SkipCheck -- no --> Payload[Build outbound payload]
    Payload --> HashPayload[sha256 JSON payload]
    HashPayload --> Key[sha256 workflow_id step_name payload_hash]
    Key --> Lookup{side_effect_log contains key?}
    Lookup -- yes --> Existing[Return logged result idempotent_skip=true]
    Lookup -- no --> SideEffect[Execute mock send]
    SideEffect --> Log[Write side_effect_log]
    Log --> Result[Return sent result]
```

## Telemetry Events

```mermaid
flowchart LR
    Engine[WorkflowEngine] --> StepStart[step_start]
    Engine --> StepComplete[step_complete]
    Engine --> Crash[crash_detected]
    Engine --> Resume[workflow_resumed]
    Engine --> Complete[workflow_complete]
    Engine --> ApprovalRequest[approval_requested]
    Engine --> ApprovalDecision[approval_decision]
    Router[ModelRouter] -. ModelResponse .-> Workflow[InboxTriageWorkflow]
    Workflow --> Fallback[model_fallback if was_fallback]

    StepStart --> Logger[TelemetryLogger]
    StepComplete --> Logger
    Crash --> Logger
    Resume --> Logger
    Complete --> Logger
    ApprovalRequest --> Logger
    ApprovalDecision --> Logger
    Fallback --> Logger
    Logger --> Stdout[stdout JSON when echo=true]
    Logger --> File[optional JSONL file path]
```

## Demo Execution Paths

```mermaid
flowchart TD
    StartScript[start.sh] --> Mode{command}
    Mode -- crash --> CrashDemo[examples/crash_resume_demo.py]
    Mode -- inbox --> InboxDemo[examples/inbox_triage_demo.py]
    Mode -- test/tests --> Pytest[pytest tests/]
    Mode -- help --> Help[usage text]

    CrashDemo --> ReplaceStep[replace_step injects os._exit crash]
    CrashDemo --> CrashDB[(examples/crash_resume_demo.sqlite)]
    CrashDemo --> CrashTelemetry[crash_resume_demo.telemetry.jsonl]

    InboxDemo --> InboxDB[(examples/inbox_triage_demo.sqlite)]
    InboxDemo --> InboxTelemetry[inbox_triage_demo.telemetry.jsonl]

    Pytest --> TempDB[(tmp_path SQLite DBs)]
```

## Non-Goals

This reference runtime intentionally excludes: concurrent workflow workers, real email or calendar APIs, embedding-based retrieval, production-grade tokenizers, and governance or authorization policy beyond the approval gate. See README **What This Is Not** for the production-oriented replacement stack.

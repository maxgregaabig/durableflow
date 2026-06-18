# Specification: Durable Flow

**Status:** READY
**Author:** Marcos Polanco
**Created:** 2026-06-17
**Target completion:** 2026-06-19 (48-hour build)
**Repository:** `durableflow`
**Visibility:** This spec is a private implementation guide. The public artifact is the repo itself: README, code, tests, demos.

---

## 1. Requirement & Narrative

### What

A minimal, self-contained Python backend runtime that demonstrates the infrastructure primitives required to operate LLM-powered assistant workflows reliably. The system executes a multi-step inbox triage workflow (ingest email, select context, classify priority, draft reply, await human approval, send) with durable checkpointing, crash recovery, multi-model routing with cost accounting, and context selection under token budget constraints.

This is not an assistant. It is the engine underneath one.

### Why

The personal AI assistant category is growing fast, but nearly all public demos focus on the intelligence layer (prompts, RAG, agent frameworks). The operational layer -- how you make a multi-step, LLM-dependent workflow survive crashes, respect human approval gates, manage inference cost, and select the right context under token limits -- is underdiscussed and underbuilt. This repo addresses that gap as an open-source reference implementation of the infrastructure primitives.

The core runtime must remain small, but it must be extensible enough for sibling packages to register their own step sequences, emit domain-specific telemetry, and choose whether an approval rejection terminates a workflow or returns a denial observation to a later step. The default inbox triage workflow keeps terminal rejection semantics.

### Who

**Primary audience:** Senior backend engineers and engineering leaders exploring agentic infrastructure patterns. The README should be useful to anyone building production assistant systems.

**Implicit audience:** Developers and architects building production assistant systems who want to verify the implementation's architectural invariants.

---

## 2. Gherkin Scenarios

### 2.1 Behavioral Gherkin (Test Coverage)

```gherkin
Scenario: Golden path -- email triage with approval
  Given a new email arrives in the mock inbox
  And a user context corpus of 50 prior emails and 10 calendar events
  When the inbox triage workflow executes
  Then the engine selects relevant context within the token budget (4096 tokens)
  And the triage step classifies the email as "action_required" or "informational"
  And if action_required, the draft step produces a reply
  And the workflow pauses at the approval gate
  And the workflow state is persisted to SQLite
  And when the operator approves, the workflow resumes and completes the send step
  And the telemetry log records cost, latency, and model used per LLM call

Scenario: Crash recovery mid-workflow
  Given a workflow that has completed steps ingest_email and select_context
  And the process is killed during the triage_llm step
  When the engine restarts
  Then it loads the persisted workflow state from SQLite
  And resumes execution from the last completed checkpoint (select_context)
  And completes the remaining steps without re-executing prior steps
  And the telemetry log shows the crash and recovery event

Scenario: Idempotent send on crash-after-side-effect
  Given a workflow that has completed draft_reply and approval_gate
  And the send_reply step executes successfully (side effect: email sent)
  And the process crashes before the checkpoint is written
  When the engine restarts and resumes from approval_gate
  Then the send_reply step checks the side-effect log for an existing idempotency key
  And skips the duplicate send
  And checkpoints normally

Scenario: Approval rejection
  Given a workflow paused at the approval gate with a draft reply
  When the operator rejects the draft
  Then the workflow transitions to state "rejected"
  And the rejection reason is recorded
  And no send step executes
  And the telemetry log records the rejection

Scenario: Extension workflow continues after rejected approval
  Given an extension workflow registers an approval step with rejection policy "continue"
  And the workflow is paused on a side-effecting operation
  When the operator rejects the operation
  Then the rejection is checkpointed as the step output
  And the workflow resumes at the next registered step
  And the workflow does not transition to state "rejected"

Scenario: Model fallback on provider failure
  Given the primary model provider returns a 500 error or times out after 30 seconds
  When the engine retries the LLM call
  Then it falls back to the secondary provider
  And the telemetry log records the failover, latency delta, and cost delta
  And the workflow continues without operator intervention

Scenario: Context budget enforcement
  Given a user corpus of 200 emails totaling 80,000 tokens
  And a token budget of 4096 tokens for the triage step
  When the context selector runs
  Then it returns a subset of emails ranked by relevance to the incoming email
  And the total token count of the selected context is at or below 4096
  And at least the 3 most relevant emails are included

Scenario: Cost accounting per workflow
  Given a completed workflow that used 2 LLM calls (triage + draft)
  When the workflow completes
  Then the telemetry log contains per-step cost in USD
  And the total workflow cost is the sum of per-step costs
  And cost is computed from model-specific token pricing and actual token counts
```

---

## 3. Phased Implementation Plan

### Phase 1: Core Data Models & Infrastructure

**Scope:** SQLite persistence layer, workflow state machine, step definitions, checkpoint/resume logic.

**Files:**
- `src/store.py` -- SQLite-backed workflow state store
- `src/engine.py` -- Workflow execution engine with checkpoint/resume

**Deliverables:**
- `WorkflowState` dataclass: `workflow_id`, `workflow_type`, `current_step`, `step_data` (JSON), `status` enum, `created_at`, `updated_at`
- `StepResult` dataclass: `step_name`, `output` (JSON-serializable dict), `duration_ms`, `cost_usd`, `model_used`, `timestamp`
- `WorkflowStep` dataclass: `name`, `fn`; a convenience wrapper for extension packages that build step lists programmatically
- `ApprovalRejectionPolicy` enum: `terminate`, `continue`
- `WorkflowStore` class with methods: `create_workflow()`, `save_checkpoint()`, `load_workflow()`, `list_pending()`, `update_status()`
- `WorkflowEngine` class with methods: `register_step()`, `register_steps()`, `execute()`, `resume()`, `_run_from_step()`
- SQLite schema: `workflows` table, `step_results` table, `approval_queue` table, `side_effect_log` table

**Status enum values:** `pending`, `running`, `paused_approval`, `approved`, `rejected`, `completed`, `failed`, `crashed`

**Target acceptance criteria:**
- [ ] Workflow state persists across process restarts via SQLite
- [ ] Engine resumes from last completed checkpoint, not from the beginning
- [ ] Each step's output is stored and available to subsequent steps
- [ ] Crashed workflows are detectable on restart (status = `running` with stale `updated_at`)
- [ ] No in-memory-only state that would be lost on crash
- [ ] Extension packages can register a deterministic list of steps with `register_steps()`
- [ ] Approval rejection defaults to terminal, but a step can opt into continue semantics through `approval_rejection_policies`

### Phase 2: Logic Engines & Processing

**Scope:** Workflow step definitions for inbox triage, model router, context selector, approval gate, idempotency layer.

**Files:**
- `src/workflows.py` -- Inbox triage workflow step definitions
- `src/model_router.py` -- Multi-model routing with fallback and cost tracking
- `src/context_selector.py` -- TF-IDF context selection under token budget
- `src/approval.py` -- Approval gate with pause/resume semantics

**Deliverables:**

#### model_router.py

- `ModelProvider` dataclass: `name`, `model_id`, `cost_per_input_token`, `cost_per_output_token`, `timeout_seconds`, `is_mock`
- `RoutingPolicy` dataclass: `providers` (ordered list), `retry_count`, `fallback_on_timeout`, `fallback_on_error`
- `ModelRouter` class with methods: `route(prompt, system, policy) -> ModelResponse`, `_call_provider()`, `_estimate_cost()`
- `ModelResponse` dataclass: `content`, `model_used`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`, `was_fallback`
- Mock provider that returns plausible responses without network calls (default path)
- Optional real provider integration (Anthropic SDK) gated by environment variable `ANTHROPIC_API_KEY`; never required

#### context_selector.py

- `ContextItem` dataclass: `id`, `content`, `source_type` (email/calendar), `timestamp`, `token_count`
- `ContextSelector` class with methods: `select(query, corpus, token_budget) -> list[ContextItem]`, `_score_relevance()`, `_pack_budget()`
- TF-IDF scoring using only standard library + basic math (no sklearn dependency)
- Token counting via whitespace splitting with a 0.75 word-to-token ratio approximation (sufficient for demo; production would use tiktoken)
- Greedy knapsack packing: sort by relevance score descending, include items until budget exhausted

#### approval.py

- `ApprovalRequest` dataclass: `workflow_id`, `step_name`, `payload` (the draft to review), `requested_at`, `status` (pending/approved/rejected), `decided_at`, `decided_by`, `rejection_reason`
- `ApprovalGate` class with methods: `request_approval()`, `check_approval()`, `approve()`, `reject()`, `list_pending()`
- Backed by the `approval_queue` table in SQLite
- `request_approval()` persists the request and returns a gate ID
- `check_approval()` is non-blocking; returns current status
- Engine integration: when a step returns a `PauseForApproval` sentinel, the engine persists state and stops

#### workflows.py -- Idempotency for side effects

The `send_reply` step (and any future step with external side effects) must implement idempotency:

1. Before executing the side effect, generate a deterministic idempotency key: `sha256(workflow_id + step_name + payload_hash)`
2. Check the `side_effect_log` table for this key
3. If the key exists, skip execution and return the logged result
4. If the key does not exist, execute the side effect, write the key + result to `side_effect_log`, then return

This handles the specific crash window between "side effect executed" and "checkpoint written." Without it, a crash-recovery resume would re-send an email that was already sent.

```
side_effect_log table:
  idempotency_key  TEXT PRIMARY KEY
  workflow_id      TEXT NOT NULL
  step_name        TEXT NOT NULL
  result           TEXT NOT NULL    -- JSON
  executed_at      TEXT NOT NULL
```

#### workflows.py -- Step definitions

- `InboxTriageWorkflow` -- defines the step sequence and step functions:
  1. `ingest_email` -- loads the incoming email from mock data, stores in step_data
  2. `select_context` -- calls ContextSelector with the email subject+body as query against the user's corpus
  3. `triage_llm` -- calls ModelRouter to classify (action_required / informational / fyi), using selected context
  4. `draft_reply` -- if action_required, calls ModelRouter to draft a reply in the user's voice; if not, marks complete
  5. `approval_gate` -- pauses for human approval of the draft
  6. `send_reply` -- mock send with idempotency guard; completes the workflow
- Each step function signature: `fn(workflow_state, step_data, dependencies) -> StepResult | PauseForApproval`
- Step functions are pure-ish: they read from `step_data` (prior step outputs) and return a `StepResult`

**Target acceptance criteria:**
- [ ] Model router attempts primary provider first, falls back on error/timeout
- [ ] Model router tracks cost per call in USD using per-model token pricing
- [ ] Context selector respects token budget ceiling; never exceeds it
- [ ] Context selector returns items ranked by relevance (highest first)
- [ ] Approval gate persists request to SQLite; workflow does not proceed until approved
- [ ] Approval rejection terminates the workflow with status `rejected`
- [ ] Extension workflows may set `dependencies["approval_rejection_policies"][step_name] = "continue"` so a rejected approval is checkpointed as `{"approved": false, ...}` and execution resumes at the next step
- [ ] Workflow steps access prior step outputs via `step_data` dict, not global state
- [ ] `send_reply` checks side-effect log before executing; skips if idempotency key exists

### Phase 3: Telemetry, Demos, & Mock Data

**Scope:** Observability, demo scripts, mock data fixtures.

**Files:**
- `src/telemetry.py` -- Structured logging for workflow events
- `examples/inbox_triage_demo.py` -- End-to-end golden path demo
- `examples/crash_resume_demo.py` -- Crash recovery demo (the killer demo)
- `data/mock_emails.json` -- 50 mock emails with realistic subjects, bodies, senders, timestamps
- `data/mock_calendar.json` -- 10 mock calendar events

**Deliverables:**

#### telemetry.py

- `WorkflowEvent` dataclass: `event_type`, `workflow_id`, `step_name`, `timestamp`, `duration_ms`, `cost_usd`, `model_used`, `metadata` (dict)
- `TelemetryLogger` class with methods: `log()`, `log_event()`, `log_step_start()`, `log_step_complete()`, `log_crash()`, `log_resume()`, `log_approval_request()`, `log_approval_decision()`, `log_fallback()`, `log_workflow_complete()`
- `log_event()` is the generic extension hook for domain-specific events such as tool timeouts or duplicate side-effect prevention; core named helpers remain for stable workflow events
- Output format: structured JSON lines to stdout and optionally to a `telemetry.jsonl` file
- Summary method: `summarize_workflow(workflow_id) -> dict` returning total cost, total latency, step count, fallback count, approval wait time

#### crash_resume_demo.py

Execution flow:
1. Create a new inbox triage workflow
2. Execute steps: `ingest_email`, `select_context`
3. Begin `triage_llm`, then simulate crash via `os._exit(1)` in a subprocess
4. Restart the engine in the parent process
5. Detect the crashed workflow (status=`running`, stale timestamp)
6. Resume from last checkpoint (`select_context`)
7. Complete remaining steps through approval gate
8. Auto-approve for demo purposes
9. Print telemetry summary

Expected output:
```text
[engine] workflow wf-001 started
[engine] step: ingest_email .......... complete (12ms, $0.00)
[engine] step: select_context ........ complete (8ms, $0.00)
[engine] step: triage_llm ............ started
[crash]  simulated process crash (PID 48201)

--- restarting engine ---

[engine] detected crashed workflow wf-001 (last checkpoint: select_context)
[engine] resuming wf-001 from step: triage_llm
[engine] step: triage_llm ............ complete (340ms, $0.0012)
[engine] step: draft_reply ........... complete (890ms, $0.0034)
[engine] step: approval_gate ......... paused (awaiting approval)
[approval] auto-approving for demo
[engine] step: approval_gate ......... approved
[engine] step: send_reply ............ complete (2ms, $0.00)
[engine] workflow wf-001 complete

--- summary ---
total steps:     6
total cost:      $0.0046
total latency:   1,252ms
fallbacks:       0
crash recoveries: 1
```

#### inbox_triage_demo.py

Execution flow:
1. Load mock emails and calendar events from `data/`
2. Create and run a full inbox triage workflow (no crash)
3. Pause at approval gate, display the draft to the operator
4. Accept interactive input (y/n) for approval
5. Complete or reject based on input
6. Print telemetry summary with cost breakdown

#### Mock data

`mock_emails.json` structure:
```json
[
  {
    "id": "email-001",
    "from": "sarah.chen@acme.com",
    "to": "user@company.com",
    "subject": "Q3 board deck review -- need feedback by Thursday",
    "body": "Hi, attached is the Q3 board deck...",
    "timestamp": "2026-06-17T09:14:00Z",
    "labels": ["inbox", "important"],
    "thread_id": "thread-042"
  }
]
```

`mock_calendar.json` structure:
```json
[
  {
    "id": "cal-001",
    "title": "Board meeting prep with Sarah",
    "start": "2026-06-19T14:00:00Z",
    "end": "2026-06-19T15:00:00Z",
    "attendees": ["sarah.chen@acme.com", "user@company.com"],
    "description": "Review Q3 deck before Thursday board meeting"
  }
]
```

**Target acceptance criteria:**
- [ ] `crash_resume_demo.py` runs with `python examples/crash_resume_demo.py` and produces the expected output without any API keys or external dependencies
- [ ] `inbox_triage_demo.py` runs interactively with mock providers by default
- [ ] Telemetry output is valid JSON lines parseable by `jq`
- [ ] Mock data is realistic enough that the triage and draft outputs are plausible
- [ ] Demo scripts import only from `src/` and `data/`; no circular dependencies

### Phase 4: Presentation Layer

**Status: DEFERRED**

**Rationale:** This project has no user-facing UI. The "presentation" is the CLI output of demo scripts and the README. Phase 4 sub-phases (4a: view models, 4b: scenario catalog, 4c: UI renderer) do not apply to a backend library/runtime.

The semantics-policy's UI Semantic Data Model (section 5), presentation contract, and renderer contract requirements are not applicable. If this project were extended with a web dashboard for workflow monitoring, those requirements would activate.

### Phase 5: Documentation & Tests

**Scope:** README, project configuration, test suite.

**Files:**
- `README.md`
- `pyproject.toml`
- `tests/test_resume.py`
- `tests/test_approval_gate.py`
- `tests/test_context_budget.py`

**Deliverables:**

#### README.md structure

1. **Headline:** "Assistants are easy to demo and hard to operate. This repo explores the infrastructure primitives needed to run them reliably."
2. **Quick start:** Two commands to run the crash recovery demo
3. **What this is:** One paragraph on the five primitives (durable execution, approval gates, model routing, cost accounting, context selection)
4. **Architecture notes: Scaling LLM-powered assistants** (~600-800 words)
   - Frames five scaling problems generically (not company-specific):
     1. Context corpus growth outpacing retrieval quality
     2. Workflow reliability under partial failures across external APIs
     3. Cost control as autonomous mode increases inference volume
     4. Approval queue latency as users build more routines
     5. Observability across non-deterministic execution paths
   - Maps each prototype component to the corresponding problem
   - Where public evidence from assistant companies is referenced, uses "public evidence suggests" language with links
   - Forward reference (one paragraph max): "At scale, the missing layer is governance: what is each workflow authorized to negotiate, commit, or reveal? That is a separate and harder problem."
5. **Repo structure:** tree diagram
6. **Design decisions:** brief rationale for SQLite (not Postgres/Redis), TF-IDF (not embeddings), mock providers (not mandatory API keys), idempotency keys on side effects
7. **What this is not:** "This is not a production system. It is a proof of concept exploring the problem space. A production implementation would use Temporal or a comparable durable execution framework, vector search for context retrieval, and a proper secrets manager for API credentials."

**Tone:** Written as genuine technical exploration, not as a job application artifact. "I think about these problems" not "I want this job."

#### pyproject.toml

- Python >=3.11
- Zero required external dependencies (stdlib only for core)
- Optional dependency group `[providers]`: `anthropic==0.69.0`
- Optional dependency group `[mcp]`: `mcp==1.13.1`
- Optional dependency group `[adk]`: `google-adk==1.18.0`
- Optional dependency group `[dev]`: `pytest==8.4.2`
- Package discovery includes core and sibling extension packages: `src*`, `colony*`, `agent*`, `readiness*`, `mcp_server*`

#### Tests

| Test ID | File | Scenario | Assertion |
|---------|------|----------|-----------|
| T-RES-001 | test_resume.py | Workflow completes steps 1-2, engine stops, engine restarts | Resumed workflow starts from step 3, not step 1 |
| T-RES-002 | test_resume.py | Workflow crashes mid-step (status=running, stale timestamp) | Engine detects crash and resets to last completed step |
| T-RES-003 | test_resume.py | Completed workflow is not re-executed on restart | Engine skips workflows with status=completed |
| T-APR-001 | test_approval_gate.py | Workflow reaches approval gate | Status is paused_approval; approval_queue has a pending entry |
| T-APR-002 | test_approval_gate.py | Operator approves | Workflow resumes and completes |
| T-APR-003 | test_approval_gate.py | Operator rejects | Workflow status is rejected; send step never executes |
| T-APR-004 | test_approval_gate.py | Approval gate persists across restart | Stop engine, restart, approval still pending in SQLite |
| T-EXT-001 | test_extensibility.py | Extension registers `WorkflowStep` list | Steps execute in registered order |
| T-EXT-002 | test_extensibility.py | Rejected approval with continue policy | Rejection is checkpointed; next step runs; workflow completes |
| T-EXT-003 | test_extensibility.py | Generic telemetry event | JSON line contains extension event type, step, and metadata |
| T-CTX-001 | test_context_budget.py | Corpus of 200 items, budget of 4096 tokens | Selected items total <= 4096 tokens |
| T-CTX-002 | test_context_budget.py | Relevance ranking | Top item is semantically closest to query (verified with known corpus) |
| T-CTX-003 | test_context_budget.py | Empty corpus | Returns empty list, no crash |
| T-CTX-004 | test_context_budget.py | Budget smaller than smallest item | Returns empty list, no crash |
| T-IDP-001 | test_resume.py | Send step executes, key logged, step re-runs | Second execution skips side effect, returns logged result |

**Target acceptance criteria:**
- [ ] All tests pass with `pytest tests/`
- [ ] README renders correctly on GitHub
- [ ] `pyproject.toml` installs with `pip install -e .` on Python 3.11+ and includes sibling extension packages
- [ ] No external API keys required to run tests or crash_resume_demo

---

## 3.1 Contract Types

This project has no user-facing UI. The contract structure is:

| Contract | Purpose | This Project |
|----------|---------|--------------|
| **Domain contract** | Engine/workflow outputs | `WorkflowState`, `StepResult`, `WorkflowStep`, `ModelResponse`, `ApprovalRequest` |
| **Presentation contract** | UI view model + builder | **DEFERRED** -- no UI |
| **Render contract** | Component functions | **DEFERRED** -- no UI |

---

## 3.2 Runtime Traceability (Golden Path)

End-to-end execution trace for `inbox_triage_demo.py`:

```
main()
  -> WorkflowStore(db_path)                          # src/store.py
  -> WorkflowStore.create_workflow("inbox_triage")    # src/store.py
  -> WorkflowEngine(store, telemetry)                 # src/engine.py
  -> WorkflowEngine.register_step("ingest_email", ingest_email_fn)
  -> WorkflowEngine.register_step("select_context", select_context_fn)
  -> WorkflowEngine.register_step("triage_llm", triage_llm_fn)
  -> WorkflowEngine.register_step("draft_reply", draft_reply_fn)
  -> WorkflowEngine.register_step("approval_gate", approval_gate_fn)
  -> WorkflowEngine.register_step("send_reply", send_reply_fn)
  -> WorkflowEngine.execute(workflow_id)              # src/engine.py
       -> _run_from_step(step_index=0)
            -> ingest_email_fn(state, step_data, deps)
                 -> loads email from data/mock_emails.json
                 -> returns StepResult(output={"email": {...}})
            -> store.save_checkpoint(workflow_id, step=0, result)
            -> telemetry.log_step_complete(...)

            -> select_context_fn(state, step_data, deps)
                 -> ContextSelector.select(query, corpus, budget)
                      -> _score_relevance(query, item)  -- TF-IDF
                      -> _pack_budget(scored_items, budget)  -- greedy knapsack
                 -> returns StepResult(output={"context": [...]})
            -> store.save_checkpoint(...)

            -> triage_llm_fn(state, step_data, deps)
                 -> ModelRouter.route(prompt, system, policy)
                      -> _call_provider(providers[0])  -- try primary
                      -> on success: return ModelResponse
                      -> on failure: _call_provider(providers[1])  -- fallback
                 -> returns StepResult(output={"classification": "action_required", ...})
            -> store.save_checkpoint(...)

            -> draft_reply_fn(state, step_data, deps)
                 -> if classification != "action_required": skip
                 -> ModelRouter.route(draft_prompt, system, policy)
                 -> returns StepResult(output={"draft": "..."})
            -> store.save_checkpoint(...)

            -> approval_gate_fn(state, step_data, deps)
                 -> ApprovalGate.request_approval(workflow_id, "approval_gate", draft)
                 -> returns PauseForApproval(gate_id)
            -> store.update_status(workflow_id, "paused_approval")
            -> telemetry.log_approval_request(...)
            -> ENGINE YIELDS -- workflow paused

  -- operator interaction (interactive input or auto-approve) --

  -> ApprovalGate.approve(gate_id)
  -> WorkflowEngine.resume(workflow_id)
       -> store.load_workflow(workflow_id)
       -> _run_from_step(step_index=5)  -- send_reply
            -> send_reply_fn(state, step_data, deps)
                 -> compute idempotency_key = sha256(workflow_id + "send_reply" + payload_hash)
                 -> store.check_side_effect(idempotency_key)
                 -> if exists: return logged result (skip send)
                 -> if not: execute mock send, store.log_side_effect(key, result)
                 -> returns StepResult(output={"sent": true})
            -> store.save_checkpoint(...)
            -> store.update_status(workflow_id, "completed")
            -> telemetry.log_workflow_complete(...)
```

All methods and imports above are defined in this specification. No undefined items.

---

## 4. Entry Gates

### 4.1 Specification Completeness

- [x] All acceptance criteria are explicitly written and unambiguous
- [x] Each capability claimed has a clear verification method (test IDs mapped)
- [x] No "TBD" or "TODO" placeholders in the specification
- [x] Dependencies are explicitly listed: zero required; `anthropic==0.69.0`, `mcp==1.13.1`, and `google-adk==1.18.0` optional; `pytest==8.4.2` dev

### 4.2 Cross-Reference Consistency

- [x] Claims in section 1 (narrative) match detailed specification in sections 2-3
- [x] Test plan (section 5) covers all acceptance criteria from phases 1-3 and 5
- [x] No contradictions between sections

### 4.3 Implementation Readiness

- [x] All file paths and module names specified (section 3, per phase)
- [x] Data models fully defined: `WorkflowState`, `StepResult`, `ModelProvider`, `RoutingPolicy`, `ModelResponse`, `ContextItem`, `ApprovalRequest`, `WorkflowEvent` -- all fields enumerated
- [x] Integration points: none (self-contained; optional Anthropic SDK gated by env var)
- [x] Runtime traceability: section 3.2 lists every golden-path method call and import
- [x] Presentation contract: DEFERRED with rationale (section 3.1)
- [x] Scenario catalog: Gherkin scenarios (section 2.1) cover golden path, crash recovery, idempotent send, rejection, fallback, context budget, cost accounting
- [x] Trace diagram: section 3.2 covers `engine -> workflows -> store/router/selector/approval -> telemetry`

---

## 5. Test Plan

### 5.1 Unit Tests (Logic)

| Test ID | Module Under Test | Scenario | Assertion |
|---------|-------------------|----------|-----------|
| T-RES-001 | engine.py, store.py | Workflow completes steps 1-2, engine stops, engine restarts | Resumed workflow starts from step 3 |
| T-RES-002 | engine.py, store.py | Workflow crashes mid-step | Engine detects crash via stale running status and resets to last checkpoint |
| T-RES-003 | engine.py, store.py | Completed workflow on restart | Engine does not re-execute |
| T-APR-001 | approval.py, engine.py | Workflow reaches approval gate | Status is paused_approval; pending entry in approval_queue |
| T-APR-002 | approval.py, engine.py | Operator approves | Workflow resumes and reaches completed |
| T-APR-003 | approval.py, engine.py | Operator rejects | Status is rejected; send_reply never called |
| T-APR-004 | approval.py, store.py | Approval persists across restart | New engine instance sees pending approval |
| T-EXT-001 | engine.py | Register a list of `WorkflowStep` objects | Steps execute in order |
| T-EXT-002 | engine.py, approval.py | Rejected approval with `continue` policy | Rejection checkpoint is available to the next step |
| T-EXT-003 | telemetry.py | Extension emits a generic event | JSON line contains event type, step, and metadata |
| T-CTX-001 | context_selector.py | Large corpus, limited budget | Total tokens of selection <= budget |
| T-CTX-002 | context_selector.py | Known corpus with obvious best match | Top-ranked item is the expected one |
| T-CTX-003 | context_selector.py | Empty corpus | Returns empty list without error |
| T-CTX-004 | context_selector.py | Budget smaller than any item | Returns empty list without error |
| T-RTR-001 | model_router.py | Primary provider succeeds | Response uses primary model; was_fallback is False |
| T-RTR-002 | model_router.py | Primary fails, secondary succeeds | Response uses secondary model; was_fallback is True |
| T-RTR-003 | model_router.py | All providers fail | Raises ModelRoutingError with attempted providers listed |
| T-RTR-004 | model_router.py | Cost calculation | cost_usd matches (input_tokens * cost_per_input + output_tokens * cost_per_output) |
| T-IDP-001 | workflows.py, store.py | Send executes, key logged, step re-runs | Second execution returns logged result; side effect not re-executed |
| T-TEL-001 | telemetry.py | Workflow complete event | JSON line contains workflow_id, total_cost, total_latency, step_count |
| T-TEL-002 | telemetry.py | Crash event | JSON line contains event_type "crash_detected" and last_checkpoint |

### 5.2 Integration Tests (Workflow)

| Test ID | Scenario | Assertion |
|---------|----------|-----------|
| T-INT-001 | Full golden path with mock providers | Workflow progresses through all 6 steps, ends in completed status, telemetry has 6+ events |
| T-INT-002 | Crash recovery end-to-end | Subprocess crashes at step 3, parent resumes, workflow completes |
| T-INT-003 | Approval rejection end-to-end | Workflow pauses, rejection applied, workflow ends in rejected status |

---

## 6. Exit Gates

### 6.1 Implementation Verification

For each claimed capability:
- [ ] Durable checkpointing: verify `store.py` writes to SQLite after each step; verify `engine.py` reads checkpoints on resume
- [ ] Crash recovery: verify `crash_resume_demo.py` uses subprocess + `os._exit(1)`; verify engine detects stale running status
- [ ] Approval gate: verify `approval.py` persists to SQLite; verify engine stops on `PauseForApproval` return
- [ ] Model routing: verify `model_router.py` iterates providers; verify fallback on exception/timeout
- [ ] Cost accounting: verify `ModelResponse.cost_usd` is computed from token counts and per-model pricing
- [ ] Context selection: verify `context_selector.py` enforces token budget ceiling; verify TF-IDF scoring
- [ ] Idempotency: verify `send_reply` checks `side_effect_log` before executing; verify skip on duplicate key
- [ ] Telemetry: verify JSON lines output with required fields

### 6.2 Acceptance Criteria Checklist

- [ ] All Phase 1 target acceptance criteria checked (5 items)
- [ ] All Phase 2 target acceptance criteria checked (8 items)
- [ ] All Phase 3 target acceptance criteria checked (5 items)
- [ ] All Phase 5 target acceptance criteria checked (4 items)
- [ ] All unit tests pass: `pytest tests/ -v`
- [ ] Both demo scripts run without error on Python 3.11+ with no API keys

### 6.3 Dependency Verification

- [ ] Zero required dependencies (stdlib only)
- [ ] `anthropic` pinned as optional: `anthropic==0.69.0`
- [ ] `mcp` pinned as optional: `mcp==1.13.1`
- [ ] `google-adk` pinned as optional: `google-adk==1.18.0`
- [ ] `pytest` pinned as dev: `pytest==8.4.2`
- [ ] No dependency added without rationale in README design decisions section

### 6.4 Cross-Reference Validation

- [ ] README claims match implemented capabilities
- [ ] No DEFERRED items claimed as complete
- [ ] Architecture analysis references only publicly verifiable information; uses "public evidence suggests" language with links where citing specific companies
- [ ] Governance forward-reference is one paragraph maximum

### 6.5 Presentation Layer Verification

**DEFERRED.** No user-facing UI. Terminal output verified by:
- [ ] `crash_resume_demo.py` output matches expected format (section 3, Phase 3)
- [ ] Telemetry JSON lines are valid JSON (parseable by `json.loads`)

---

## 7. Pre-Mortem Analysis

*It is 6 months after building this artifact. The target audience did not engage. What went wrong?*

| Failure Category | Risk Factor | Probability | Impact |
|------------------|-------------|-------------|--------|
| **Signal-to-noise** | README is too long; reader stops before the architecture analysis | Medium | High |
| **Credibility gap** | Code is too simple; looks like a weekend exercise, not evidence of production thinking | Medium | Medium |
| **Wrong problem** | Target company's actual bottleneck is context quality or integration reliability, not workflow durability; artifact misses the mark | Low | High |
| **Execution quality** | Bugs in demo scripts; crash_resume_demo fails on reviewer's machine | Low | Critical |
| **Overreach** | Architecture analysis makes incorrect claims about specific companies' stacks | Medium | High |
| **Positioning** | Artifact feels like a job application rather than genuine engineering interest | Low | Medium |

---

## 8. Remediation & Acceptance

| Risk | Mitigation | Integrated Into |
|------|------------|-----------------|
| README too long | Cap architecture notes at 600-800 words. Lead with the demo command. Reviewer should be running code within 30 seconds. | Phase 5: README structure |
| Code too simple | Each module has at least one non-trivial decision (state machine transitions, TF-IDF from scratch, greedy knapsack, subprocess crash, idempotency keys). Comment the "why" not the "what." | Phase 1-2: code review gate |
| Wrong problem | All five scaling problems are sourced from published assistant-company engineering content: job postings, case studies, product docs. Frame generically. | Phase 5: README framing |
| Demo script bugs | Run both demos on a clean Python 3.11 environment (no venv carryover) before submission. Test on macOS and Linux. | Phase 3: acceptance criteria |
| Stack claim errors | Use "public evidence suggests" with links, never "Company X uses Y." | Phase 5: README language |
| Job-app feel | Frame as open-source exploration of an underserved problem space. Tone: "I think about these problems" not "I built this to impress you." | Phase 5: README tone |

**Deferred items (accepted technical debt):**
- Token counting is approximate (word-based, not tiktoken). Documented in README.
- TF-IDF is basic (no IDF smoothing, no sublinear TF scaling). Sufficient for demonstrating the pattern.
- No real email/calendar API integration. Mock data only. Documented in README.
- No concurrent workflow execution. Single-workflow-at-a-time. Production would require Temporal or equivalent.

**Scope cut priority (if time gets tight):**

Drop in this order (last = drop first):
1. **Drop last:** Real Anthropic provider support (optional feature, not core signal)
2. **Drop second-to-last:** Interactive approval in `inbox_triage_demo.py` (auto-approve is fine)
3. **Keep no matter what:** durable checkpointing, crash/resume demo, approval pause, cost accounting, context budget enforcement, idempotency on send, tests, README

---

## 9. Code Review Gates

### 9.1 Implementer Self-Review Requirements

Before reporting DONE:
- [ ] Does the code contain any TODO comments related to core claimed capabilities? (If yes: DONE_WITH_CONCERNS)
- [ ] Do all imported modules get used? (Remove unused imports)
- [ ] Are there any hardcoded values that should be configurable? (Extract to constants at module top or config dict)
- [ ] Does error handling cover: SQLite lock contention, JSON serialization failures, model provider timeouts, empty corpus, zero-budget context selection?

### 9.2 Spec Compliance Review Requirements

- [ ] Read actual implementation of `engine.py`: verify checkpoint is written after each step, not at workflow end
- [ ] Read actual implementation of `model_router.py`: verify fallback loop iterates providers list, not just try/except on one
- [ ] Read actual implementation of `context_selector.py`: verify token budget is enforced as a hard ceiling
- [ ] Read actual implementation of `crash_resume_demo.py`: verify crash uses subprocess isolation (not just try/except)
- [ ] Read actual implementation of `send_reply` step: verify idempotency key check before side effect
- [ ] Verify no TODO comments related to durability, approval, routing, context selection, cost tracking, or idempotency

### 9.3 Code Quality Escalation

If code quality review identifies issues:
- [ ] Implementer fixes issues OR
- [ ] Issues are explicitly accepted as technical debt with rationale in README "Design decisions"
- [ ] Phase marked DONE_WITH_CONCERNS if proceeding with known issues

### 9.4 Integration Review

N/A for initial build. If later integrated into a larger project:
- [ ] Verify SQLite database path is configurable
- [ ] Verify telemetry output destination is configurable
- [ ] Verify model provider configuration is injectable

---

## 10. Declaration Standards

### 10.1 Status Definitions

| Status | Meaning | Applied When |
|--------|---------|--------------|
| DRAFT | Spec being written | Initial |
| READY | Entry gates passed; implementation can begin | Entry gates (section 4) all checked |
| IN_PROGRESS | Coding underway | First file created |
| PARTIAL | Core engine works; some modules incomplete | Engine + store + one demo working |
| COMPLETE | All exit gates passed | All tests pass; both demos run; README complete |
| DEFERRED | Explicitly postponed | Phase 4 (UI) |

### 10.2 Plan Update Requirements

Before marking any phase COMPLETE:
- [ ] Run exit gate checklist (section 6)
- [ ] Verify no TODO comments for claimed capabilities
- [ ] Cross-read: do README claims match code behavior?

### 10.3 Prohibited Practices

- NEVER mark a phase COMPLETE if acceptance criteria are unchecked
- NEVER claim "durable execution" if checkpoints are in-memory only
- NEVER claim "crash recovery" if the demo uses try/except instead of process-level crash
- NEVER claim "cost tracking" if cost is hardcoded rather than computed from token counts
- NEVER claim "context budget" if the selector can exceed the budget ceiling
- NEVER claim "idempotent" if the side-effect log is not checked before execution
- NEVER reference a specific company's internal architecture as fact without "public evidence suggests" qualifier and a public source link

### 10.4 Victory Declaration Anti-Patterns

| Anti-Pattern | Example in This Project | Correct Approach |
|--------------|------------------------|------------------|
| TODO in code, COMPLETE in docs | `# TODO: implement fallback` in model_router.py, README claims "multi-model routing with fallback" | Remove TODO or mark capability DEFERRED |
| Exists != Operates | `context_selector.py` exists but `select()` returns all items ignoring budget | Code must enforce the budget; test T-CTX-001 verifies |
| Mock == Real | README implies production-grade system | README explicitly states "This is not a production system" |
| Crash demo is fake | Demo catches exception instead of killing process | Demo must use subprocess + `os._exit(1)` |
| Cost is decoration | Cost field present but always 0.0 | Cost computed from mock-realistic token counts and per-model pricing |
| Idempotency is claimed but not implemented | send_reply has no side-effect log check | send_reply must check before executing; test T-IDP-001 verifies |

---

## Appendix A: File Manifest

```
durableflow/
  README.md                          # Phase 5
  pyproject.toml                     # Phase 5
  src/
    __init__.py                      # Package marker
    engine.py                        # Phase 1 -- workflow execution engine
    store.py                         # Phase 1 -- SQLite persistence
    workflows.py                     # Phase 2 -- inbox triage step definitions
    model_router.py                  # Phase 2 -- multi-model routing
    context_selector.py              # Phase 2 -- TF-IDF context selection
    approval.py                      # Phase 2 -- approval gate
    telemetry.py                     # Phase 3 -- structured event logging
  examples/
    inbox_triage_demo.py             # Phase 3 -- golden path demo
    crash_resume_demo.py             # Phase 3 -- crash recovery demo
  data/
    mock_emails.json                 # Phase 3 -- 50 mock emails
    mock_calendar.json               # Phase 3 -- 10 mock calendar events
  tests/
    __init__.py                      # Package marker
    test_resume.py                   # Phase 5 -- T-RES-001 to T-RES-003, T-IDP-001
    test_approval_gate.py            # Phase 5 -- T-APR-001 to T-APR-004
    test_context_budget.py           # Phase 5 -- T-CTX-001 to T-CTX-004
    test_extensibility.py            # Phase 5 -- T-EXT-001 to T-EXT-003
```

---

## Appendix B: Dependency Matrix

| Module | Imports From (internal) | Imports From (stdlib) | Imports From (external) |
|--------|------------------------|-----------------------|------------------------|
| store.py | -- | sqlite3, json, dataclasses, datetime, uuid, enum, hashlib | -- |
| engine.py | store, telemetry | dataclasses, enum, time, typing | -- |
| workflows.py | model_router, context_selector, approval, store | json, pathlib, hashlib | -- |
| model_router.py | -- | dataclasses, time, typing | anthropic (optional) |
| context_selector.py | -- | dataclasses, math, collections, re | -- |
| approval.py | store | dataclasses, datetime | -- |
| telemetry.py | -- | dataclasses, json, datetime, sys | -- |
| crash_resume_demo.py | engine, store, workflows, telemetry, approval | subprocess, os, time | -- |
| inbox_triage_demo.py | engine, store, workflows, telemetry, approval | json, pathlib | -- |

No circular dependencies. Dependency direction: `examples/ -> src/`; within `src/`: `engine -> store, telemetry`; `workflows -> model_router, context_selector, approval, store`; `approval -> store`. No upward or lateral cycles.

---

## Appendix C: SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id     TEXT PRIMARY KEY,
    workflow_type   TEXT NOT NULL,
    current_step    INTEGER NOT NULL DEFAULT -1,
    step_data       TEXT NOT NULL DEFAULT '{}',   -- JSON: accumulated step outputs
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS step_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id     TEXT NOT NULL,
    step_index      INTEGER NOT NULL,
    step_name       TEXT NOT NULL,
    output          TEXT NOT NULL,    -- JSON
    duration_ms     REAL NOT NULL,
    cost_usd        REAL NOT NULL DEFAULT 0.0,
    model_used      TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS approval_queue (
    gate_id         TEXT PRIMARY KEY,
    workflow_id     TEXT NOT NULL,
    step_name       TEXT NOT NULL,
    payload         TEXT NOT NULL,    -- JSON: the draft or artifact to review
    status          TEXT NOT NULL DEFAULT 'pending',
    requested_at    TEXT NOT NULL,
    decided_at      TEXT,
    decided_by      TEXT,
    rejection_reason TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS side_effect_log (
    idempotency_key TEXT PRIMARY KEY,
    workflow_id     TEXT NOT NULL,
    step_name       TEXT NOT NULL,
    result          TEXT NOT NULL,    -- JSON
    executed_at     TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_workflows_status ON workflows(status);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_queue(status);
CREATE INDEX IF NOT EXISTS idx_step_results_workflow ON step_results(workflow_id);
```

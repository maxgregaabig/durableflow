# Workshop Curriculum — Full Lesson Plan

Complete lesson-by-lesson plan for the DurableFlow workshop. Cross-references [exercises.md](../exercises.md) (E1–E8) and [workshop-exercises.md](workshop-exercises.md) (W1–W12).

---

## Module 1: The Operational Gap

**Duration:** 45 minutes  
**Goal:** Frame why intelligence-layer demos fail in production and what primitives matter.

### Learning objectives

- Name the five scaling problems for LLM-powered assistants (context, partial failure, cost, approval latency, observability).
- Distinguish DurableFlow from agent frameworks and from production orchestrators.
- Articulate what "durable execution" means in one sentence.

### Lesson 1.1 — From demo to production (15 min)

**Lecture points:**

1. Narrow assistants succeed: one request → one model call → one response.
2. Production assistants accumulate context, run multi-step routines, and touch real systems.
3. Public platform docs increasingly emphasize tools, background execution, observability, evals, and cost — the ops layer is no longer optional.

**Discussion:** What broke the last agent demo your team shipped to staging?

**Reading:** [README.md](../../README.md) — "Architecture notes: scaling LLM-powered assistants"

### Lesson 1.2 — What DurableFlow is and is not (15 min)

**Lecture points:**

| Layer | DurableFlow | Production recommendation |
|-------|-------------|---------------------------|
| Durability | SQLite checkpoints | Temporal |
| Orchestration | Plain Python steps | LangGraph / LlamaIndex Workflows |
| Model routing | `ModelRouter` | LiteLLM / Portkey |
| Observability | JSONL telemetry | LangSmith / Phoenix |
| Agent loop | Readiness + MCP demos | Your framework of choice |

**Key phrase:** "This is the engine underneath an assistant, not another assistant framework."

**Reading:** [README.md](../../README.md) — "Why not X?"

### Lesson 1.3 — Repo tour and quick start (15 min)

**Live demo:**

```bash
./start.sh crash
./start.sh inbox    # optional: show approval prompt
./start.sh test
```

**Walkthrough:** `src/`, `examples/`, `tests/`, `colony/`, `readiness/`, `docs/`.

**Lab:** None — observe only.

---

## Module 2: Durable Execution Engine

**Duration:** 2 hours  
**Goal:** Understand checkpoint semantics, SQLite schema, and real crash recovery.

### Learning objectives

- Explain `current_step` as the index of the **last completed** step.
- Trace `execute()` vs `resume()` through `WorkflowEngine`.
- Recover a workflow after `os._exit` without re-running completed steps.

### Lesson 2.1 — Core invariants (20 min)

**Lecture points** (from [dflow-arch.md](../dflow-arch.md)):

1. Checkpoint after every completed step.
2. Pause on human gate (`PauseForApproval`).
3. Idempotency before side effects.
4. Hard token budget in context selection.
5. No in-memory-only workflow state.

**Diagram review:** Inbox triage workflow (indices 0–5).

### Lesson 2.2 — SQLite persistence model (25 min)

**Code walkthrough:**

- `src/store.py` — `WorkflowStore`, tables: `workflows`, `step_results`, `approval_queue`, `side_effect_log`
- `src/engine.py` — `register_step`, `execute`, `resume`, `_run_from_step`

**Concept check:** If `current_step = 1`, which step runs next? (`select_context` is done; `triage_llm` runs.)

### Lesson 2.3 — Crash recovery lab (45 min)

**Demo:** `examples/crash_resume_demo.py` — subprocess kill during `triage_llm`.

**Labs:**

| ID | Task | Source |
|----|------|--------|
| E1 | Inspect checkpoints after crash | [exercises.md](../exercises.md) |
| W1 | Predict resume index before running parent | [workshop-exercises.md](workshop-exercises.md) |
| W2 | Trace `recover_crashed` and stale `running` status | [workshop-exercises.md](workshop-exercises.md) |

**Expected evidence:** `current_step = 1`; steps 0–1 in `step_results`; `triage_llm` completes only after resume.

### Lesson 2.4 — Engine extension contract (30 min)

**Lecture:** `InboxTriageWorkflow.register(engine)` binds callables; engine does not import workflows.

**Lab preview:** Exercise E7 (add seventh step) — assigned as homework or capstone prep.

**Reading:** [dflow-spec.md](../dflow-spec.md) — Phase 1 acceptance criteria

---

## Module 3: Human-in-the-Loop Gates

**Duration:** 1.5 hours  
**Goal:** Master the two-layer approval model and rejection semantics.

### Learning objectives

- Separate `workflows.status` from `approval_queue.status`.
- Explain why `approve()` does not resume execution by itself.
- Handle terminal rejection vs extension `continue` policy.

### Lesson 3.1 — Approval architecture (20 min)

**Diagram review:** Approval gate flow in [dflow-arch.md](../dflow-arch.md).

**Two layers:**

1. `approval_queue` — operator decision (`pending` → `approved` / `rejected`)
2. `workflows` — execution state (`paused_approval` → `running` / `rejected` on `resume()`)

**Code:** `src/approval.py`, `approval_gate` in `src/workflows.py`

### Lesson 3.2 — Golden path with approval (25 min)

**Live demo:**

```bash
./start.sh inbox
# Approve with 'y'
```

**Sequence review:** draft → `PauseForApproval` → checkpoint pending → operator approves → `resume()` → send.

### Lesson 3.3 — Rejection and skip paths (35 min)

**Labs:**

| ID | Task | Source |
|----|------|--------|
| E2 | Reject draft; confirm no send | [exercises.md](../exercises.md) |
| E6 | Informational email skips gate and send | [exercises.md](../exercises.md) |
| W3 | Compare `ApprovalRejectionPolicy.TERMINATE` vs `CONTINUE` in tests | [workshop-exercises.md](workshop-exercises.md) |

**Discussion:** When would you use `continue` instead of `terminate`? (e.g. operator denies a CRM update but agent should log and proceed.)

### Lesson 3.4 — Pause persistence across restart (10 min)

**Concept:** Approval payload and gate row survive process exit; workflow resumes when operator returns.

**Reading:** Gherkin "Approval rejection" in [dflow-spec.md](../dflow-spec.md)

---

## Module 4: Cost, Routing, and Context Budgets

**Duration:** 2 hours  
**Goal:** Operate multi-provider routing and bounded context selection.

### Learning objectives

- Configure primary/secondary providers and interpret `was_fallback`.
- Compute per-step USD cost from token estimates.
- Enforce a hard token ceiling with greedy TF-IDF selection.

### Lesson 4.1 — Model routing and fallback (35 min)

**Code:** `src/model_router.py` — `RoutingPolicy`, `ModelProvider`, timeout and error paths.

**Live lab:**

| ID | Task | Source |
|----|------|--------|
| E3 | Force model fallback in REPL | [exercises.md](../exercises.md) |
| W4 | Inject failing primary into inbox workflow; grep `model_fallback` in JSONL | [workshop-exercises.md](workshop-exercises.md) |

**Discussion:** What belongs in routing policy vs workflow code?

### Lesson 4.2 — Cost accounting (25 min)

**Lecture:**

- Cost = f(input_tokens, output_tokens, model-specific pricing)
- Recorded per step in `step_results.cost_usd` and telemetry
- Autonomous mode makes per-workflow cost mandatory, not a monthly surprise

**Lab W5:** Sum costs from `step_results` for a completed workflow; compare to `workflow_complete` telemetry event.

### Lesson 4.3 — Context selection under budget (40 min)

**Code:** `src/context_selector.py` — TF-IDF scoring, greedy packing, `token_count` ceiling.

**Why not embeddings?** Visibility and testability; this workshop is about ops, not retrieval SOTA.

**Labs:**

| ID | Task | Source |
|----|------|--------|
| E4 | Context budget enforcement | [exercises.md](../exercises.md) |
| W6 | Tune budget to 512 tokens; observe which emails drop out | [workshop-exercises.md](workshop-exercises.md) |

### Lesson 4.4 — Idempotent side effects (20 min)

**Code:** `send_reply` in `src/workflows.py` — idempotency key, `side_effect_log`.

**Labs:**

| ID | Task | Source |
|----|------|--------|
| E5 | Idempotent send on replay | [exercises.md](../exercises.md) |
| W7 | Draw the crash window between side effect and checkpoint | [workshop-exercises.md](workshop-exercises.md) |

**Key invariant:** Duplicate send prevented when crash occurs after send but before checkpoint.

---

## Module 5: Observability and Audit Trails

**Duration:** 1 hour  
**Goal:** Read telemetry as the source of truth for non-deterministic runs.

### Learning objectives

- List telemetry event types and when each fires.
- Reconstruct a workflow path from JSONL after crash, fallback, and rejection.
- Explain what production observability platforms add on top.

### Lesson 5.1 — Telemetry event model (20 min)

**Code:** `src/telemetry.py`

**Events:** `step_start`, `step_complete`, `crash_detected`, `workflow_resumed`, `approval_requested`, `approval_decision`, `model_fallback`, `workflow_complete`

### Lesson 5.2 — Audit trail lab (30 min)

**Labs:**

| ID | Task | Source |
|----|------|--------|
| E8 | Read the audit trail after crash demo | [exercises.md](../exercises.md) |
| W8 | Build a timeline table: event_type, step_name, timestamp | [workshop-exercises.md](workshop-exercises.md) |

### Lesson 5.3 — From JSONL to production tracing (10 min)

**Discussion:** What would you send to LangSmith/OpenTelemetry that DurableFlow already captures locally?

---

## Module 6: Colony — Measured Durability on Hostile Compute

**Duration:** 1.5 hours  
**Goal:** Understand the naive-vs-durable benchmark and its limits.

### Learning objectives

- Describe the five-stage job shape and completion criterion.
- Explain seeded chaos and why both runners share the same loss schedule.
- Interpret completion, cost, wall-clock, recoveries, and interventions.

### Lesson 6.1 — The narrow claim (15 min)

**Reading:** [colony/README.md](../../colony/README.md), [colony-methodology.md](../colony-methodology.md)

**Claim:** Durable execution converts spot-like compute into completable inventory — measured, not asserted.

### Lesson 6.2 — Run the benchmark (30 min)

```bash
python3 examples/chaos_benchmark_demo.py --profile hostile
python3 examples/chaos_benchmark_demo.py --profile calm
python3 examples/single_eviction_demo.py
```

**Compare:** naive restart-from-stage-0 vs checkpoint-resume on new instance.

### Lesson 6.3 — Threats to validity (20 min)

**Facilitate debate:**

- Mock mode ≠ live infrastructure
- One workload, one loss model
- Controller-induced termination as proxy

**Lab W9:** Change seed; document whether completion delta holds.

### Lesson 6.4 — Map to your infrastructure (25 min)

**Discussion:** Where would checkpoints live for your batch jobs? What is your "artifact upload commits" equivalent?

**Reading:** [colony/colony-spec.md](../../colony/colony-spec.md) (optional, for implementers)

---

## Module 7: Agent Readiness and the Durable Agent Pattern

**Duration:** 2 hours  
**Goal:** Evaluate whether an agent is deployable near customer systems.

### Learning objectives

- State the six failure modes in the readiness harness.
- Run naked vs wrapped comparison and read verdict-first report.
- Apply the field checklist from the Durable Agent Pattern.

### Lesson 7.1 — The Durable Agent Pattern (20 min)

**Reading:** [field-pattern.md](../field-pattern.md)

**Pattern steps:**

1. Wrap agent loop in durable shell
2. Checkpoint every reason-act-observe turn
3. Idempotent external writes
4. Gate external writes
5. Run same failures against naked and wrapped agents
6. Ship from measured evidence

### Lesson 7.2 — Readiness harness (40 min)

```bash
./start.sh readiness
cat readiness_report.md
```

**Code tour:** `readiness/harness.py`, `readiness/scoring.py`, `agent/runner.py`

**Six failure modes:** tool timeout, malformed output, prompt injection, context overflow, model fallback, crash after side effect.

### Lesson 7.3 — MCP gated write path (30 min)

```bash
./start.sh mcp
```

**Concept:** Write tools routed through approval; read tools execute freely.

**Lab W10:** Trace MCP demo telemetry and `side_effect_log` for CRM write.

### Lesson 7.4 — ADK boundary and production checklist (30 min)

**Optional:** `agent/adk_adapter.py` — adapter boundary, not full Runner E2E.

**Lab W11:** Fill the [field checklist](../field-pattern.md) for a hypothetical customer deployment.

**Discussion:** Human approval is a bridge — what replaces it? (authorization policy, audited delegation)

---

## Capstone (Module 8)

**Duration:** 2–4 hours  
**Doc:** [capstone.md](capstone.md)

Participants choose one track:

| Track | Deliverable |
|-------|-------------|
| A — Extend workflow | New step + test + checkpoint verification |
| B — New side effect | Idempotent integration step with approval |
| C — Readiness scenario | Add failure scenario to harness with scoring |
| D — Colony profile | New chaos profile + methodology note |

---

## Assessment quizzes

Short verbal or written checks facilitators can use between modules.

### Module 2

1. What does `current_step = 3` mean after `draft_reply` completes?
2. Why does crash during `triage_llm` not re-run `ingest_email`?

### Module 3

1. After `ApprovalGate.approve()`, why is the workflow still `paused_approval`?
2. What SQLite tables prove no email was sent after rejection?

### Module 4

1. When does `was_fallback` become true?
2. Why might sum of selected `token_count` be strictly less than budget?

### Module 5

1. Which event proves recovery after crash?
2. Where is per-step cost also persisted besides JSONL?

### Module 6

1. What defines job completion in Colony?
2. Why must both runners use the same chaos seed?

### Module 7

1. Name three readiness failure modes.
2. What is the primary artifact for a customer-facing deployment decision?

---

## Exercise index (all modules)

| ID | Title | Module |
|----|-------|--------|
| E1 | Inspect checkpoints after crash | 2 |
| E2 | Reject draft and confirm no send | 3 |
| E3 | Force model fallback | 4 |
| E4 | Context budget enforcement | 4 |
| E5 | Idempotent send on replay | 4 |
| E6 | Informational email skips send | 3 |
| E7 | Add a seventh step | 2 / Capstone A |
| E8 | Read the audit trail | 5 |
| W1 | Predict resume index | 2 |
| W2 | Stale running detection | 2 |
| W3 | Rejection policies | 3 |
| W4 | Fallback in full workflow | 4 |
| W5 | Cost reconciliation | 4 |
| W6 | Budget tuning lab | 4 |
| W7 | Crash window diagram | 4 |
| W8 | Telemetry timeline | 5 |
| W9 | Seed sensitivity | 6 |
| W10 | MCP write trace | 7 |
| W11 | Field checklist | 7 |
| W12 | Capstone peer review | 8 |

---

## Homework between days

**After Day 1:** Complete E1, E2, read [dflow-arch.md](../dflow-arch.md) through "Crash Recovery Sequence".

**After Day 2:** Complete E3–E6, E8; run Colony with `--profile moderate`.

**After Day 3:** Capstone + one-page "production mapping" note (which primitive → which production tool).

---

## Production mapping template

Participants complete this once during the workshop:

```markdown
## Our assistant: [name]

| Primitive | DurableFlow mechanism | Our production choice | Owner |
|-----------|----------------------|------------------------|-------|
| Durability | SQLite checkpoint | | |
| Approval | ApprovalGate | | |
| Model routing | ModelRouter | | |
| Context budget | ContextSelector | | |
| Idempotency | side_effect_log | | |
| Observability | TelemetryLogger | | |
| Readiness | readiness harness | | |
```

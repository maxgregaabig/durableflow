# Specification: DurableFlow Planner (`/planner`)

**Status:** DRAFT
**Extension level:** Peer to Colony. Both are extensions built on DurableFlow core (durable execution, checkpoint persistence, crash recovery, cost-aware routing). Colony is the durable multi-agent execution layer. Planner is the constraint-driven target-selection and execution-planning layer.
**Owner:** Marcos Polanco
**Applies:** `process/spec-policy.md`, `process/semantics-policy.md`
**Revision:** 3 (remediates two external spec reviews; see §12 Change Log)

---

## 1. Requirement & Narrative

### 1.1 What
**A constraint-driven execution planner with durable, verifiable escalation across local and cloud tiers. Local-first with cloud escalation.**

The planner accepts an intent-level request (a chat-completion plus declarative constraints) and produces an **execution plan**: an ordered chain of candidate targets that satisfies hard constraints and ranks the rest against a stated objective. The default chain is local-first: a local model runs first, and the request escalates to a cloud tier only on **verifiable** failure. DurableFlow executes the plan durably, checkpointing each attempt and recording verifiable outcomes back into the planner so future plans improve.

The caller does not name a model. The caller states requirements. The default request body uses `"model": "auto"`; an explicit model name bypasses the planner entirely (escape hatch).

### 1.2 Why
The model-routing market optimizes **selection** (which model per call). It does not produce an **execution plan** across heterogeneous targets, and it treats local and cloud as separate silos. The defensible position for DurableFlow is to make the placement decision a first-class, durable, replayable artifact built on assets DurableFlow already owns (durable state, checkpoints, cost-aware routing). This puts the work adjacent to durable workflow runtimes rather than to commoditizing gateways.

Two value props lead, in this order of explainability:

1. **Stay within budget.** A request (and optionally a session) carries a hard cost ceiling. The simplest, most concrete promise the system makes is "this will not cost more than X, and it will prefer the cheapest target that can do the job." This is the easiest thing to demo and the easiest thing to trust.
2. **Local-first with cloud escalation.** Run on local compute by default; reach for cloud only when local verifiably fails. Lower cost, data stays local unless escalation is permitted, and offline-capable where the local tier suffices.

The honest scope boundary, enforced throughout this spec: the planner is **constraint-aware selection with verifiable escalation, not a quality oracle.** Pre-execution quality cannot be measured the way a database optimizer measures cardinality. The system therefore does not store or claim a "quality" number. The only signal with a real source of truth is **verifiable outcome** (transport success, latency within budget, and an optional caller-supplied output check). Historical statistics are expressed as a per-target, per-task-class **success rate** over those verifiable outcomes, with explicit confidence. Escalation fires on verifiable failure, never on a guessed score.

### 1.3 Who
- **Primary:** Backend and platform engineers integrating an OpenAI-compatible endpoint who want cost, latency, and privacy governed by policy instead of hardcoded per-call model choices.
- **Secondary:** Agent authors (including Colony) who need subtasks placed under a shared budget.
- **Observability consumer:** The engineer or reviewer reading a plan trace to answer "why did this run here, and what did it cost versus the alternatives?"

### 1.4 Standalone value and relationship to Colony
The planner is **fully usable without Colony.** It ships a standalone OpenAI-compatible proxy, a session budget ledger, durable escalation, and a plan trace. A team can adopt it purely to cap and explain spend on an existing endpoint, with no agent framework involved. This standalone path is the primary adoption story.

Planner and Colony are **siblings**, not parent/child. Both import DurableFlow core; neither requires the other. Colony MAY call the planner to place agent subtasks under a session budget. The **cross-subtask portfolio optimization** (allocating one budget optimally across many known future subtasks) lives in Colony and is **DEFERRED** here. The planner provides the in-scope primitive Colony will build on: a session budget ledger with tier downgrade near exhaustion (§3.2, §3.3).

### 1.5 Core integration boundary

Planner is **not** a fixed-step `WorkflowEngine` workflow. A chat-completion request is a request-level execution plan with a variable attempt chain, not a pre-registered sequence of workflow steps. Forcing it through `WorkflowEngine.register_steps()` would obscure the domain model and make streaming semantics harder to state correctly.

Planner therefore follows the Colony extension shape: it reuses DurableFlow's lower-level SQLite durability primitives through `WorkflowStore`, while owning Planner-specific tables and request execution logic. `PlannerStore` wraps a `WorkflowStore` connection, creates an internal workflow row per planned request for core checkpoint visibility, and writes each target attempt as a checkpoint plus a Planner outcome row. This keeps the durable artifact inspectable in the core store without changing the core schema or public `WorkflowEngine` API.

Implementation rule: Planner MAY import `WorkflowStore`, `StepResult`, `TelemetryLogger`, and the existing model-routing cost conventions. Planner MUST NOT require changes to `WorkflowEngine` execution semantics, MUST keep all new persistence additive, and MUST keep the OpenAI-compatible proxy usable without Colony or Readiness.

---

## 2. Gherkin Scenarios

### 2.1 Behavioral Gherkin (test coverage)

```gherkin
Scenario: Cheap request stays local
  Given a healthy local target and two cloud targets are registered
  When a request arrives with X-Max-Cost: 0.002, X-Privacy: any, and model "auto"
  Then the plan primary step selects the local target
  And the plan includes at least one cloud fallback step
  And planning latency is recorded and under the hot-path budget

Scenario: A tier floor forces a minimum target tier
  Given a request sets X-Tier-Floor: frontier
  When the planner runs
  Then no local or economy target is selected as primary or fallback
  And every step in the plan is a frontier-tier target

Scenario: Privacy is a hard constraint
  Given X-Privacy: local-only is requested
  And no local target is healthy
  When the planner runs
  Then the plan status is INFEASIBLE with reason "no_healthy_local_target"
  And the API returns HTTP 422 with the structured reason
  And no cloud target is attempted

Scenario: Verifiable failure triggers durable escalation
  Given a non-streaming plan with primary = local and fallback = frontier
  And the request carries an output check requiring valid JSON
  When the local target returns output failing the JSON check
  Then DurableFlow checkpoints the failed attempt
  And execution escalates to the frontier step
  And the recorded attempt marks step 0 verifiable_outcome = "failed_check"

Scenario: Latency ceiling excludes a target before execution
  Given the frontier target's measured p95 latency exceeds X-Max-Latency
  When the planner runs
  Then the frontier target is excluded from the plan with reason "latency_ceiling"
  And it does not appear as a fallback step

Scenario: Session budget near exhaustion forces downgrade
  Given a budget id has spent 0.95 of a 1.00 limit
  When a new request arrives under that budget id with objective most_capable
  Then the objective is downgraded to cheapest for this request
  And the lowest permitted tier that fits the remaining budget is selected
  And if no permitted target fits the remaining budget the plan is INFEASIBLE with reason "budget_exhausted"

Scenario: Streaming request commits the chosen step before the first token
  Given a streaming request with primary = local and fallback = frontier
  When the local target is reachable and the stream begins
  Then the local step is committed for the lifetime of the stream
  And a mid-stream transport failure returns a stream error
  And the attempt is recorded as verifiable_outcome = "transport_error"
  And the request is NOT silently retried on the frontier target

Scenario: Plan cache hot path
  Given an identical (task-signature, constraint-set) was planned within the cache TTL
  When the same request arrives again
  Then the cached plan is returned
  And planning latency is under the hot-path budget
```

### 2.2 Conceptual Gherkin (plan-trace surface semantics)

```gherkin
Scenario: Engineer asks why a request ran where it did
  Given an engineer is reviewing a request that ran more cheaply than expected and is mildly skeptical
  When they open the plan trace for that request
  Then they see one headline decision in plain language ("Ran locally under a $0.002 cap")
  And they see the constraints that bound the decision
  And they see the alternatives that were considered, each with a one-line verdict and reason
  And predicted cost and latency are shown beside the actual cost and latency
  And implementation field names (step indices, target ids) are never shown

Scenario: Reviewer sees a low-confidence decision
  Given a request ran on a target that is cold-start for this task class
  When the reviewer opens the plan trace
  Then the trace states plainly that the decision was made with low confidence
  And it states that the system has little history for this kind of request yet

Scenario: Reviewer inspects an infeasible request
  Given a request was rejected as infeasible
  When the reviewer opens the plan trace
  Then the trace states in plain language which hard constraint could not be met
  And it lists what would have to change for the request to succeed
  And no partial or misleading "almost ran" state is shown
```

---

## 3. Phased Implementation Plan

### 3.0 Runtime Traceability (golden path)

End-to-end trace for "cheap request stays local, executes, and is traced." Every call and import below is defined in this spec; undefined items are marked DEFERRED.

```
HTTP POST /v1/chat/completions  (durableflow/planner/api.py: handle_completions)
  ├─ import ConstraintParser            (durableflow/planner/constraints.py)
  │    └─ ConstraintParser.parse(headers, body) -> ExecutionConstraints
  ├─ import Planner                     (durableflow/planner/planner.py)
  │    └─ Planner.plan(request, constraints) -> ExecutionPlan
  │         ├─ PlanCache.get(signature, constraints)          (cache.py)   [hot path returns here]
  │         ├─ BudgetLedger.check(constraints.budget_id)      (budget.py)
  │         ├─ TargetRegistry.healthy_targets()               (targets.py)
  │         ├─ derive_task_class(request)                     (taskclass.py) -> TaskClass
  │         ├─ ConstraintFilter.apply(targets, constraints)   (solver.py)
  │         ├─ CostModel.estimate / LatencyModel.estimate / CapabilityEstimator.estimate (estimators.py) -> Estimate
  │         ├─ PlanSolver.rank(estimates, constraints)        (solver.py) -> [PlanStep]
  │         ├─ PlanSolver.build_chain(ranked)                 (solver.py) -> ExecutionPlan
  │         └─ PlanCache.put(signature, constraints, plan)    (cache.py)
  ├─ import run_with_plan               (durableflow/planner/integration.py)
  │    └─ run_with_plan(plan, request) -> (Response, PlanOutcome)
  │         ├─ PlannerStore.checkpoint_attempt(...)           (wraps WorkflowStore.save_checkpoint)
  │         ├─ OllamaAdapter.invoke(step, request)            (adapters/ollama.py)
  │         ├─ OutputCheck.verify(response, request.check)    (integration.py)   [pass -> stop]
  │         ├─ BudgetLedger.charge(budget_id, actual_cost)    (budget.py)
  │         └─ OutcomeRecorder.record(plan, outcome)          (outcomes.py)
  │              └─ PlannerStore.insert_outcome(...) + update_target_stats(...) (store.py)
  └─ import build_plan_trace_view       (durableflow/planner/views.py)
       └─ build_plan_trace_view(plan, outcome, constraints) -> PlanTraceView
            └─ render_plan_trace(view)  (durableflow/planner/render.py)   [CLI / JSON]
```

### 3.1 Contract Types (plan-trace UI feature)

| Contract | Purpose | This feature |
|----------|---------|--------------|
| **Domain contract** | Engine outputs | `ExecutionPlan`, `PlanStep`, `PlanOutcome`, `Estimate` |
| **Presentation contract** | View model + builder | `PlanTraceView`, `build_plan_trace_view(plan, outcome, constraints) -> PlanTraceView` |
| **Render contract** | Component function | `render_plan_trace(view: PlanTraceView) -> None` |

Presentation contract requirements follow `process/semantics-policy.md` §5. Mapping table in §3.8.

### 3.2 Phase 1: Core Data Models & Infrastructure

Modules: `constraints.py`, `targets.py`, `taskclass.py`, `budget.py`, `solver.py` (types only), `outcomes.py`, `store.py`, `adapters/ollama.py`, `adapters/openai_compat.py`.

Data models (fully defined, no TBD fields):

- `ExecutionConstraints`: `max_cost_usd: float | None`, `max_latency_ms: int | None`, `privacy: Privacy` (`LOCAL_ONLY | LOCAL_OR_VPC | ANY`), `region: str | None`, `tier_floor: Tier` (`NONE | ECONOMY | FRONTIER`), `objective: Objective` (`CHEAPEST | FASTEST | MOST_CAPABLE`; default `CHEAPEST`), `budget_id: str | None`, `shadow: bool` (default `False`), `output_check: OutputCheck | None`.
- `Tier`: `LOCAL | ECONOMY | FRONTIER` (also the natural ordering for `tier_floor`, where `NONE` permits all).
- `TargetProfile`: `id`, `name`, `tier: Tier`, `model_id`, `privacy_class: Privacy`, `region`, `cost_in_per_1k: float`, `cost_out_per_1k: float`, `enabled: bool`.
- `TargetHealth`: `target_id`, `available: bool`, `last_checked_at`, `consecutive_failures: int`.
- `TaskClass` (enum, taxonomy v1): `CHAT | CODE | JSON_EXTRACTION | SUMMARIZATION | OTHER`. Constant `TASK_CLASS_TAXONOMY_VERSION = 1`.
- `Estimate`: `cost_usd: float`, `latency_ms_p95: int`, `success_rate: float` (0..1, fraction of past verifiable non-failures for this target and task class; absent an `output_check` an attempt counts as a non-failure, so without checks `success_rate` reflects completion reliability, not answer quality), `confidence: float` (0..1, rising with `sample_count`), `tier: Tier`.
- `PlanStep`: `index`, `target_id`, `model_id`, `estimate: Estimate`, `role` (`PRIMARY | FALLBACK | ESCALATION | SHADOW`), `rationale: str`.
- `ExecutionPlan`: `id`, `request_id`, `status` (`PLANNED | INFEASIBLE`), `steps: list[PlanStep]`, `flags: list[str]`, `infeasible_reason: str | None`, `planning_ms: float`, `low_confidence: bool`.
- `Estimate` source of truth and `Attempt`:
  - `VerifiableOutcome` (enum): `PASSED_CHECK | NO_CHECK_COMPLETED | FAILED_CHECK | TRANSPORT_ERROR | LATENCY_BREACH`.
  - `Attempt`: `step_index`, `target_id`, `actual_cost_usd`, `actual_latency_ms`, `verifiable_outcome: VerifiableOutcome`, `success: bool` (derived: `PASSED_CHECK` or `NO_CHECK_COMPLETED`).
  - `PlanOutcome`: `plan_id`, `attempts: list[Attempt]`, `final_step_index: int`, `success: bool`.

SQLite schema extensions (DurableFlow store). Additive migration only.

```sql
CREATE TABLE planner_targets (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, tier TEXT NOT NULL,
  model_id TEXT NOT NULL, privacy_class TEXT NOT NULL, region TEXT,
  cost_in_per_1k REAL NOT NULL, cost_out_per_1k REAL NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE planner_target_stats (
  target_id TEXT NOT NULL, task_class TEXT NOT NULL, taxonomy_version INTEGER NOT NULL,
  latency_ms_p50 REAL, latency_ms_p95 REAL,
  success_rate REAL, sample_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (target_id, task_class, taxonomy_version)
);
CREATE TABLE planner_plans (
  id TEXT PRIMARY KEY, request_id TEXT NOT NULL,
  constraints_json TEXT NOT NULL, plan_json TEXT NOT NULL,
  status TEXT NOT NULL, planning_ms REAL NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE planner_outcomes (
  id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, step_index INTEGER NOT NULL,
  target_id TEXT NOT NULL, actual_cost_usd REAL, actual_latency_ms INTEGER,
  verifiable_outcome TEXT NOT NULL, success INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE planner_budgets (
  budget_id TEXT PRIMARY KEY, limit_usd REAL NOT NULL,
  spent_usd REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
);
```

`PlannerStore` contract:
- `__init__(db_path)`: constructs an internal `WorkflowStore(db_path)` and applies Planner's additive schema.
- `create_plan_workflow(request_id, constraints, plan) -> workflow_id`: creates a core workflow row with `workflow_type="planner_request"` and stores the request/plan snapshot in `planner_plans`.
- `checkpoint_attempt(plan, attempt) -> None`: writes a `StepResult` to `WorkflowStore.save_checkpoint()` with `step_name=f"attempt_{attempt.step_index}"` and output containing `target_id`, `verifiable_outcome`, latency, and cost; also inserts the corresponding `planner_outcomes` row.
- `insert_outcome(plan, outcome) -> None`: idempotently records final outcome metadata and supports replay-safe stats updates.
- `update_target_stats(target_id, task_class, attempt) -> None`: updates `planner_target_stats` keyed by `TASK_CLASS_TAXONOMY_VERSION`.

Adapters: `OllamaAdapter` (local) and `OpenAICompatAdapter` (economy and frontier upstreams) implement `invoke(step, request) -> RawResponse` and reuse DurableFlow's cost-aware routing client where available.

**Exit criteria:** types instantiable and serializable; additive migration applies cleanly to an existing DurableFlow DB; `PlannerStore` persists request attempts through `WorkflowStore.save_checkpoint()` without requiring `WorkflowEngine`; both adapters round-trip against a stub server; `TASK_CLASS_TAXONOMY_VERSION` persisted with every stats row.

### 3.3 Phase 2: Logic Engines & Processing

Modules: `constraints.py` (parser), `taskclass.py`, `budget.py`, `estimators.py`, `solver.py` (logic), `cache.py`, `outcomes.py`.

- `ConstraintParser.parse(headers, body)`: maps `X-Max-Cost`, `X-Max-Latency`, `X-Privacy`, `X-Region`, `X-Tier-Floor` (`economy|frontier`), `X-Objective` (`cheapest|fastest|most_capable`), `X-Budget-Id`, `X-Shadow` to `ExecutionConstraints`. Unknown values reject with a structured 400. `model != "auto"` short-circuits to direct invocation. There is no `min_quality` field; quality is never expressed as a free-floating number (see §1.2 and §11).
- `derive_task_class(request) -> TaskClass`: deterministic and pinned. Rules (taxonomy v1, in priority order): an `output_check` with a JSON schema implies `JSON_EXTRACTION`; fenced code or code-intent markers imply `CODE`; an explicit summarize instruction implies `SUMMARIZATION`; otherwise `CHAT`, falling back to `OTHER` only when input is non-textual. The taxonomy is versioned so a future rule change does not silently corrupt historical stats.
- `BudgetLedger`: `check(budget_id) -> Remaining` and `charge(budget_id, actual_cost)`. When projected request cost would exceed remaining budget, the solver downgrades `objective` to `CHEAPEST` and lowers the permitted tier ceiling to the cheapest that fits; if nothing fits, the plan is `INFEASIBLE` with reason `budget_exhausted`.
- `CostModel.estimate(target, request)`: deterministic from token estimate and target pricing.
- `LatencyModel.estimate(target, task_class)`: from rolling `planner_target_stats` p95 with a conservative prior when `sample_count` is below a cold-start threshold.
- `CapabilityEstimator.estimate(target, request)`: **bounded, grounded in verifiable history.** Returns `success_rate` and `confidence` from the target's `planner_target_stats` for the derived `task_class`. Cold start (low `sample_count`) yields a conservative `success_rate` and low `confidence`. Low confidence widens the fallback chain rather than trusting a single pick; it never invents a quality number. The interface is stable so an ML backend can replace the heuristic later without touching the solver.
- `PlanSolver`: (1) filter by hard constraints (privacy, region, `tier_floor`, capability, health); (2) drop targets whose predicted cost exceeds `max_cost_usd` or whose predicted p95 exceeds `max_latency_ms`; (3) apply budget downgrade if a `budget_id` is near exhaustion; (4) rank survivors by `objective` (`CHEAPEST` = min cost; `FASTEST` = min predicted p95; `MOST_CAPABLE` = highest tier, then highest `success_rate` (declared capability and verifiable reliability, not predicted answer quality)); (5) build the local-first primary plus ordered fallback chain; append a `SHADOW` step when `shadow=True` and a candidate is cold-start; (6) if no target survives the hard filter, return `INFEASIBLE` with a specific reason. `objective=BALANCED` is intentionally NOT offered in v1 (see §7 and §11).
- `PlanCache`: keyed on `(task_signature, normalized_constraints)`, TTL-bounded, bounded size. Hot-path target p99 under 10 ms.
- `OutcomeRecorder.record(plan, outcome)`: persists attempts and updates `planner_target_stats` (latency percentiles; `success_rate` as an EMA over `VerifiableOutcome`). Writes are off the request path (async).

**Exit criteria:** solver unit tests cover local-first golden, tier-floor, infeasible, latency-exclusion, budget-downgrade, and shadow; `derive_task_class` is deterministic across a fixture set; cache hit/miss tested; stats update idempotent per outcome.

### 3.4 Phase 3: API & Integration Layer

Modules: `api.py`, `integration.py`.

- `api.py`: `POST /v1/chat/completions` OpenAI-compatible, streaming and non-streaming. Constraint headers parsed; `model: "auto"` invokes the planner; explicit model bypasses. `INFEASIBLE` returns 422 with structured reason. `GET /v1/plans/{request_id}` returns the plan trace as JSON.
- `integration.py`: `run_with_plan(plan, request)` executes durably on DurableFlow.
  - **Non-streaming:** for each step, checkpoint, invoke, verify the optional `output_check`; on `TRANSPORT_ERROR`, `FAILED_CHECK`, or `LATENCY_BREACH`, escalate to the next step; return the first success or an exhausted-chain error.
  - **Streaming (commit-before-stream rule):** the planner reachability-probes the primary, commits exactly one step, then streams. Once the first token reaches the client the step is committed for the stream's lifetime. A mid-stream transport failure returns a stream error and records `TRANSPORT_ERROR` on the committed step; it is never silently retried on a fallback, which prevents double-charging and duplicate tokens. Cross-step escalation for streaming happens only pre-commit.
  - On completion, `BudgetLedger.charge` and `OutcomeRecorder.record` run; both off the response path.

**Exit criteria:** end-to-end tests for golden, escalation, infeasible, budget-downgrade, and streaming-mid-stream-failure; stock OpenAI clients call the endpoint unmodified when `model` is set; planning overhead measured and reported.

### 3.5 Phase 4a: Presentation View Model + Builder

Module: `views.py`.

- `PlanTraceView` fields: `state` (`PLANNED | EXECUTED | ESCALATED | INFEASIBLE | LOADING`), `headline: str`, `confidence_note: str | None` (set when `low_confidence`), `constraints_summary: list[str]`, `chosen: ChosenCard | None`, `considered: list[ConsideredRow]` (capped at 4; ordered chosen, then fallback, then rejected), `escalation: EscalationNote | None`, `actual_vs_predicted: ComparisonRow | None`, `what_would_change: list[str]` (infeasible only).
- `build_plan_trace_view(plan, outcome, constraints) -> PlanTraceView`: pure function; all vocabulary mapping and state routing here. Routing: `INFEASIBLE` plan to infeasible; outcome with `final_step_index > 0` to escalated; outcome at step 0 to executed; no outcome to planned; in-flight to loading. Sets `confidence_note` whenever `plan.low_confidence` is true.

### 3.6 Phase 4b: Scenario / Demo Data Catalog

Fixtures in `data/planner_scenarios/` (version-controlled; no hardcoded demo copy in render files). One fixture per cognitive outcome:

| Cognitive outcome | Fixture | State |
|-------------------|---------|-------|
| Golden (ran on local primary, cheap) | `PLAN-001-local-golden` | EXECUTED |
| Escalation (verifiable failure) | `PLAN-002-escalation` | ESCALATED |
| Infeasible (privacy unmet) | `PLAN-003-infeasible` | INFEASIBLE |
| Budget downgrade | `PLAN-004-budget-downgrade` | EXECUTED |
| Low-confidence cold-start decision | `PLAN-005-low-confidence` | EXECUTED |
| Loading (execution in flight) | `PLAN-006-loading` | LOADING |

### 3.7 Phase 4c: Renderer

Module: `render.py`. `render_plan_trace(view: PlanTraceView)` produces a CLI (Rich) or JSON view. Consumes the presentation view type only; imports no domain DTO modules for rendering.

**A browser/web dashboard is DEFERRED:** the primary integration surface is the API and trace JSON; a CLI/JSON trace suffices for the MVP audience (engineers and demos) and avoids UI scope before the engine is validated.

### 3.8 Presentation Mapping Table (semantics-policy §5.2)

| User mental model object | UI component | Source field(s) | Builder responsibility |
|--------------------------|--------------|-----------------|------------------------|
| The decision | Headline | `ExecutionPlan.steps[0]`, `PlanOutcome.final_step_index` | One plain-language sentence; no ids |
| How sure we are | Confidence note | `ExecutionPlan.low_confidence` | Plain-language cold-start caveat when set |
| What bounded it | Constraints summary | `ExecutionConstraints` | Render only set constraints, in user words |
| Why here | Chosen card | `PlanStep.estimate`, `PlanStep.rationale` | Map to "predicted cost / latency / past success rate" |
| The alternatives | Considered rows | `PlanStep[]` plus rejected candidates | One verdict + reason each; cap at 4 |
| Did fallback fire | Escalation note | `PlanOutcome.attempts` | from-target to-target plus verifiable reason |
| Predicted vs reality | Comparison row | `Estimate` vs `Attempt` actuals | Side-by-side; never hide a miss |
| Why it could not run | What-would-change list | `ExecutionPlan.infeasible_reason` | Translate reason to remediation steps |

---

## 4. Entry Gates

### 4.1 Specification Completeness
- [x] Acceptance criteria explicit (§5).
- [x] Each claimed capability has a verification method (§5 Test IDs).
- [x] No TBD/TODO placeholders in this specification.
- [ ] Dependencies version-pinned (resolved at implementation start; §6.3).

### 4.2 Cross-Reference Consistency
- [x] Narrative scope (§1) matches implemented scope: three tiers, heuristic capability estimator, success-rate-grounded history, no quality oracle, no `BALANCED`.
- [x] Test plan covers every §2.1 scenario.
- [x] No section contradicts another; Colony boundary stated once (§1.4) and not violated.

### 4.3 Implementation Readiness
- [x] File paths and module names specified (§3.0, §3.2 to §3.7).
- [x] Data models fully defined (§3.2; no "to be determined" fields).
- [x] Integration points with DurableFlow core identified (checkpoint, cost-aware routing client, SQLite store).
- [x] Runtime traceability present (§3.0); ML capability backend, web UI, Colony portfolio optimization, and additional target kinds marked DEFERRED.
- [x] Presentation contract defined (`build_plan_trace_view()` signature, §3.1, §3.5).
- [x] API contract lists the builder, not a renderer accepting domain DTOs.
- [x] Scenario catalog covers all Conceptual Gherkin outcomes (§3.6 maps to §2.2 plus behavioral failure modes).
- [x] Trace diagram includes `api → planner → run_with_plan → build_plan_trace_view() → render_plan_trace()`.

**Gate result:** one open item (4.1 dependency pinning), resolved at implementation start. All other gates pass. Spec is **READY** on resolution of pinning.

---

## 5. Test Plan

### 5.1 Engine and integration tests

| Test ID | Type | Scenario | Assertion |
|---------|------|----------|-----------|
| PLN-001 | unit | Cheap request, healthy local | Primary step is local; at least one cloud fallback present |
| PLN-002 | unit | `tier_floor=frontier` | No local/economy target in any step; all steps frontier |
| PLN-003 | unit | `privacy=local-only`, no healthy local | INFEASIBLE; reason `no_healthy_local_target` |
| PLN-004 | unit | Frontier p95 > `max_latency` | Frontier excluded with reason `latency_ceiling` |
| PLN-005 | unit | Predicted cost > `max_cost` for all but local | Only local survives the cost filter |
| PLN-006 | unit | `budget_id` near exhaustion | Objective downgraded to cheapest; lowest fitting tier chosen; `budget_exhausted` when nothing fits |
| PLN-007 | unit | Cold-start target (low sample_count) | Conservative latency + success_rate prior; `low_confidence` set; chain widened |
| PLN-008 | unit | Cache hit on identical signature+constraints | Cached plan returned; planning_ms under hot-path budget |
| PLN-009 | integration | Non-streaming: local output fails JSON check | Failed attempt checkpointed; escalates; `failed_check` recorded |
| PLN-010 | integration | HTTP via stock OpenAI client, explicit model | Planner bypassed; direct invocation |
| PLN-011 | integration | INFEASIBLE over HTTP | 422 with structured reason; no target invoked |
| PLN-012 | integration | Outcome recording updates stats | `planner_target_stats` percentile and `success_rate` updated idempotently, keyed by taxonomy_version |
| PLN-013 | perf | Planning latency budget | Hot-path (cache hit) p99 < 10 ms; cold-path (full solve, 3 targets) p99 < 50 ms; both measured over 1k runs |
| PLN-014 | integration | `shadow=on`, cold-start candidate | Shadow step runs in parallel; its output is not returned; its `verifiable_outcome` is recorded; user latency unaffected |
| PLN-015 | integration | Streaming mid-stream transport failure | Committed step records `transport_error`; no retry on fallback; stream error surfaced; budget charged once |
| PLN-016 | unit | `derive_task_class` determinism | Same request yields same `TaskClass`; JSON-check request maps to `JSON_EXTRACTION` |

### 5.2 Plan-trace fitness functions (semantics-policy §7)

| Test ID | Cognitive scenario | Assertion | Method |
|---------|--------------------|-----------|--------|
| SEM-PLAN-001 | Engineer reads a trace | Exactly one headline; no ids or step indices in user text | Automated text scan |
| SEM-PLAN-002 | Reviewer reads infeasible trace | `what_would_change` non-empty; no "almost ran" state | Builder test on `PLAN-003` |
| SEM-PLAN-003 | AI regenerates the view | Renderer imports no domain DTO modules; consumes `PlanTraceView` only | Import-lint architecture test |
| SEM-PLAN-004 | Each cognitive outcome | Each fixture in §3.6 yields the expected `state` enum | Builder test per fixture |
| SEM-PLAN-005 | Predicted missed actual | Comparison row shows predicted and actual; miss not hidden | Builder test on `PLAN-002` |
| SEM-PLAN-006 | Low-confidence decision | `confidence_note` is set and plainly worded for the cold-start fixture | Builder test on `PLAN-005` |

### 5.3 Value Benchmark (proves value, not just correctness)

Harness: `bench/planner_benchmark.py`. A fixed, version-controlled corpus of 100 requests spanning the task classes, a fraction carrying deterministic `output_check`s.

Compare three configurations over the same corpus:
- Baseline A: always frontier.
- Baseline B: always economy.
- Planner: `objective=cheapest`, local-first, with the corpus's output checks.

Report per configuration: total cost, latency p50 and p95, verifiable success rate, and (planner only) escalation count and the cost ratio versus Baseline A.

| Test ID | Type | Assertion |
|---------|------|-----------|
| BENCH-001 | benchmark | Harness runs end-to-end and emits the comparison table. Default release threshold: planner total cost <= 50% of Baseline A, with planner verifiable success rate >= Baseline A minus 2 percentage points. The measured figures are recorded from the run; the threshold is the gate, the exact numbers are not asserted in advance. |

The benchmark is a release gate input (§6.4), not merely a demo. It exists because a correct planner that does not measurably beat a static default is not worth shipping.

---

## 6. Exit Gates

### 6.1 Implementation Verification (per capability)
- [ ] Read the implementation for each §5 capability; behavior matches claim.
- [ ] No TODO comments tied to claimed capabilities.
- [ ] Escalation fires only on `VerifiableOutcome` failure, never on a guessed score; verified in code.

### 6.2 Acceptance Criteria Checklist
- [ ] Every §5 Test ID has passing coverage.
- [ ] Known gaps documented before completion.

### 6.3 Dependency Verification
- [ ] All dependencies pinned with `==`.
- [ ] No new dependencies without explicit approval; optional deps marked optional.

### 6.4 Cross-Reference Validation
- [ ] README and docs match implemented capabilities and use the §11 vocabulary (no "quality oracle", no `min_quality`, no `BALANCED`).
- [ ] No DEFERRED item (ML capability backend, web UI, Colony portfolio optimization, `BALANCED`, VPC/Vast/edge-NPU targets) claimed as complete.
- [ ] Planning-latency targets (PLN-013) measured and met.
- [ ] **Value benchmark (BENCH-001) run; results recorded; planner beats the static default on cost at comparable verifiable success.**

### 6.5 Presentation Layer Verification
- [ ] `render_plan_trace` accepts `PlanTraceView` only.
- [ ] `build_plan_trace_view()` tested for each fixture in §3.6 (golden, escalation, infeasible, downgrade, low-confidence, loading).
- [ ] No render file imports domain DTOs for rendering.
- [ ] Mapping table (§3.8) maps 1:1 to view model fields, not hardcoded copy.

---

## 7. Pre-Mortem Analysis

Assume the planner failed six months after launch.

- **Reliability (streaming double-charge):** mid-stream failure silently retries on a fallback, duplicating tokens and cost. Trigger: streaming plus mid-stream transport failure. Mitigated by the commit-before-stream rule (§3.4, PLN-015).
- **Data Quality (cold start):** capability estimates are unreliable until outcomes accumulate, so early plans pick badly and erode trust. Trigger: new target or new task class with `sample_count` near zero. Mitigated by success-rate grounding, conservative priors, chain widening, low-confidence trace signaling, and opt-in shadow mode (§3.3, §3.5, PLN-007, PLN-014, SEM-PLAN-006).
- **Misleading constraint (resolved):** an earlier draft exposed `min_quality: float`, a number nobody could define. Removed in favor of the concrete `tier_floor` plus `objective` (§1.2, §11).
- **Complexity (resolved):** a `BALANCED` objective with hidden weights would be unpredictable and undebuggable. Deferred from v1; only the three pure objectives ship, default `CHEAPEST` (§3.3, §11).
- **Commercial Validation:** users set `model` explicitly and never adopt `"auto"`, so the planner is dead weight. Mitigated by the value benchmark as a release gate (§5.3, §6.4) and by leading with the easily explained budget value prop (§1.2).
- **Scaling:** per-request planning plus stats writes contend on the SQLite store under load. Trigger: high QPS with synchronous writes. Mitigated by plan caching and async outcome/budget writes (§3.3, §3.4).

---

## 8. Remediation & Acceptance

Accepted mitigations, woven into phases and tests:

- **Verifiable outcome as the only stored signal** (Phase 1 and 2): `success_rate` over `VerifiableOutcome`, never a quality number. Covers Data Quality and trust. Verified by PLN-012, PLN-016.
- **Commit-before-stream** (Phase 3): one committed step per stream; no mid-stream cross-target retry. Covers Reliability. Verified by PLN-015.
- **`tier_floor` replaces `min_quality`** (Phase 1 and 2): a concrete, user-understandable knob. Verified by PLN-002.
- **`BALANCED` deferred** (Phase 2): only pure objectives ship; default `CHEAPEST`. Covers Complexity.
- **Conservative cold-start priors, chain widening, low-confidence signaling, opt-in shadow mode** (Phase 2 and 4): Covers Data Quality. Verified by PLN-007, PLN-014, SEM-PLAN-006.
- **Session budget ledger with downgrade** (Phase 1, 2, 3): in-scope budget enforcement and the primitive Colony will build on. Covers the budget value prop. Verified by PLN-006.
- **Value benchmark as a release gate** (Phase analysis, §5.3): proves value, not just correctness. Verified by BENCH-001, gated in §6.4.
- **Pinned, versioned task classification** (Phase 2): deterministic `derive_task_class`; taxonomy version stored with stats. Verified by PLN-016.
- **Async outcome and budget writes** (Phase 3): off the request path. Covers Scaling. Verified by PLN-013.

Deferred (accepted technical debt, not in scope):
- ML capability backend (heuristic ships first; interface stable).
- `objective=BALANCED` (only with explicit, trace-exposed weights when introduced).
- Web dashboard (CLI/JSON trace ships first).
- Colony cross-subtask portfolio optimization (the planner provides the session-budget primitive only).
- Additional target kinds: VPC private endpoints, Vast spot GPUs, phone NPU, P2P device clusters. The local tier (Ollama) represents edge for the MVP. See §9 for the extension path.

---

## 9. Future Target Extensibility

Adding a new target kind must not require solver changes. The solver and filters operate on `TargetProfile` fields and `Estimate`, never on hardcoded kind logic. To add a kind (for example `VAST_SPOT`, `VPC`, `EDGE_NPU`):

1. **Adapter:** implement `invoke(step, request) -> RawResponse` for the new backend under `adapters/`.
2. **Profile registration:** insert a `planner_targets` row with `tier`, `privacy_class`, `region`, and a cost model. The hard-constraint filter (privacy, region, tier_floor, cost, latency) applies unchanged.
3. **Priors:** seed conservative latency and `success_rate` priors; the `CapabilityEstimator` keys on `task_class`, not on kind, so no estimator change is required.
4. **Optional kind-specific semantics:** only if a kind needs new privacy or region rules does the filter gain a case; the ranking stays kind-agnostic.

This keeps the path from "three tiers" to a broader heterogeneous fleet a matter of adapters and registry rows, not a solver rewrite.

---

## 10. Code Review Gates

### 10.1 Implementer Self-Review
- [ ] No TODO comments tied to core capabilities (else DONE_WITH_CONCERNS).
- [ ] No unused imports.
- [ ] No hardcoded model names, pricing, tier logic, or thresholds outside config/registry.
- [ ] Error handling covers every §2.1 failure mode (infeasible, latency exclusion, output-check failure, transport failure, budget exhaustion, streaming mid-stream failure).

### 10.2 Spec Compliance Review
- [ ] Reviewer reads implementation, not just the report.
- [ ] Each §3 requirement has corresponding code.
- [ ] TODOs flagged as partial completion.
- [ ] "Escalates on verifiable outcome only" verified against code.

### 10.3 Quality Escalation
- [ ] Important issues fixed, or accepted as documented debt, or phase marked DONE_WITH_CONCERNS.

### 10.4 Integration Review
- [ ] Existing DurableFlow tests pass.
- [ ] No breaking changes to DurableFlow core public API.
- [ ] Additive SQLite migration validated against an existing DB.
- [ ] Config and environment changes documented.

---

## 11. Declaration Standards & Vocabulary Guard

- **Status:** DRAFT, advancing to READY on resolution of the single open entry gate (dependency pinning, §4.1).
- **Plan update rule:** before marking any phase COMPLETE, run §6 exit gates (including BENCH-001), confirm no TODOs for claimed capabilities, confirm dependencies pinned with `==`, and cross-read claims against code.
- **Prohibited COMPLETE conditions:** unchecked acceptance checklist; TODOs on claimed capabilities; unpinned dependencies; unaddressed Important review issues; any DEFERRED item claimed as implemented.
- **Vocabulary guard (this feature).** Docs, README, and the trace must use grounded language:
  - Do NOT claim the planner "predicts quality", "optimizes quality", or "measures quality". It does none of these.
  - Do NOT reintroduce a `min_quality` float or any free-floating quality score.
  - Do NOT ship `objective=BALANCED` in v1.
  - The capability-preferring objective is named `MOST_CAPABLE` (highest tier, then highest verifiable reliability), never `BEST_QUALITY`; the system selects by declared tier and reliability, not by predicting answer quality.
  - DO describe the system as "constraint-aware selection with verifiable escalation across local and cloud tiers", whose only learned signal is per-target, per-task-class **success rate** over verifiable outcomes.
  - "AI Query Planner" is roadmap and vision framing only; it is not the product description and must not headline external materials, because it invites the unanswerable "how do you predict quality before execution?" The shipped framing is the budget and local-first story.

---

## 12. Change Log

**Revision 3** remediates the second external review and one self-consistency gap. Changes:
1. Renamed objective `BEST_QUALITY` to `MOST_CAPABLE` (header `most_capable`) so the objective name matches the §11 vocabulary guard: selection is by declared tier and verifiable reliability, never by predicted answer quality.
2. Clarified that `success_rate`, absent an `output_check`, is a completion-reliability signal rather than an answer-quality signal, closing the "where does the signal come from" critique for workloads with no ground truth.
3. Gave the value benchmark a concrete default release threshold (cost <= 50% of all-frontier baseline at verifiable success within 2 points), so the release gate is measurable rather than hand-waved.
4. Fixed the revision-line cross-reference to point at §12.

**Revision 2** remediates the external spec review. Changes:
1. Removed `min_quality: float`; added concrete `tier_floor` (`NONE | ECONOMY | FRONTIER`) as a hard constraint.
2. Replaced the `quality`/`quality_ema`/`quality_signal` model with `success_rate` and a `VerifiableOutcome` enum that has a real source of truth; renamed `QualityEstimator` to `CapabilityEstimator`.
3. Deferred `objective=BALANCED`; v1 ships `CHEAPEST` (default), `FASTEST`, `MOST_CAPABLE` only.
4. Tightened §1 to match MVP scope and led with the budget and local-first value props; promoted the standalone (no-Colony) adoption story.
5. Promoted a session budget ledger (`planner_budgets`) to in-scope, with downgrade-near-exhaustion logic; kept cross-subtask portfolio optimization deferred to Colony.
6. Added the commit-before-stream rule and a streaming-failure test (PLN-015) to resolve the reliability pre-mortem.
7. Added cold-start handling: low-confidence trace signaling (`confidence_note`, SEM-PLAN-006) and opt-in shadow mode (PLN-014).
8. Pinned and versioned task classification (`derive_task_class`, `TASK_CLASS_TAXONOMY_VERSION`; PLN-016).
9. Added a value benchmark (§5.3, BENCH-001) and made it a release gate (§6.4).
10. Added §9 Future Target Extensibility and a §11 vocabulary guard retiring external "AI Query Planner" framing.

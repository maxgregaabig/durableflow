# Proposal: Governed Multi-Agent Coordination for DurableFlow (`multiagent/`)

**Status:** PROPOSAL
**Created:** 2026-07-28
**Applies to:** new package `multiagent/`; consumes `src/engine.py`, `src/store.py`, `src/approval.py`, `src/model_router.py`, `src/telemetry.py`, `agent/runner.py`, `agent/protocol.py`
**Core engine changes required:** none
**Precedent:** `colony/` (extension-owned tables over the shared `WorkflowStore`, `colony/store_ext.py:13`)
**Delta constraint (deferred):** No precondition violation has been identified for coordination itself; defer this proposal until one is concrete rather than treating more agents as an authority control.

---

## 1. Position

Multi-agent frameworks sell *capability*: roles, delegation, negotiation. The claim that actually fails in production is *coordination*. Coordination breaks before compute does — a multi-agent system dies from a supervisor that never terminates, two workers writing the same state key, a sub-agent that executes an irreversible write nobody approved, or a review loop that spends $40 on a $2 task.

DurableFlow already owns the primitives that answer those four failures: durable checkpoints (`src/store.py:165`), a synchronous approval gate that fires *before* a write commits (`src/engine.py:146`), idempotent side effects keyed on a content hash (`agent/runner.py:302`, `src/store.py:123`), and per-step cost accounting on `StepResult` (`src/store.py:44`).

**The claim of this proposal, stated so it can be falsified:**

> DurableFlow can run a supervisor-coordinated agent team where termination is deterministic, every write scope is disjoint and pre-authorized, spend is capped by a hard ceiling enforced before each turn, and a mid-flight process kill resumes without re-executing a single completed sub-agent turn or duplicating a single write.

That is a coordination and governance claim, not an intelligence claim. Nothing here makes agents smarter.

### 1.1 Earning multi-agent

The decision ladder is `rules → heuristics → classical ML → LLM/RAG → bounded agent → multi-agent`. DurableFlow already ships the bounded-agent rung: `AgentRunner` (`agent/runner.py:70`) is a single tool-using agent with governed writes, and it is the correct answer for most workloads.

`multiagent/` is justified only when one of these is true, and the proposal must name which:

| Trigger | Why one agent fails |
|---|---|
| Independent fan-out | N research subtasks with no ordering dependency serialize behind one history |
| Context bloat | A single trajectory exceeds the token budget before the task resolves |
| Conflicting evidence | Two sources disagree and the resolution needs an arbiter that did not gather either |
| Separable authority | One role must hold a write scope another role must not have |

**Not a trigger:** a destructive action. A destructive action requires a policy gate, which `AgentRunner` already has. Adding agents to make a write safer is the junior move.

What we accept in exchange, stated up front: orchestration complexity, a shared-state ACL surface, a wider prompt-injection perimeter across handoffs, and more observability to maintain. §11 prices these.

---

## 2. Scope, non-goals, and deferrals

### 2.1 In scope for v1

- Supervisor topology only: one orchestrator owns routing, termination, and the approval choke point.
- A governed shared task state with a **one-writer-per-field** permission matrix.
- Deterministic termination: plan resolved **OR** budget exhausted **OR** max turns **OR** circuit breaker.
- A hard per-task spend ceiling enforced *before* each sub-agent turn, plus model tiering by role.
- Sub-agent writes routed through the existing `PauseForApproval` → `approval_commit_handlers` path.
- An append-only coordination audit stream keyed on `workflow_id` carrying a policy **content** snapshot.
- Crash resumption at turn granularity with zero re-executed writes.

### 2.2 Explicit non-goals

- **Peer-to-peer agent messaging is rejected, not deferred.** Agents do not call each other. Every handoff routes through the supervisor. Rationale in §5.3 — this is the single most consequential change from the prior draft of this document, which offered P2P as a first-class topology.
- No new execution semantics in `WorkflowEngine`. If a design here needs the engine to change, the design is wrong (§5.1 shows why it doesn't).
- No agent long-term memory. Coordination state is per-task and expires with it.
- No multi-tenancy. Single-tenant v1; see §10.3 for the isolation shape v2 must take.
- No distributed execution. `colony/` owns that axis.

### 2.3 Deferred with reasons

| Deferred | Why not v1 |
|---|---|
| Consensus / voting swarm | Requires real concurrency. The engine is single-threaded and SQLite has one writer; a "parallel" swarm would serialize on the coordination table and prove nothing. Revisit after §10 stateless workers. |
| Hierarchical (supervisor-of-supervisors) | Only pays off on very long tasks; doubles the termination-ownership surface. |
| Cross-task research cache | Privacy review required on which fields are cacheable across tasks. |
| Dynamic agent spawning | Unbounded agent count defeats the static write-scope matrix that makes §6 checkable. |

---

## 3. Metric tree — what this is optimized for

A coordination layer with no outcome metric becomes feature theatre. The gate for shipping `multiagent/` is a measurable improvement in the L0, with none of the counter-metrics regressing.

```text
L0  accepted, policy-compliant task resolutions per eligible task
L1  eligible tasks × plan-completion rate × user-accepted (or verified-correct) rate
L2  per-role turn success, handoff schema-validation pass rate, budget headroom at
    termination, approval approve-rate, crash-resume fidelity, p95 task wall-clock
```

**Counter-metrics — hard floors, not dashboards:**

| Counter-metric | Floor |
|---|---|
| Unauthorized writes (write outside the agent's declared scope) | **0** |
| Duplicate writes surviving a crash-resume | **0** |
| Tasks exceeding the spend ceiling | **0** |
| Non-terminating tasks (hit max-turns without a plan verdict) | < 1% |
| p95 coordination overhead vs. single-agent baseline | < 2× |

The multi-agent-specific one: a right answer reached through a broken trajectory still fails. §12 scores trajectory and outcome separately.

---

## 4. Architecture

```text
┌───────────────────────────────────────────────────────────────────────────┐
│  multiagent/  (extension track)                                           │
│  Supervisor · SharedTaskState (ACL'd) · Role contracts · Budget ledger    │
│  Termination controller · Coordination audit stream                       │
├───────────────────────────────────────────────────────────────────────────┤
│  Agent execution layer (agent/)                                           │
│  AgentRunner · AgentStep protocol · ToolSpec · idempotent writes          │
├───────────────────────────────────────────────────────────────────────────┤
│  Core durable runtime (src/, stdlib + SQLite)                             │
│  WorkflowEngine · WorkflowStore · ApprovalGate · ModelRouter · Telemetry  │
└───────────────────────────────────────────────────────────────────────────┘
```

Draw order is deliberate and matches the coordination-first discipline: **orchestrator → shared state → agent pool → tool layer → audit stream → UI.** The agents are drawn fourth because they are the least interesting part.

**Principles**

1. **Core engine unchanged.** `WorkflowEngine` stays a linear step runner. All topology lives in extension-owned SQLite tables, mirroring `colony/store_ext.py:13`.
2. **State persisted before action.** Every turn result, state write, and budget decrement is checkpointed before the next dispatch.
3. **Writes are gated before execution, not confirmed after.** Sub-agent writes return `PauseForApproval` and execute only inside an `approval_commit_handlers` entry (`src/engine.py:146-164`).
4. **Termination is owned by exactly one component.** The supervisor. This is the reason P2P is rejected.
5. **Determinism offline.** Mock provider path in `ModelRouter` (`src/model_router.py:133`); no API key required for any test.

---

## 5. Coordination

### 5.1 The bounded turn loop — how a loop runs on a linear engine

The prior draft returned `status="in_progress"` from a step and expected re-enqueue. **The engine has no such semantics:** `_run_from_step` advances unconditionally (`src/engine.py:246`), and a step may return only a `StepResult` or a `PauseForApproval`.

The codebase already solved this, and `multiagent/` copies the solution rather than inventing one. `AgentRunner.register` (`agent/runner.py:139-146`) **pre-registers `max_turns` step slots up front**; each turn step short-circuits to a no-op once the trajectory is terminal (`agent/runner.py:150-151`). A bounded loop becomes a bounded, statically-known chain of steps.

This is the same discipline as "never loop until done": the turn budget is structural, visible in `engine.steps` before execution begins, and impossible to exceed.

```python
# multiagent/orchestrator.py
MAX_COORDINATION_TURNS = 12  # structural cap; also the registered step count

def register(self, engine: WorkflowEngine) -> None:
    steps: list[WorkflowStep] = [WorkflowStep("supervisor_plan", self._plan_step)]
    for index in range(MAX_COORDINATION_TURNS):
        name = f"coordination_turn_{index}"
        steps.append(WorkflowStep(name, self._make_turn_step(index, name)))
        # A denied write must not kill the task: the supervisor records the denial
        # and replans. Same policy AgentRunner uses (agent/runner.py:143).
        engine.dependencies["approval_rejection_policies"][name] = ApprovalRejectionPolicy.CONTINUE
        engine.dependencies["approval_commit_handlers"][name] = self._make_commit_handler(name)
    steps.append(WorkflowStep("synthesize", self._synthesis_step))
    engine.register_steps(steps)
```

**Consequence to state plainly:** crash granularity is the *turn*, because each turn is a step and each step is a checkpoint (`src/store.py:165`). Nothing finer is durable. A sub-agent that crashes mid-turn re-runs that turn from its start — which is safe precisely because writes inside it are idempotent (§8.2).

### 5.2 Termination

```text
Supervisor stops when:
    plan fully resolved (every step_status terminal)
 OR budget_remaining_usd <= 0            (hard ceiling, §9)
 OR turn_index == MAX_COORDINATION_TURNS (structural, §5.1)
 OR circuit breaker tripped              (§8.3)
```

Every one of these is deterministic and checkable from persisted state — no LLM decides when to stop. On budget or turn exhaustion the supervisor emits a **partial result with the trace**, never a crash: a booked flight with a deferred hotel beats a failed task.

### 5.3 Why peer-to-peer is rejected

The prior draft made "Peer-to-Peer Handoff" a first-class topology with agent-to-agent mailboxes. That is a defect, not a feature:

- **No owner of termination.** If A hands to B hands to C, no component can answer "are we done?" without a global scan, and no component is accountable for the budget.
- **Writes become unauditable.** The approval gate is a choke point only if all writes pass through one router. P2P scatters them.
- **Injection propagates.** A poisoned tool result read by A becomes an instruction to C with no validation boundary in between.

`AgentMessage` survives, but as a **supervisor-routed envelope**: `sender_id` is always a worker and `recipient_id` is always `"supervisor"`, or vice versa. Worker-to-worker delivery is rejected at the store layer, not by convention (§6.3).

### 5.4 Roles — one decision each

| Role | The single decision it makes | Write scope | Tools | Model tier |
|---|---|---|---|---|
| **Supervisor** | Route next work / declare termination | `plan`, `step_status`, `budget_remaining_usd` | none | strong |
| **Researcher ×N** | Gather evidence for one plan step | `results[step_id]` | read-only | cheap |
| **Decision** | Select among gathered options | `decision[step_id]` | none | strong |
| **Critic** | Approve or reject before commit | `critic_notes` (append-only) | none | cheap |
| **Executor** | Perform one real-world write | `exec_status` | write tools (gated) | cheap |

**Test:** if a role's decision cannot be stated in one sentence, split the role. **Rule:** no two roles share a write scope, and no role calls another role.

---

## 6. Domain model

### 6.1 Role contracts

Agents are stateless microservices with typed I/O. Every contract carries an **error variant with `retryable`** — a contract without one produces a supervisor that cannot distinguish "retry" from "replan".

```python
# multiagent/models.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ModelTier(StrEnum):
    """Resolved to a RoutingPolicy at dispatch — see §9.2.

    The prior draft's `model_alias: str = "primary"` referenced a registry that
    does not exist: RoutingPolicy (src/model_router.py:22) is a provider list
    with no alias concept.
    """
    CHEAP = "cheap"
    STRONG = "strong"


@dataclass(frozen=True)
class AgentDefinition:
    """Configuration and authority envelope for one role."""
    agent_id: str
    role_name: str                       # supervisor | researcher | decision | critic | executor
    system_prompt: str
    allowed_tools: frozenset[str]        # enforced at dispatch, §7.1
    write_scope: frozenset[str]          # enforced at state write, §6.3
    model_tier: ModelTier = ModelTier.CHEAP
    max_turns: int = 5                   # per-agent sub-budget within the global cap


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"              # budget or turn cap hit before completion


@dataclass(frozen=True)
class AgentTask:
    task_id: str
    workflow_id: str
    assigned_role: str
    description: str
    depends_on: tuple[str, ...] = ()
    status: TaskStatus = TaskStatus.PENDING
    result_ref: str | None = None        # key into shared state; the body lives there
    error_reason: str | None = None
    retryable: bool = False
    attempts: int = 0
```

`result_ref` replaces the prior `result_digest`: a digest cannot be read back. The body lives in `multiagent_state` under the role's own write scope; the task row holds only the pointer.

### 6.2 Supervisor-routed envelopes

```python
@dataclass(frozen=True)
class AgentMessage:
    message_id: str
    workflow_id: str
    sender_id: str
    recipient_id: str                    # "supervisor", or a worker agent_id
    payload: dict[str, Any]
    created_at: str = ""                 # ISO-8601 via utc_now(); matches src/store.py:57
    delivered_at: str | None = None      # ack cursor — see below
```

`created_at` is an ISO string, not the prior `timestamp_ms: float`, so it sorts and compares identically to every other timestamp in the codebase.

`delivered_at` fixes a correctness bug in the prior draft: a mailbox with no read cursor re-delivers every prior message after a crash-resume, so the supervisor re-dispatches completed work. `fetch_mailbox` returns undelivered messages only and stamps them within the same transaction that checkpoints the turn.

### 6.3 `MultiAgentStore` — extension-owned tables

Follows `colony/store_ext.py:13`: wrap a shared `WorkflowStore`, add extension tables, never fork the core schema.

```sql
CREATE TABLE IF NOT EXISTS multiagent_tasks (
    task_id       TEXT PRIMARY KEY,
    workflow_id   TEXT NOT NULL,
    assigned_role TEXT NOT NULL,
    description   TEXT NOT NULL,
    depends_on    TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'pending',
    result_ref    TEXT,
    error_reason  TEXT,
    retryable     INTEGER NOT NULL DEFAULT 0,
    attempts      INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE TABLE IF NOT EXISTS multiagent_messages (
    message_id   TEXT PRIMARY KEY,
    workflow_id  TEXT NOT NULL,
    sender_id    TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    delivered_at TEXT,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

-- Shared task state. One row per (workflow, field); the writer is enforced,
-- not documented. `version` makes a lost update detectable rather than silent.
CREATE TABLE IF NOT EXISTS multiagent_state (
    workflow_id  TEXT NOT NULL,
    field_key    TEXT NOT NULL,          -- 'plan' | 'results:<step_id>' | 'decision:<step_id>' | ...
    writer_id    TEXT NOT NULL,
    value        TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    expires_at   TEXT,                   -- TTL; NULL = task lifetime
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workflow_id, field_key),
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

-- Append-only coordination audit. Distinct from telemetry: telemetry is
-- operational, this is forensic and carries the policy content snapshot.
CREATE TABLE IF NOT EXISTS multiagent_audit (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id     TEXT NOT NULL,
    turn_index      INTEGER NOT NULL,
    actor_id        TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- dispatch | state_write | write_denied | approval | terminate
    policy_snapshot TEXT NOT NULL,       -- the authority envelope CONTENT at decision time
    detail          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id)
);

CREATE INDEX IF NOT EXISTS idx_ma_tasks_wf ON multiagent_tasks(workflow_id, status);
CREATE INDEX IF NOT EXISTS idx_ma_msgs_undelivered
    ON multiagent_messages(workflow_id, recipient_id, delivered_at);
CREATE INDEX IF NOT EXISTS idx_ma_audit_wf ON multiagent_audit(workflow_id, turn_index);
```

`policy_snapshot` stores the authority envelope **content** — the `allowed_tools` and `write_scope` in force at that moment — not a version ID. A policy ID that later changes meaning makes the audit trail worthless for the one question it exists to answer.

**Permission matrix, enforced in `write_state`:**

| `field_key` | Sole writer | TTL |
|---|---|---|
| `plan`, `step_status:*` | supervisor | task lifetime |
| `results:<step_id>` | the researcher assigned that `step_id` | 1 hour |
| `decision:<step_id>` | decision agent | task lifetime |
| `critic_notes` | append-only, any role | task lifetime |
| `exec_status:*` | executor | task lifetime |
| `budget_remaining_usd` | supervisor | task lifetime |

```python
class MultiAgentStore:
    def __init__(self, db_path: str | Path) -> None:
        self.workflow_store = WorkflowStore(db_path)   # shared connection settings, WAL on
        self._init_schema()

    def write_state(self, workflow_id: str, field_key: str, writer: AgentDefinition,
                    value: dict[str, Any], expected_version: int | None = None) -> int:
        """Reject any write outside the writer's declared scope.

        Enforcement lives here, at the only path that mutates shared state, so a
        scope violation is structurally impossible rather than prompt-discouraged.
        Raises WriteScopeViolation; the supervisor records it and replans.
        """

    def fetch_mailbox(self, workflow_id: str, agent_id: str) -> list[AgentMessage]:
        """Undelivered messages only; stamps delivered_at in the same transaction."""

    def append_audit(self, workflow_id: str, turn_index: int, actor_id: str,
                     event_type: str, policy_snapshot: dict[str, Any],
                     detail: dict[str, Any]) -> None: ...
```

---

## 7. Authority containment

### 7.1 `allowed_tools` is enforced, at a named place

The prior draft declared `allowed_tools` and never enforced it. Enforcement is at **dispatch**, in the orchestrator, before the sub-agent's `ToolSpec` map is constructed: the runner for a role is built with `[t for t in tools if t.name in role.allowed_tools]`, so an out-of-scope tool is not merely denied — it is not in the agent's namespace. A model that hallucinates it takes the existing `unknown_tool` path (`agent/runner.py:184`).

Violation handling: increment `unauthorized_writes_blocked`, append a `write_denied` audit row with the policy snapshot, and return the denial to the supervisor as an observation. Never silently drop.

### 7.2 Writes: policy gate before execution

Sub-agent writes reuse the core path unchanged. The executor's turn returns `PauseForApproval` (`src/engine.py:13`); the write itself happens **only** inside the commit handler, which the engine invokes after approval (`src/engine.py:146-164`), and executes through `AgentRunner._execute_write_once` (`agent/runner.py:270`) so it is idempotent by construction.

This is the distinction the prior draft's `if not deps.approval.is_approved(...)` polling idiom erased: a confirmation step is not a policy gate. The gate is synchronous, pre-execution, and recorded.

### 7.3 Cross-agent prompt injection

The new attack surface multi-agent creates: a poisoned document read by a Researcher becomes an instruction the Decision agent acts on.

**Defense at the supervisor handoff, not in system prompts.** Every sub-agent output is untrusted input. Before it enters shared state it is validated against the role's output contract: required keys present, no unexpected keys, types correct, no tool-invocation syntax in free-text fields. Validation failure → quarantine to `critic_notes`, audit row, replan. The system prompt is not a security boundary and delimiters are not a parser.

---

## 8. Reliability

### 8.1 Crash recovery — the corrected narrative

The prior draft's diagram was internally inconsistent (it resumed *at* the last completed step; `resume()` starts at `current_step + 1`, `src/engine.py:95`) and attributed to idempotency keys a behavior they do not have ("side effects are reused").

What actually happens:

```text
step 0  supervisor_plan       → checkpoint (store.py:165); plan + budget in multiagent_state
step 1  coordination_turn_0   → Researcher-1 result checkpointed; mailbox stamped delivered
step 2  coordination_turn_1   → Executor requests write → PauseForApproval (engine.py:212-225)
        operator approves     → ApprovalGate.approve (approval.py:76)
step 2' commit handler runs   → _execute_write_once logs idempotency key (runner.py:270-289)

--- os._exit(1) immediately after the write lands, before the next checkpoint ---

restart → engine.resume(workflow_id)
        → status is APPROVED, so _resume_index_after_approval runs (engine.py:96-97)
        → commit handler is re-entered for step 2
        → get_side_effect(key) returns the logged result (store.py:306)
        → the tool handler is NOT called a second time;
          duplicate_side_effects_prevented += 1 (runner.py:282)
        → resume continues at step 3; steps 0-1 are never re-executed
```

The narrow local fact is precise: **`side_effect_log.idempotency_key` is a PRIMARY KEY (`src/store.py:124`), so a duplicated local mock result is structurally impossible to log.** A retry returns the recorded local result. This is mock-replay suppression, not authorization, remote exactly-once delivery, or effect reconciliation.

### 8.2 Failure modes and where each is handled

| Failure | Boundary | Response |
|---|---|---|
| Two researchers report conflicting evidence | researcher join | Decision agent arbitrates; both inputs retained in audit — never LLM-arbitrated state merge |
| Sub-agent loops without progress | supervisor | Loop detection on repeated idempotency signature; counts against turn cap |
| Sub-agent returns malformed output | handoff | Contract validation (§7.3) → quarantine → replan; do not feed it forward |
| Tool timeout mid-turn | tool layer | Existing `tool_timeout` path (`agent/runner.py:264`); one bounded retry, then escalate with partial trace — optimize for handoff, not blind resume |
| Stale research reused | shared state | `expires_at` TTL; expired reads force re-query |
| Write approved but process dies | executor → world | §8.1 idempotency suppression |
| Budget exhausted mid-plan | supervisor | Terminate with partial result + trace; status `ABANDONED`, not `FAILED` |

### 8.3 Circuit breaker

Trip conditions, each checked by the supervisor before dispatch: N consecutive turns with no state mutation; N consecutive contract-validation failures from one role; any `WriteScopeViolation`. Tripping terminates the task with a partial result and a `terminate` audit row. A tripped breaker is a bug report, not a retry.

---

## 9. Budget as architecture

The prior draft opened by citing unbounded token spend as a motivating failure and then designed nothing to prevent it. This section is that design.

### 9.1 Hard ceiling, enforced pre-dispatch

```python
@dataclass(frozen=True)
class BudgetPolicy:
    ceiling_usd: float                   # hard per-task cap
    reserve_for_synthesis_usd: float     # held back so the task can always close
    per_turn_max_usd: float              # a single runaway turn cannot drain the task
```

The supervisor decrements `budget_remaining_usd` in shared state from `StepResult.cost_usd` (`src/store.py:48`) after every turn and checks headroom **before** dispatching the next. No headroom → terminate with partial result. The check is arithmetic on persisted state, so it survives a crash and cannot be talked out of by a model.

### 9.2 Tiering: `ModelTier` → `RoutingPolicy`

`ModelTier` resolves to a real `RoutingPolicy` (`src/model_router.py:22`) at dispatch — cheap providers first for classify/extract/gather roles, the stronger provider reserved for planning, arbitration, and synthesis. Roles are assigned tiers in §5.4. When `budget_remaining_usd` drops below a down-tier threshold, the supervisor forces `CHEAP` for all remaining turns rather than failing the task: degrade quality before you degrade safety, and never silently.

**The economics to validate, not assert:** if a coordinated task averages ~8 model calls, uniform strong-tier routing costs roughly 4–5× a tiered mix. Tiering plus the synthesis reserve is what makes a multi-agent task cost-competitive with the single-agent baseline it must beat.

---

## 10. Scale

### 10.1 Coordination breaks before compute

Ordered by what fails first under load:

| Order | Bottleneck | Why more compute does not help |
|---|---|---|
| 1 | `multiagent_state` hot-key contention | SQLite has one writer; `plan` and `budget_remaining_usd` are written every turn |
| 2 | Supervisor throughput | One supervisor drives every dispatch decision serially |
| 3 | Provider rate limits | External APIs throttle before local compute saturates |
| 4 | Cost per task | Grows linearly with turns; §9 is the only defense |

Bottleneck 1 is why the consensus topology is deferred: a "parallel" swarm on this substrate serializes on the same table it is supposed to fan out around.

### 10.2 The v2 unlock (not built here)

Stateless workers pulling ready tasks from a queue; state externalized as the only stateful tier; a **per-task lease** on the supervisor so a lease expiry lets another instance resume from durable state (single-writer preserved, idempotency makes resumption safe). The pool scales across tasks, not within one task. `PostgresWorkflowStore` (`src/store.py:400`) is the existing seam for the state tier.

### 10.3 Multi-tenancy (v2)

Isolation belongs at the data layer — namespaced keys, per-tenant budget, per-tenant tool quotas — never a `tenant_id` in a prompt. A shared store plus a prompt-carried tenant ID is one injection away from cross-tenant leakage.

---

## 11. Tradeoff ledger

| Decision | Chose | Gave up | Why |
|---|---|---|---|
| Topology | Supervisor only | P2P flexibility | One owner of termination; one audit choke point |
| Turn loop | Pre-registered bounded steps | Dynamic loop length | Core engine unchanged; turn budget is structural |
| Shared state | ACL'd store, one writer per field | Scratchpad speed | Race-free, replayable, auditable |
| Writes | Pre-execution policy gate | Sub-agent autonomy | Zero unauthorized writes is a hard floor |
| Cost | Tiering + hard ceiling | Uniform top quality | Multi-agent must beat single-agent on cost, not just quality |
| Crash granularity | Per turn | Sub-turn resumption | Turn = step = checkpoint; finer needs engine changes |
| Concurrency | None in v1 | Parallel fan-out latency | Would serialize on the state table anyway (§10.1) |

Frame: **predictable, auditable, bounded execution over raw autonomy.**

---

## 12. Verification

### 12.1 Integration example (compiles against the real API)

```python
from pathlib import Path

from src.engine import ApprovalRejectionPolicy, WorkflowEngine
from src.approval import ApprovalGate
from src.store import StepResult, WorkflowStore
from src.telemetry import TelemetryLogger

from multiagent.models import AgentDefinition, BudgetPolicy, ModelTier
from multiagent.orchestrator import MultiAgentOrchestrator
from multiagent.store_ext import MultiAgentStore


def build_multiagent_workflow(
    db_path: Path,
    agents: list[AgentDefinition],
    budget: BudgetPolicy,
) -> tuple[WorkflowEngine, str]:
    ma_store = MultiAgentStore(db_path)
    store = ma_store.workflow_store
    approval = ApprovalGate(store)
    telemetry = TelemetryLogger(echo=False)

    orchestrator = MultiAgentOrchestrator(ma_store, agents, budget)

    engine = WorkflowEngine(
        store,
        telemetry,
        dependencies={
            "approval_gate": approval,
            "approval_rejection_policies": {},
            "approval_commit_handlers": {},
            "multiagent_orchestrator": orchestrator,
        },
    )
    # Registers supervisor_plan + MAX_COORDINATION_TURNS turn slots + synthesize,
    # and installs the per-step commit handlers (§5.1).
    orchestrator.register(engine)

    state = store.create_workflow(
        "multiagent",
        initial_data={"goal": "", "budget_remaining_usd": budget.ceiling_usd},
    )
    return engine, state.workflow_id
```

And one turn step, showing the three real return shapes:

```python
def _make_turn_step(self, turn_index: int, step_name: str):
    def run_turn(state, step_data, dependencies) -> StepResult | PauseForApproval:
        decision = self.supervisor.next_action(state.workflow_id, turn_index)

        if decision.is_terminal:                       # plan resolved / budget / breaker
            return StepResult(
                step_name=step_name,
                output={"terminated": True, "reason": decision.reason},
                duration_ms=0.0,
            )

        role = self.agents_by_id[decision.agent_id]
        if decision.requires_write_approval:
            gate_id = dependencies["approval_gate"].request_approval(
                state.workflow_id,
                step_name,
                {"tool_name": decision.tool_name, "tool_args": decision.tool_args,
                 "agent_id": role.agent_id},
            )
            # The write executes in the commit handler, after approval — never here.
            return PauseForApproval(gate_id, step_name,
                                    {"tool_name": decision.tool_name,
                                     "tool_args": decision.tool_args})

        outcome = self.dispatch(state.workflow_id, role, decision, turn_index)
        return StepResult(
            step_name=step_name,
            output={"agent_id": role.agent_id, "task_id": decision.task_id,
                    "result_ref": outcome.result_ref},
            duration_ms=outcome.latency_ms,
            cost_usd=outcome.cost_usd,
            model_used=outcome.model_used,
        )

    return run_turn
```

Corrections from the prior draft, each verified against source: `StepResult` takes `step_name` / `output` / `duration_ms` and has no `status` or `step_data` field (`src/store.py:44-50`); `PauseForApproval` takes `(gate_id, step_name, payload)` (`src/engine.py:13-17`); `dependencies` is a `dict`, keyed `"approval_gate"` (`src/engine.py:113`), and `ApprovalGate` exposes `check_approval` / `get_for_workflow`, not `is_approved` (`src/approval.py:55-74`); `WorkflowState` has `step_data`, not `input_data` (`src/store.py:33-40`); and imports come from `src.*` — `src/__init__.py` re-exports nothing.

### 12.2 Test plan

Determinism first: every test uses the `ModelRouter` mock path (`src/model_router.py:133`) and a `tmp_path` SQLite file. No test requires an API key.

**Coordination**
1. Supervisor decomposes a goal into a dependency-ordered plan; `depends_on` respected in dispatch order.
2. Plan resolves → workflow reaches `COMPLETED` before the turn cap.
3. Turn cap exhausted → task terminates `ABANDONED` with a partial result, not an exception.
4. Circuit breaker trips after N no-progress turns.

**Authority (hard gates — must be 0 failures)**
5. A role writing outside `write_scope` raises `WriteScopeViolation`; state is unchanged; a `write_denied` audit row with the policy snapshot exists.
6. A role invoking a tool outside `allowed_tools` never reaches the handler.
7. Every write turn pauses; approving executes exactly once; rejecting leaves zero rows in `side_effect_log` and the supervisor replans (`CONTINUE` policy).

**Reliability**
8. **Subprocess crash test:** run to a checkpointed turn, `os._exit(1)` in the child, resume in the parent; assert completed turns are not re-executed and `step_results` has no duplicate `step_index`.
9. **Crash immediately after an approved write:** on resume, `duplicate_side_effects_prevented == 1` and `side_effect_count` is unchanged.
10. Mailbox delivered-cursor: after resume, `fetch_mailbox` returns no previously-delivered message.
11. TTL expiry forces re-query rather than serving stale `results:*`.

**Budget**
12. Ceiling enforced pre-dispatch: a task whose next turn would exceed the ceiling terminates instead of dispatching; final cost ≤ ceiling.
13. Down-tier threshold forces `CHEAP` routing and the task still closes (synthesis reserve honored).

**Contracts**
14. Malformed sub-agent output is quarantined, not written to shared state.
15. Injected tool-invocation syntax in a research result does not reach the Decision agent's prompt.

**Coverage floor for merge:** items 5–9 and 12 are hard gates at 0 failures; the rest are soft.

### 12.3 Evaluation

Wire into the existing eval track rather than inventing a parallel one. `trajectory-evals-proposal.md` scores tool-policy compliance, ordering, termination, loops, and write attribution — all of which apply per sub-agent trajectory. Two additions are multi-agent-specific:

- **Handoff integrity:** every state write is attributable to a role that held the scope; every dispatch is attributable to a supervisor decision recorded in `multiagent_audit`.
- **Outcome vs. trajectory scored separately:** a correct final answer produced through a scope violation or an ungated write is a **failure**, not a pass.

---

## 13. Roadmap

**Phase 1 — coordination spine.** `multiagent/models.py` (contracts, `ModelTier`, `BudgetPolicy`), `multiagent/store_ext.py` (four tables, `write_state` enforcement, mailbox cursor), `multiagent/orchestrator.py` (pre-registered turn loop, termination controller, budget ledger). Tests 1–4, 8, 12.

**Phase 2 — authority and audit.** Tool-scope enforcement at dispatch, contract validation at handoff, `multiagent_audit` with policy snapshots, `multiagent/telemetry_ext.py` mirroring `colony/telemetry_ext.py:8`. Tests 5–7, 9–11, 14–15.

**Phase 3 — demo and docs.** `examples/multiagent_demo.py` (supervisor + 2 researchers + decision + gated executor, mock providers, crash injection). Sections in `docs/walkthrough.md` and `README.md`. Comparison table: single-agent baseline vs. coordinated team on cost, wall-clock, and completion under an identical seeded chaos schedule — the `colony/` benchmark discipline applied to coordination.

**Rollout:** `multiagent/` is additive and off by default. Existing `AgentRunner` workloads are untouched. The recommended progression for any deployment is v1 single agent with gated writes → v2 supervisor + executor → v3 full role set — adopt a rung only when §1.1 names the trigger.

---

## 14. Close

**Tradeoff:** predictable, auditable, bounded coordination over agent autonomy. Rejected P2P in one line: no owner of termination, and writes become unauditable.

**Platform loop:** the reusable artifact here is not "a multi-agent framework." It is the pattern — *supervisor-owned termination, disjoint write scopes enforced at the store, a pre-execution policy gate, a hard budget ceiling, and a forensic audit stream* — which is the same shape whether the agents are booking travel, triaging support tickets, or patching code. Once it lands twice, it becomes a deployment module and the friction goes back to core.

> **Multi-agent frameworks build agent teams. DurableFlow's `multiagent/` extension makes a team's termination deterministic, its writes pre-authorized and idempotent, its spend capped, and its whole trajectory replayable after the process dies.**

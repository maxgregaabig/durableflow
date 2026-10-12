# Proposal: Core Lifecycle Evidence

**Status:** PROPOSAL  
**Scope:** Core runtime (`src/`) plus thin operator/demo surfaces — not a new peer extension package  
**Owner:** Marcos Polanco  
**Created:** 2026-08-11  
**Repository:** `durableflow`  
**Depends on:** `WorkflowStore`, `WorkflowEngine`, `ApprovalGate`, `TelemetryLogger`, existing inbox / crash / readiness demos  
**Dependency policy:** Core remains Python standard library only. No network, no UI framework, no required Postgres. Optional operator views stay local (CLI / static HTML from SQLite).  
**Visibility:** Private implementation guide. Public artifacts after ship: tests, seed fixtures, updated walkthrough claims, and a requirements→evidence matrix.

---

## 0. Positioning

DurableFlow already proves the hard operational claim:

> Checkpoint after every completed unit of progress; resume after process death; gate side effects; separate operator decisions from execution state.

That claim is true in demos and tests, but the **evidence path is uneven**. Status changes are scattered across the engine; telemetry is best-effort JSONL rather than co-committed history; crash recovery is real but not named as a policy; terminal re-runs rewrite the same workflow row rather than preserving attempt history; there is no first-class cancel; and a reviewer cannot point at one pure function and enumerate legal status moves.

This proposal upgrades **lifecycle legibility** without changing the teaching thesis or growing the engine into a graph orchestrator.

**Load-bearing claim (falsifiable):**

> After implementation, every durable status change is (1) admitted by a pure transition table, (2) co-committed with a monotonic lifecycle event in the same SQLite transaction as the status write, and (3) attributable to a concrete attempt — so a reviewer can reconstruct “what happened, in order, under which attempt, why it stopped” from SQLite alone, without replaying process memory or parsing JSONL as source of truth.

**What this is not:**

- A product agent console or React SPA  
- A replacement for Temporal / LangGraph  
- Engine-level loops, branching, or back-edges  
- Replacing `step_results` or approval-queue separation  
- Claiming exactly-once delivery to remote side effects (local idempotency stays as today)

---

## 1. Problem statement

| Gap | Today | Cost to learners / reviewers |
|-----|--------|------------------------------|
| Status transitions | Ad-hoc `update_status(...)` from ~12 sites in `engine.py` + crash marking in `store.py` | No single table of legal moves; hard to prove exhaustiveness |
| Execution history | `step_results` + JSONL telemetry | Telemetry can lag or be deleted; not transactionally bound to checkpoints |
| Attempts | One mutable workflow row for the whole life of an id | “Failed then succeeded on retry” is invisible; readiness/evals lose trajectory |
| Cancel | Pause/reject only | No clean operator abort while running |
| Boot recovery | Implicit: mark `running` → `crashed`, then `resume()` | Opposite of “fail orphans” systems; policy is not a named, testable strategy |
| Concurrency | Process + SQLite discipline | Double-start of the same workflow is not DB-enforced |
| Onboarding | Demos produce state by running | No seed that materializes every status for walkthrough without side effects |
| Evidence map | Spec claim IDs exist; root README does not map claim → file → test | Reviewers hunt across packages |

---

## 2. Design overview

Five additive primitives, one policy enum, two optional surfaces:

```text
┌─────────────────────────────────────────────────────────────┐
|  Optional: seed fixture + read-only operator view (CLI)     |
├─────────────────────────────────────────────────────────────┤
|  WorkflowEngine (still linear)                              |
|    uses transition() · cancel() · start_attempt()           |
├─────────────────────────────────────────────────────────────┤
|  WorkflowStore                                              |
|    workflows (+ attempt, lifecycle fields)                  |
|    workflow_events (monotonic cursor, co-committed)         |
|    partial uniqueness: one active execution per workflow    |
├─────────────────────────────────────────────────────────────┤
|  Pure: transitions.py (status × event → next | illegal)     |
└─────────────────────────────────────────────────────────────┘
         │
         ▼ existing (unchanged contracts)
   step_results · approval_queue · side_effect_log · JSONL sinks
```

**Invariant set (named for tests):**

| ID | Invariant |
|----|-----------|
| **INV-LIFECYCLE-001** | Every durable status change goes through `transition(current, event)`. Illegal pairs raise; no silent overwrite. |
| **INV-LIFECYCLE-002** | Status update and its lifecycle event commit in the **same** SQLite transaction. |
| **INV-LIFECYCLE-003** | `workflow_events.id` is a monotonic, unique cursor per database (not promised gapless). Replay is `id > cursor`. |
| **INV-LIFECYCLE-004** | Lifecycle events drive the machine; observational events (logs, progress, cost notes) never call `transition`. |
| **INV-LIFECYCLE-005** | At most one *active* attempt per `workflow_id` (`pending`/`running`/`paused_approval`/`approved` — final list fixed in Phase 0). |
| **INV-LIFECYCLE-006** | A terminal attempt outcome is immutable. Operator re-run after `failed` / `rejected` / `cancelled` opens attempt N+1; crash **resume** continues the same attempt. |
| **INV-LIFECYCLE-007** | Boot recovery is a named `RecoveryPolicy`; default remains resume-oriented, not fail-orphans. |

---

## 3. Detailed design

### 3.1 Pure transition table

New module: `src/transitions.py` (stdlib only).

```python
# src/transitions.py (sketch)
from __future__ import annotations

from enum import StrEnum
from typing import Literal

from .store import WorkflowStatus


class LifecycleEvent(StrEnum):
    START = "start"                 # pending|crashed|approved → running
    PAUSE_APPROVAL = "pause_approval"
    APPROVE = "approve"
    REJECT = "reject"
    COMPLETE = "complete"
    FAIL = "fail"
    CANCEL = "cancel"
    MARK_CRASHED = "mark_crashed"   # boot sweep only
    # resume after crash uses START (or explicit RESUME if we want distinct audit)


class IllegalTransition(Exception):
    def __init__(self, current: WorkflowStatus, event: LifecycleEvent) -> None:
        super().__init__(f"illegal: {current.value} + {event.value}")
        self.current = current
        self.event = event


def transition(current: WorkflowStatus, event: LifecycleEvent) -> WorkflowStatus:
    """Return next status or raise IllegalTransition.

    Exhaustive: every (status, event) pair is either listed or illegal.
    """
    table: dict[tuple[WorkflowStatus, LifecycleEvent], WorkflowStatus] = {
        (WorkflowStatus.PENDING, LifecycleEvent.START): WorkflowStatus.RUNNING,
        (WorkflowStatus.CRASHED, LifecycleEvent.START): WorkflowStatus.RUNNING,
        (WorkflowStatus.APPROVED, LifecycleEvent.START): WorkflowStatus.RUNNING,
        (WorkflowStatus.RUNNING, LifecycleEvent.PAUSE_APPROVAL): WorkflowStatus.PAUSED_APPROVAL,
        (WorkflowStatus.PAUSED_APPROVAL, LifecycleEvent.APPROVE): WorkflowStatus.APPROVED,
        (WorkflowStatus.PAUSED_APPROVAL, LifecycleEvent.REJECT): WorkflowStatus.REJECTED,
        (WorkflowStatus.RUNNING, LifecycleEvent.COMPLETE): WorkflowStatus.COMPLETED,
        (WorkflowStatus.RUNNING, LifecycleEvent.FAIL): WorkflowStatus.FAILED,
        (WorkflowStatus.PENDING, LifecycleEvent.CANCEL): WorkflowStatus.CANCELLED,
        (WorkflowStatus.RUNNING, LifecycleEvent.CANCEL): WorkflowStatus.CANCELLED,
        (WorkflowStatus.PAUSED_APPROVAL, LifecycleEvent.CANCEL): WorkflowStatus.CANCELLED,
        (WorkflowStatus.RUNNING, LifecycleEvent.MARK_CRASHED): WorkflowStatus.CRASHED,
        # absorbing terminals: omitted → illegal
    }
    key = (current, event)
    if key not in table:
        raise IllegalTransition(current, event)
    return table[key]
```

**Note on `CANCELLED`:** add `WorkflowStatus.CANCELLED = "cancelled"` as a terminal peer of `FAILED` / `REJECTED` / `COMPLETED`.

**Approval queue** stays a separate table and status layer (do not collapse into workflow status). Optional Phase 1: a tiny pure function for `pending → approved|rejected` on the gate row only — still two layers.

Engine call sites become:

```python
# instead of: self.store.update_status(workflow_id, WorkflowStatus.RUNNING)
self.store.apply_lifecycle(
    workflow_id,
    LifecycleEvent.START,
    payload={"reason": "execute"},
)
```

### 3.2 Co-committed `workflow_events`

```sql
-- additive schema (WorkflowStore._init_schema)
CREATE TABLE IF NOT EXISTS workflow_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,  -- cursor
    workflow_id     TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 1,
    kind            TEXT NOT NULL CHECK (kind IN ('lifecycle', 'observational')),
    type            TEXT NOT NULL,  -- start|complete|fail|cancel|step_checkpoint|...
    step_name       TEXT,
    payload         TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_events_wf_id
    ON workflow_events (workflow_id, id);
```

**Single write path:**

```python
# store sketch
def apply_lifecycle(
    self,
    workflow_id: str,
    event: LifecycleEvent,
    *,
    payload: dict[str, Any] | None = None,
    step_name: str | None = None,
) -> WorkflowState:
    with self.connect() as conn:
        row = conn.execute(
            "SELECT * FROM workflows WHERE workflow_id = ? FOR UPDATE",  # SQLite: BEGIN IMMEDIATE
            (workflow_id,),
        ).fetchone()
        # SQLite: use BEGIN IMMEDIATE on the connection for write serialization
        current = WorkflowStatus(row["status"])
        nxt = transition(current, event)
        now = utc_now()
        conn.execute(
            "UPDATE workflows SET status = ?, updated_at = ? WHERE workflow_id = ?",
            (nxt.value, now, workflow_id),
        )
        conn.execute(
            """
            INSERT INTO workflow_events
              (workflow_id, attempt, kind, type, step_name, payload, created_at)
            VALUES (?, ?, 'lifecycle', ?, ?, ?, ?)
            """,
            (
                workflow_id,
                row["attempt"],
                event.value,
                step_name,
                json.dumps(payload or {}),
                now,
            ),
        )
        # commit via context manager
        return self._load(conn, workflow_id)
```

**Checkpoint co-commit (recommended same PR as Phase 1):** when persisting a `StepResult`, insert an observational (or lifecycle-adjacent) event `type=step_checkpoint` in the **same** transaction as the `step_results` insert + `current_step` bump. That closes the “status moved but step not durable” teaching gap without making every log line transactional.

**JSONL telemetry** remains a **sink** of events, not the source of truth:

```python
# after apply_lifecycle commits
self.telemetry.log(WorkflowEvent(
    event_type=f"lifecycle.{event.value}",
    workflow_id=workflow_id,
    step_name=step_name,
    metadata={"attempt": attempt, "event_id": event_id, **payload},
))
```

Sinks stay best-effort (must not fail execution).

### 3.3 Attempts: resume vs re-run

| Operator / system action | Attempt | Semantics |
|--------------------------|---------|-----------|
| Crash mid-step, process restart, `resume()` | **same** | Continue from `current_step + 1` |
| Terminal `failed` / `rejected` / `cancelled`, then operator re-run | **N+1** | New attempt row fields; prior terminal outcome frozen in events |
| `completed` | — | No re-run by default (opt-in “clone workflow” later, out of scope) |

Schema addition on `workflows` (minimal):

```sql
ALTER TABLE workflows ADD COLUMN attempt INTEGER NOT NULL DEFAULT 1;
-- Optional denormalized helper; history lives in workflow_events
ALTER TABLE workflows ADD COLUMN terminal_reason TEXT;
```

Or, if we want immutable attempt snapshots without rewriting history:

```sql
CREATE TABLE IF NOT EXISTS workflow_attempts (
    workflow_id     TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    status          TEXT NOT NULL,  -- terminal snapshot when attempt ends
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    terminal_reason TEXT,
    PRIMARY KEY (workflow_id, attempt)
);
```

**MVP preference:** `workflows.attempt` + event stream (no second table) to keep blast radius small. Add `workflow_attempts` only if evals need a closed attempt row without scanning events.

```python
def start_new_attempt(self, workflow_id: str, *, reason: str) -> WorkflowState:
    """Only legal from failed|rejected|cancelled. Increments attempt; status → pending."""
    ...
```

**Colony / agent:** document that job-stage recovery stays same-attempt (like crash resume); batch-level “retry job from stage 0” is a new attempt if productized later.

### 3.4 Cancel

```python
def cancel(self, workflow_id: str, *, by: str = "operator", reason: str = "") -> WorkflowState:
    return self.store.apply_lifecycle(
        workflow_id,
        LifecycleEvent.CANCEL,
        payload={"by": by, "reason": reason},
    )
```

Legal from `pending`, `running`, `paused_approval` (exact set locked in transition table). Side effects already committed stay committed (idempotency log unchanged). Pending approval gates: mark gate row `cancelled` or leave pending with workflow terminal — **decision:** workflow cancel supersedes pending gate (gate status → `cancelled`, workflow → `cancelled`) in one transaction.

### 3.5 Named recovery policy

```python
class RecoveryPolicy(StrEnum):
    """What boot/startup does with non-terminal workflows left by a dead process."""

    MARK_CRASHED_AND_RESUME = "mark_crashed_and_resume"  # DurableFlow default (today's spirit)
    MARK_CRASHED_ONLY = "mark_crashed_only"              # leave for explicit resume()
    # FAIL_ORPHANS is intentionally NOT default — it contradicts the teaching claim.
    # May exist as an opt-in for demos that compare policies.
    FAIL_ORPHANS = "fail_orphans"


def recover_on_boot(store: WorkflowStore, policy: RecoveryPolicy) -> list[str]:
    ...
```

Today’s `mark_running_as_crashed` becomes the implementation of `MARK_CRASHED_*`. Tests assert policy behavior and lifecycle events with `type=mark_crashed`.

### 3.6 One active execution per workflow

SQLite cannot express Postgres-style partial unique indexes as cleanly, but we can approximate:

```sql
-- Option A: generated "active" flag
-- active = 1 only for non-terminal statuses; unique(workflow_id) where active=1
-- SQLite 3.8+ partial indexes:
CREATE UNIQUE INDEX IF NOT EXISTS workflows_one_active
ON workflows (workflow_id)
WHERE status IN ('pending', 'running', 'paused_approval', 'approved', 'crashed');
```

Wait — unique on `workflow_id` alone where active is tautological (PK already unique). The real race is **two processes** calling `execute` on the same id, not two rows.

**Correct enforcement:**

1. `BEGIN IMMEDIATE` on lifecycle admission  
2. Optional lease column: `executor_token TEXT`, `lease_expires_at TEXT`  
3. `execute` / `resume` refuse if lease held by another token and not expired  

For educational MVP, **BEGIN IMMEDIATE + transition checks** are enough; document multi-process lease as Phase 3.

What we *can* unique-constrain is **one inflight attempt row** if we materialize `workflow_attempts` with status in (`running`, …). With a single `workflows` row, PK already implies one current status — the gap is process fencing, not row cardinality.

### 3.7 Seed fixture (all statuses without interactive demos)

`data/lifecycle_seed.sql` or `examples/seed_lifecycle_demo.py` creates a scratch DB with workflows (and events) in:

- pending  
- running (synthetic mid-flight)  
- paused_approval + pending gate  
- approved (ready to resume)  
- rejected  
- completed (with step_results + side_effect)  
- failed  
- crashed  
- cancelled  
- completed on attempt 2 after failed attempt 1 (event history)

Walkthrough / learning-path Stage 0 can open this DB read-only and answer status questions **before** running demos.

### 3.8 Read-only operator surface (optional, thin)

Not a product UI. One of:

```bash
python3 -m src.operator status --db examples/foo.sqlite --workflow-id wf-001
python3 -m src.operator events --db ... --workflow-id wf-001 --from 0
python3 -m src.operator attempts --db ... --workflow-id wf-001
```

Output: current status, attempt, current_step, last lifecycle events, pending approval summary, side-effect keys present/absent. Stdlib only. HTML export optional later.

### 3.9 Requirements → evidence matrix

Add to root README or `docs/walkthrough.md` appendix:

| Claim | Module | Test / demo |
|-------|--------|-------------|
| Legal transitions only | `src/transitions.py` | `tests/test_transitions.py` |
| Co-committed lifecycle | `store.apply_lifecycle` | `tests/test_lifecycle_events.py` |
| Crash resume same attempt | `engine.resume` | `tests/test_resume.py`, `./start.sh crash` |
| Re-run new attempt | `store.start_new_attempt` | `tests/test_attempts.py` |
| Cancel terminal | `engine.cancel` | `tests/test_cancel.py` |
| Recovery policy | `store.recover_on_boot` | `tests/test_recovery_policy.py` |

---

## 4. Phased delivery

### Phase 0 — Spec freeze (no code behavior change)

- Freeze transition table for all current statuses + `CANCELLED`  
- Freeze event kinds/types vocabulary  
- Freeze attempt semantics (resume vs re-run)  
- Freeze recovery policy names and default  
- Update claim IDs in verification ledger as `PROPOSED`

**Exit:** written table + review sign-off; no runtime change.

### Phase 1 — Transition + co-committed events (core)

- `src/transitions.py` + exhaustive tests  
- `workflow_events` table  
- `apply_lifecycle` used by `WorkflowEngine` for all status writes  
- Checkpoint write co-commits observational `step_checkpoint`  
- JSONL remains sink  
- Migrate Postgres store path in parallel if still supported  

**Exit:** full suite green; new unit tests for illegal transitions and atomicity (kill mid-transaction simulation optional).

### Phase 2 — Cancel + recovery policy naming

- `CANCELLED` status end-to-end  
- `engine.cancel` + approval supersession rules  
- `RecoveryPolicy` wrapping existing crash marking  
- Lifecycle events for cancel and mark_crashed  

**Exit:** tests for cancel-from-running and cancel-from-paused; recovery policy tests.

### Phase 3 — Attempts

- `workflows.attempt` (or `workflow_attempts`)  
- `start_new_attempt` from terminal non-completed  
- Demo: reject → new attempt → approve → complete, with event history  
- Evals: optional scorer “attempt count / terminal immutability”  

**Exit:** multi-attempt fixture + tests; crash resume still same attempt.

### Phase 4 — Seed + operator CLI + docs matrix

- Seed DB  
- `python -m src.operator` (or `examples/operator_cli.py`)  
- README / walkthrough evidence matrix  
- Learning-path stage optional for events cursor  

**Exit:** Stage 0 of learning path can use seed without running demos.

---

## 5. Blast radius analysis

### 5.1 Summary matrix

| Surface | Phase | Risk | Notes |
|---------|-------|------|-------|
| `src/transitions.py` | 1 | **Low** | New pure module; no callers until wired |
| `src/store.py` schema | 1–3 | **Medium** | Additive columns/tables; old DBs need migration path |
| `src/store.update_status` | 1 | **High** if removed abruptly | Prefer: implement via `apply_lifecycle` or deprecate behind shim |
| `src/engine.py` | 1–2 | **High** | All status writes; approval resume paths are subtle |
| `src/approval.py` | 2 | **Medium** | Cancel supersession of pending gates |
| `src/telemetry.py` | 1 | **Low** | Remains optional sink; shape may gain `event_id` |
| `PostgresWorkflowStore` | 1–3 | **Medium** | Must mirror schema + transactions |
| `tests/test_resume.py` etc. | 1–3 | **Medium** | Expect status sequences; may assert new events |
| Inbox / crash demos | 1–2 | **Low–Medium** | Behavior same; more rows in DB |
| Readiness pack | 2–3 | **Medium** | Scoring may see `cancelled`; attempt metadata optional |
| Agent runner | 2 | **Medium** | Cancel mid-turn; lease if multi-process |
| Colony | 3 | **Low** if attempt scoped to core workflows only | Job stages already have their own recovery; avoid double attempt models |
| Context ledger | — | **None** | Orthogonal tables |
| Evals | 3–4 | **Low–Medium** | New scorers optional; redaction still digests-only |
| Factory / CLEAR | 1–2 | **Low** | Uses engine; benefits from events automatically |
| Integrations (LangSmith) | 1 | **Low** | Can map lifecycle events later; must not become required |
| Docs / learning-path | 4 | **Low** | Line anchors may drift; prefer section links |
| Existing on-disk demo SQLite files | 1 | **Medium** | `CREATE IF NOT EXISTS` + default `attempt=1`; no rewrite of history |

### 5.2 Highest-risk areas (detail)

**1. Approval resume index (`_resume_index_after_approval`)**  
Today couples `PAUSED_APPROVAL` / `APPROVED` / `REJECTED` with step index. Lifecycle refactor must not change *when* the approval step re-runs vs advances. **Mitigation:** characterization tests that freeze current resume indices before refactor; then swap `update_status` for `apply_lifecycle` without changing control flow order.

**2. Dual writers of status**  
`engine.py` and `store.mark_crashed` both write status. If only the engine uses `transition()`, boot recovery can bypass the table. **Mitigation:** every status write, including boot, goes through `apply_lifecycle` / `transition`.

**3. Shim vs break `update_status`**  
Many tests and possibly extensions call `update_status` directly. **Mitigation Phase 1:**

```python
def update_status(self, workflow_id: str, status: WorkflowStatus | str) -> WorkflowState:
    """Deprecated path: derive event from (current → target) or raise.

    Prefer apply_lifecycle(event).
    """
```

Mapping target→event is ambiguous (several events could land on `running`). Safer shim: **require event** and delete free-form status sets from public API after tests migrate.

**4. SQLite transaction boundaries**  
Today checkpoint and status may be separate statements/connections. Co-commit requires one connection and one transaction for “step complete + lifecycle event + status.” **Mitigation:** introduce `store.checkpoint_step(...)` that does all three; engine uses only that after a successful step.

**5. Telemetry consumers**  
If anything parses JSONL as authoritative (eval export, LangSmith adapter), document that `workflow_events` is canonical after Phase 1. Adapters may dual-read during transition.

**6. Status string surface**  
Adding `cancelled` changes enums, readiness vocabulary, and any `match status` in demos. **Mitigation:** extend `WorkflowStatus`, update readiness allowed sets, add explicit tests.

**7. Attempt increment accidental misuse**  
If crash resume incorrectly increments attempt, cost/eval metrics double-count. **Mitigation:** tests that kill mid-workflow and assert `attempt` unchanged; only `start_new_attempt` increments.

### 5.3 What stays stable (non-goals / no blast)

- Linear `WorkflowEngine` (no loops in core)  
- `step_results` schema meaning  
- Approval queue as separate status layer  
- Side-effect idempotency key semantics  
- Mock providers default; no API keys  
- Extension packages remain siblings (`context/`, `colony/`, …)  
- Privacy: events store digests/refs in payload conventions where body-like data might appear (same as context/evals)  

### 5.4 Estimated code touch set

| Path | Nature of change |
|------|------------------|
| `src/transitions.py` | **New** |
| `src/store.py` | Schema, `apply_lifecycle`, checkpoint transaction, recovery policy |
| `src/engine.py` | Replace status writes; cancel; maybe attempt re-run API |
| `src/approval.py` | Cancel supersession; optional gate transition helper |
| `src/telemetry.py` | Optional event_id metadata only |
| `tests/test_transitions.py` | **New** |
| `tests/test_lifecycle_events.py` | **New** |
| `tests/test_cancel.py` | **New** |
| `tests/test_attempts.py` | **New** |
| `tests/test_recovery_policy.py` | **New** |
| `tests/test_resume.py`, `test_approval_gate.py`, `test_integration.py` | Adjust expectations |
| `tests/test_readiness.py` | If cancel appears in harness |
| `examples/*` | Optional cancel demo; seed script |
| `docs/dflow-spec.md`, `docs/dflow-arch.md`, `docs/walkthrough.md` | Claims + diagrams |
| `verification/ledger.json` | Append claim rows |
| `README.md` | Evidence matrix (Phase 4) |

Rough size: **~400–700 LOC core**, **~500–800 LOC tests**, docs separate. No new dependencies.

### 5.5 Rollback strategy

- Feature flag unnecessary if Phase 1 keeps observational compatibility (JSONL still written).  
- Schema is additive; rollback code leaves unused tables harmlessly.  
- If `update_status` shim retained for one release, external notebooks keep working.  

---

## 6. Code sketches (engine integration)

```python
# engine.py excerpt (sketch)
def execute(self, workflow_id: str) -> WorkflowState:
    state = self.store.load_workflow(workflow_id)
    if state.status == WorkflowStatus.COMPLETED:
        return state
    self.store.apply_lifecycle(workflow_id, LifecycleEvent.START, payload={"via": "execute"})
    return self._run_from_step(workflow_id, state.current_step + 1)


def _complete_step(self, workflow_id: str, index: int, result: StepResult) -> None:
    # ONE transaction: step_results + current_step + observational event
    self.store.checkpoint_step(workflow_id, index, result)
    self.telemetry.log(...)


def _fail(self, workflow_id: str, step_name: str, exc: BaseException) -> None:
    self.store.apply_lifecycle(
        workflow_id,
        LifecycleEvent.FAIL,
        step_name=step_name,
        payload={"error": type(exc).__name__, "message": str(exc)[:500]},
    )
```

Atomicity test sketch:

```python
def test_lifecycle_event_matches_status(tmp_path):
    store = WorkflowStore(tmp_path / "t.sqlite")
    store.create_workflow("wf", "demo", {})
    store.apply_lifecycle("wf", LifecycleEvent.START)
    state = store.load_workflow("wf")
    events = store.list_events("wf")
    assert state.status == WorkflowStatus.RUNNING
    assert events[-1]["kind"] == "lifecycle"
    assert events[-1]["type"] == "start"
    # count status transitions == count lifecycle events of transition types
```

Illegal transition:

```python
def test_completed_is_absorbing():
    with pytest.raises(IllegalTransition):
        transition(WorkflowStatus.COMPLETED, LifecycleEvent.START)
```

---

## 7. Interaction with existing proposals

| Proposal | Interaction |
|----------|-------------|
| Front-Pressure | Human intervention envelopes can **reference** `workflow_events.id` as evidence pointers; do not replace lifecycle table |
| Trajectory evals | Attempt boundaries + ordered lifecycle/step events are better scorer inputs than JSONL alone |
| Experiment replay | Replay cursor = `workflow_events.id`; same log for live and history |
| Multi-agent | Per-workflow lifecycle still applies; supervisor workflows get their own attempts |
| DataFlow | Artifacts remain separate; optional `payload` refs only |
| AWS / Vast | Recovery policy naming clarifies resume-vs-fail-orphans when mapping to workers |

This proposal is **prerequisite quality** for several roadmap items: they all want ordered, queryable execution evidence.

---

## 8. Acceptance criteria

1. `tests/test_transitions.py` enumerates the full legal table and samples illegal pairs.  
2. No production status write in `src/` bypasses `transition` (grep gate in CI or test).  
3. For a completed inbox demo, `workflow_events` contains an ordered lifecycle chain reconstructible without JSONL.  
4. Crash demo: same `attempt`, `mark_crashed` + `start` (or resume) events, step not duplicated.  
5. New: cancel demo or test leaves terminal `cancelled` and supersedes pending approval.  
6. New: failed → `start_new_attempt` → completed shows attempt 1 terminal + attempt 2 success in events.  
7. Stdlib-only core path; offline CI green on 3.11–3.13.  
8. Docs: transition diagram in `dflow-arch.md`; evidence matrix linked from walkthrough.  
9. Verification ledger rows for INV-LIFECYCLE-001…007 with evidence ranks.  

---

## 9. Trade-offs

| Choice | Why | Change if |
|--------|-----|-----------|
| Events in SQLite, JSONL as sink | Single local truth; demos stay inspectable | Multi-node workers need a log bus |
| Pure table in Python, not DB CHECK for all pairs | Readable teaching artifact; easier exhaustive tests | Adversarial writers outside engine become a threat |
| Attempts as column first, table later | Smaller migration | Evals need closed attempt snapshots without event scans |
| Default recovery = mark crashed + allow resume | Matches DurableFlow thesis | Host wants fail-fast orphans only |
| No product UI | Preserve lab scope | Operators need multi-tenant console (out of repo) |
| Cancel does not roll back side effects | Honesty about local idempotency | True compensating transactions (different proposal) |

---

## 10. Decision requested

Approve **Phase 0–1** as the next core hardening slice (transition table + co-committed `workflow_events` + engine wiring), with Phases 2–4 sequenced after the suite stays green.

Reject or defer if the priority is extension surface area (DataFlow, multi-agent) over core evidence quality — in that case keep this proposal as a dependency note on trajectory evals and front-pressure.

---

## 11. Suggested title alternatives (for linking)

Canonical file: `proposals/lifecycle-evidence-proposal.md`  

| Title | Use when |
|-------|----------|
| **Core Lifecycle Evidence** | Default — emphasizes co-committed proof |
| Workflow Transition Hardening | If scoped to Phase 0–1 only |
| Attempt-Aware Durable Execution | If Phase 3 is the headline for evals |

**Recommended public name:** *Core Lifecycle Evidence*.

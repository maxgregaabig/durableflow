# Proposal: nanoq as a DurableFlow Tool (Thin Adapter)

**Status:** PROPOSAL  
**Scope:** Optional integration package + demo workflow; **not** a core `src/` dependency  
**Owner:** Marcos Polanco  
**Created:** 2026-08-11  
**Repositories:** `durableflow` (host control plane), `nanoq` (text-to-SQL pipeline specimen; may be a sibling path or git submodule/symlink)  
**Depends on:** DurableFlow `WorkflowEngine`, `WorkflowStore`, `ApprovalGate`, agent tool surface (optional), existing readiness/MCP patterns for gated writes  
**Dependency policy:**  
- DurableFlow **core** remains stdlib-only and offline by default.  
- nanoq is an **optional extra** (or subprocess boundary) — never imported at module top level in `src/`.  
- Default demos and CI on DurableFlow stay green **without** nanoq installed.  
- nanoq’s own pins (CPython 3.12.x, hashed lock) apply only to the optional path / nested venv / subprocess.  
**Visibility:** Private implementation guide. Public artifacts after ship: optional extra, adapter tests with mocks, composition demo, short walkthrough section.

---

## 0. Positioning

**DurableFlow** teaches the durable *shell*: checkpoint steps, survive crashes, gate consequential writes, account for model cost, keep evidence.

**nanoq** teaches a *domain agent pipeline*: natural language → safe read-only SQL → grounded result, with triple read-only enforcement, one LLM call site, and measured evaluation gates.

They answer different questions:

| System | Load-bearing question |
|--------|----------------------|
| DurableFlow | Can multi-step work **survive** and be **governed**? |
| nanoq | Can this question be answered with **safe, grounded SQL**? |

Together they illustrate a production composition rule:

> Domain guardrails without a durable shell: a correct SQL agent that dies mid-run or double-fires a **downstream** write.  
> A durable shell without domain guardrails: a workflow that resumes perfectly into a destructive query.  
> Production needs **both** — nanoq-class discipline *inside* a tool call; DurableFlow-class discipline *around* steps and side effects.

**Load-bearing claim (falsifiable):**

> A DurableFlow workflow can invoke nanoq through a thin adapter as **one durable step (or one agent tool)**, re-run that step safely after a crash (read-only re-execution), and only apply ApprovalGate + side-effect idempotency to **non-SQL consequences** of the answer — without re-implementing nanoq’s eight stages as engine steps, without making nanoq a required core dependency, and without weakening nanoq’s read-only architecture.

**What this is not:**

- Merging the two repos into one product  
- Re-hosting nanoq stages as `WorkflowEngine` steps (stage-level durability)  
- Teaching DurableFlow as a text-to-SQL framework  
- Making `sqlglot` / nanoq’s lockfile part of DurableFlow core CI  
- Claiming nanoq’s NFR-Q2/L2 live-model gates via DurableFlow readiness scores  
- Approval-gating every SELECT by default  

---

## 1. Problem / opportunity

Today the two labs sit as **siblings** (composition is verbal). Reviewers and learners do not get a runnable artifact that shows:

1. Where **domain safety** ends (nanoq RO stack).  
2. Where **workflow durability** begins (checkpoint around the tool).  
3. Where **HITL and writes** attach (only after an answer exists).  

Without a thin integration, people either under-compose (“they’re unrelated demos”) or over-merge (“fork nanoq into the engine”).

---

## 2. Integration model

### 2.1 Levels of wrap (only Level 1 is in scope for v1)

| Level | Description | v1? |
|-------|-------------|-----|
| **0** | Shell out to `nanoq` CLI, parse stdout | Demo-only emergency; not normative |
| **1** | **Thin adapter** → structured DTO; one DF step or agent tool | **Yes — default** |
| **2** | Each nanoq stage is a DF checkpoint | **No** (optional later teaching claim only) |
| **3** | Reimplement nanoq stages inside DurableFlow | **No** |

**Rule:** DurableFlow owns **workflow survival and consequential writes**. nanoq owns **read-only query correctness inside one call**. Do not make DF own SQL stages.

```text
┌──────────────────────────────────────────────────────────────┐
│  DurableFlow workflow (linear engine)                        │
│                                                              │
│  [step]  ingest / clarify question                           │
│  [step]  nanoq_query  ──thin adapter──►  nanoq pipeline      │
│            │                              (stages 1–8)       │
│            │                              RO × 3, 1× LLM     │
│            ▼                                                 │
│          StepResult (structured, digests preferred)          │
│  [step]  draft_action (optional; model)                      │
│  [step]  approval_gate  ◄── only if write/export             │
│  [step]  side_effect (email / ticket / CRM) + idempotency    │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 Two host surfaces (same adapter)

| Surface | How nanoq is used | Approval on nanoq call? |
|---------|-------------------|-------------------------|
| **Workflow step** | `register_step("nanoq_query", ...)` | **No** (RO) |
| **Agent tool** | Tool in `agent/` / mini_react tool list | **No** for query; **Yes** for any write tool that consumes the answer |

One adapter implementation; two wiring entry points.

---

## 3. Adapter contract

### 3.1 Package placement

```text
integrations/nanoq_adapter.py     # lazy import / protocol
integrations/nanoq_types.py       # DTOs shared with demos/tests (no nanoq import)
examples/nanoq_composition_demo.py
tests/test_nanoq_adapter.py       # mock backend; skip if nanoq absent for live path
```

Optional:

```text
pyproject.toml  [project.optional-dependencies]
  nanoq = []   # documented sibling install; or pin path-extra later
```

Do **not** put imports under `src/` core modules.

### 3.2 Input / output DTOs

```python
# integrations/nanoq_types.py (stdlib only)
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NanoqOutcome(StrEnum):
    OK = "ok"
    BLOCKED = "blocked"                 # intent/safety refuse
    VALIDATION_FAILED = "validation_failed"
    COST_REFUSED = "cost_refused"
    TIMEOUT = "timeout"
    ERROR = "error"
    DRY_RUN_OK = "dry_run_ok"           # validated + planned, not executed


@dataclass(frozen=True)
class NanoqQueryRequest:
    question: str
    db_path: str
    catalog_path: str | None = None
    dry_run: bool = False
    llm_mode: str = "mock"              # mock | http — default mock for DF demos
    # Optional correlation for DF telemetry
    workflow_id: str | None = None
    step_name: str | None = None
    idempotency_key: str | None = None  # hash inputs for optional LLM re-call suppression


@dataclass(frozen=True)
class NanoqQueryResult:
    ok: bool
    outcome: NanoqOutcome
    route: str                          # llm | fast_path | sql_file | blocked | ...
    narrative: str = ""
    row_count: int = 0
    # Privacy-safe by default (digests); raw fields only when explicitly enabled
    sql_digest: str | None = None
    question_digest: str | None = None
    sql: str | None = None              # gated: demo / NANOQ_DF_SEND_RAW
    # Presentation-safe table for demos (bounded rows); never unbounded dumps
    preview_rows: list[dict[str, Any]] = field(default_factory=list)
    error_message: str | None = None
    stage_timings_ms: dict[str, float] = field(default_factory=dict)
    backend: str = "mock"               # mock | inprocess | subprocess

    def as_step_output(self) -> dict[str, Any]:
        """Payload suitable for StepResult.output / tool observation."""
        return {
            "ok": self.ok,
            "outcome": self.outcome.value,
            "route": self.route,
            "narrative": self.narrative,
            "row_count": self.row_count,
            "sql_digest": self.sql_digest,
            "question_digest": self.question_digest,
            "sql": self.sql,
            "preview_rows": self.preview_rows,
            "error_message": self.error_message,
            "stage_timings_ms": self.stage_timings_ms,
            "backend": self.backend,
        }
```

### 3.3 Backend protocol (testability)

```python
# integrations/nanoq_adapter.py (sketch)
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .nanoq_types import NanoqQueryRequest, NanoqQueryResult


@runtime_checkable
class NanoqBackend(Protocol):
    def run(self, request: NanoqQueryRequest) -> NanoqQueryResult: ...


class MockNanoqBackend:
    """Deterministic fixture backend — default for DurableFlow CI."""

    def __init__(self, fixture: NanoqQueryResult | None = None) -> None:
        self.fixture = fixture

    def run(self, request: NanoqQueryRequest) -> NanoqQueryResult:
        if self.fixture is not None:
            return self.fixture
        # minimal success shaped like sample Q2 customers question
        return NanoqQueryResult(
            ok=True,
            outcome=NanoqOutcome.OK if not request.dry_run else NanoqOutcome.DRY_RUN_OK,
            route="mock",
            narrative="Mock: top customers by order amount (fixture).",
            row_count=5,
            sql_digest="sha256:mock",
            question_digest="sha256:mock-q",
            backend="mock",
        )


class InProcessNanoqBackend:
    """Lazy-imports nanoq pipeline. Optional; skipped if package missing."""

    def run(self, request: NanoqQueryRequest) -> NanoqQueryResult:
        try:
            # import only here — never at durableflow core import time
            from nanoq.pipeline import run_pipeline  # illustrative API
        except ImportError as exc:
            raise RuntimeError(
                "nanoq is not installed; use MockNanoqBackend or install the nanoq extra"
            ) from exc
        raw = run_pipeline(...)  # map to NanoqQueryResult; redact by default
        return map_nanoq_raw_to_result(raw, request)


class SubprocessNanoqBackend:
    """
    Isolation boundary: separate venv/interpreter (e.g. CPython 3.12) via CLI.
    Prefer when version pins diverge from DurableFlow's 3.11–3.13 CI matrix.
    Requires nanoq to emit machine-readable JSON (see open questions §10).
    """

    def run(self, request: NanoqQueryRequest) -> NanoqQueryResult:
        ...
```

**Default in DurableFlow tests:** `MockNanoqBackend`.  
**Default in composition demo:** mock unless `DURABLEFLOW_NANOQ=1` + nanoq available.  
**Live path:** gated, never required for `./start.sh test`.

### 3.4 Workflow step wiring

```python
# examples/nanoq_composition_demo.py (sketch)
def nanoq_query_step(state, step_data, deps):
    backend: NanoqBackend = deps["nanoq_backend"]
    req = NanoqQueryRequest(
        question=step_data["question"],
        db_path=deps["nanoq_db"],
        catalog_path=deps.get("nanoq_catalog"),
        llm_mode=deps.get("nanoq_llm_mode", "mock"),
        workflow_id=state.workflow_id,
        step_name="nanoq_query",
        dry_run=bool(step_data.get("dry_run", False)),
    )
    result = backend.run(req)
    # Non-ok outcomes are still a completed step (domain refuse ≠ engine crash)
    # unless deps policy says fail_workflow_on_block
    return StepResult(
        step_name="nanoq_query",
        output=result.as_step_output(),
        duration_ms=sum(result.stage_timings_ms.values()),
        cost_usd=0.0,  # or map nanoq cost if exposed; DF model $ separate
    )


def draft_export_step(state, step_data, deps):
    nq = step_data["nanoq_query"]  # prior step output merged into step_data
    if not nq.get("ok"):
        return StepResult("draft_export", {"skipped": True, "reason": nq.get("outcome")})
    # build a proposed email/ticket body from narrative + digests
    return StepResult("draft_export", {"draft": ..., "needs_approval": True})


def approval_gate_step(...):
    return PauseForApproval(...)  # existing primitive


def send_export_step(state, step_data, deps):
    # existing side_effect_log + idempotency pattern
    ...
```

Macro flow for the demo:

```text
set_question → nanoq_query → draft_export → approval_gate → send_export
```

Crash **during** `nanoq_query`: on resume, step re-runs. Safe because nanoq is read-only (and mock is pure).  
Crash **after** `send_export` checkpoint: side-effect log suppresses a duplicate mock send; it does not establish a remote outcome.

### 3.5 Agent tool wiring (optional same PR or Phase 2)

```python
# agent/tools.py or integrations/nanoq_tool.py
def make_nanoq_tool(backend: NanoqBackend, db_path: str) -> Callable:
    def nanoq_ask(question: str, dry_run: bool = False) -> dict:
        result = backend.run(NanoqQueryRequest(
            question=question, db_path=db_path, dry_run=dry_run, llm_mode="mock",
        ))
        return result.as_step_output()
    nanoq_ask.__name__ = "nanoq_ask"
    nanoq_ask.__doc__ = "Run a read-only analytical SQL question via nanoq. Never mutates data."
    return nanoq_ask
```

AgentRunner continues to gate **write** tools only. `nanoq_ask` is classified read-only in the tool manifest (same idea as read CRM vs write CRM).

---

## 4. Safety, privacy, and telemetry seams

### 4.1 Safety ownership matrix

| Concern | Owner | Integration rule |
|---------|-------|------------------|
| Mutation / DDL / authorizer | **nanoq** | Never bypass; adapter must not open a second write connection “for convenience” |
| Prompt injection in catalog | **nanoq** | Spotlighting stays inside nanoq; DF does not re-prompt with raw catalog |
| Human approval | **DurableFlow** | Only for export/send/write steps |
| Double send / double ticket | **DurableFlow** | `side_effect_log` + idempotency key |
| Crash mid-query | **DurableFlow** outer step | Re-execute tool; no nanoq internal checkpoints required |
| Crash mid-write | **DurableFlow** | Existing resume + idempotency |

### 4.2 Privacy

Align with DurableFlow context/evals posture:

- Persist **digests** of question and SQL in `step_results` / telemetry by default.  
- `preview_rows` bounded (e.g. ≤10 rows, ≤N chars).  
- Raw SQL/question only if explicit env (e.g. `DURABLEFLOW_NANOQ_SEND_RAW=1`) — treated as a data-governance decision, matching nanoq’s LangSmith raw flag spirit.  
- Do not ship customer DB files in the DurableFlow repo; demo uses nanoq sample DB path or a vendored copy under `examples/` with clear license.

### 4.3 Telemetry / observability

| Layer | Behavior |
|-------|----------|
| nanoq internal audit / LangSmith | Unchanged; fail-open; off by default |
| DurableFlow step telemetry | One event: `step.nanoq_query` with outcome, route, digests, duration |
| Nested stage export into DF | **Out of scope v1** (avoid double-counting latency NFRs) |

Eval subprocesses in nanoq already strip export; DF composition demo must not enable nanoq export in a way that breaks offline demos.

### 4.4 Cost accounting

- DurableFlow `ModelRouter` cost remains for **DF-owned** model calls (draft_export, triage, etc.).  
- nanoq’s stage-4 LLM cost: map into `StepResult.cost_usd` **if** nanoq exposes it; else record `0.0` + metadata `nanoq_cost_unknown: true` rather than inventing numbers.  
- Do not double-bill the same tokens in both systems’ ledgers without a single source of truth.

---

## 5. Composition demos

### 5.1 Minimal path (adapter acceptance)

**File:** `examples/nanoq_composition_demo.py`  
**Story:** question → `nanoq_query` → draft note → approval → mock send.  
Proves the thin adapter, RO vs write boundary, and crash/resume without double send.  
Modes: mock default; gated real nanoq; optional crash injection (see Phase 1).

### 5.2 Flagship demo — “Grounded refund reply” (whole system together)

**File:** `examples/nanoq_grounded_inbox_demo.py` (name flexible)  
**One-liner:** *A support email that needs a number is answered only after nanoq grounds the figure; context lineage credits that evidence; DurableFlow gates the outbound reply.*

This is the cool, portfolio-grade run: not “SQL in a vacuum,” but **inbox workflow + domain SQL tool + information lineage + approval + idempotent send**, with optional readiness/agent on top.

#### Scenario

Inbound (fixture email):

> “Our Q2 invoice looks wrong — what did we actually order, and can you confirm before we pay?”

Operator-facing outcome after a full run:

1. Workflow **ingests** the email (existing inbox shape).  
2. **Context** observes email + catalog/snippet artifacts (digests).  
3. **`nanoq_query`** answers a derived analytics question, e.g.  
   *“Show total order amount for customer X in Q2 2025”*  
   (mock backend returns a fixed narrative + digests offline; live nanoq optional).  
4. Context records the nanoq result as **retrieved → selected → consumed → influential** (digest/ref only — not raw SQL/rows by default).  
5. **Draft reply** cites the nanoq narrative (“Your Q2 order total was $…”) without inventing numbers when `outcome != ok`.  
6. **ApprovalGate** pauses before send.  
7. **Mock send** uses side-effect idempotency; crash after send does not double-send.  
8. Optional CLI: `context.cli audit` + workflow status + side_effect_log — one screen of “proof.”

```text
ingest_email
  → select_context
  → nanoq_ground   ← thin adapter (RO; no approval)
  → link_context   ← influential = nanoq evidence digests
  → draft_reply    ← must not fabricate totals if nanoq blocked/failed
  → approval_gate
  → send_reply     ← only consequential write
```

#### Why this demo (not a bare SQL CLI)

| Layer | What the audience sees |
|-------|------------------------|
| **nanoq** | Domain guardrails: read-only analytics, refuse mutation-shaped asks |
| **DurableFlow core** | Checkpoints, crash resume, approval, idempotent send |
| **Context (extension)** | “Why did we say $X?” → lineage to nanoq digests, not vibes |
| **Optional agent/readiness** | Same `nanoq_ask` as RO tool; write tools still gated; one readiness scenario “analytics then write” |
| **Optional evals** | Case: draft must include digest-backed figure; blocked nanoq ⇒ no send path |

#### Teaching punchline (print at end of run)

```text
Numbers came from nanoq (read-only).
Credit for those numbers is in the context ledger.
The email only went out after approval — and only once.
```

#### Variant hooks (optional flags, same example)

| Flag / mode | What it adds |
|-------------|----------------|
| Default | Mock nanoq + full inbox path + context events + approval |
| `--crash-after-nanoq` | Kill after grounded step; resume → no re-send issues; same attempt |
| `--inject-mutation-question` | Email tries to smuggle “delete orders…” into the derived SQL question → nanoq **blocked** → draft apologizes / escalates → **no send** or send without false totals |
| `--agent` | mini_react / AgentRunner with `nanoq_ask` + `send_email` tools; only send is approval-gated |
| `--readiness-slice` | Single readiness scenario wrapping the agent variant (not a full 6-pack replacement) |
| `DURABLEFLOW_NANOQ=1` | Real nanoq backend against sample DB (still optional for CI) |

#### What we deliberately skip in the flagship

- Colony / Vast (wrong failure domain).  
- Factory CLEAR full loop (noise).  
- Stage-level DF checkpoints inside nanoq.  
- Replacing nanoq’s release NFRs with readiness scores.

#### Phase mapping

| Demo | Phase |
|------|--------|
| Minimal composition (§5.1) | Phase 1 (required) |
| Flagship grounded inbox + context (§5.2) | **Phase 1.5** (same PR train as Phase 1 if cheap; else immediate follow-on) |
| `--agent` / readiness-slice | Phase 3 |
| Live nanoq backend | Phase 2 |

**Acceptance for “whole system” narrative:** one command produces (1) a grounded draft tied to nanoq digests, (2) a context audit that lists those digests as influential, (3) an approval pause, (4) a single mock send — all offline with mocks.

---

## 6. Phased delivery

### Phase 0 — Contract freeze

- Freeze DTOs, outcome enum, privacy defaults, package layout.  
- Confirm nanoq public API for in-process call **or** commit to JSON CLI for subprocess.  
- Decision: monorepo path (`durableflow/nanoq` symlink), documented sibling clone, or neither until Phase 2.

**Exit:** this proposal reviewed; no runtime change required.

### Phase 1 — Mock adapter + composition demos (no nanoq install)

- `integrations/nanoq_types.py`, `MockNanoqBackend`, step wiring.  
- `examples/nanoq_composition_demo.py` — minimal path (§5.1).  
- `examples/nanoq_grounded_inbox_demo.py` — flagship grounded refund reply + context lineage (§5.2).  
- `tests/test_nanoq_adapter.py` + composition/flagship offline tests.  
- Docs: walkthrough “whole system” subsection; composition, not merge.

**Exit:** `./start.sh test` green without nanoq; both demos run offline; flagship shows context audit + single gated send.

### Phase 2 — Real backend behind gate

- `InProcessNanoqBackend` and/or `SubprocessNanoqBackend`.  
- Skip/xfail live tests unless `DURABLEFLOW_NANOQ=1`.  
- Map real nanoq outcomes to `NanoqOutcome`.  
- Document Python version split (3.12 nanoq vs DF matrix).

**Exit:** one CI job **optional** or documented manual path; still not required for default CI.

### Phase 3 — Agent tool + readiness scenario (optional)

- Register `nanoq_ask` as RO tool.  
- Optional readiness scenario: injection/blocked path does not trigger write tools.  
- Do **not** replace nanoq’s own eval harness with readiness scores.

### Phase 4 — Hardening (only if claimed)

- Optional idempotency cache for identical `(question_digest, catalog_hash, llm_mode)` to avoid re-billing LLM on step retry (product claim).  
- Optional two-phase: dry-run step → approve SQL → execute step (only if teaching “approve the SQL”; needs clear product narrative).  
- Nested stage events into DF lifecycle log (depends on lifecycle-evidence proposal).

---

## 7. Blast radius

### 7.1 Summary

| Surface | Phase | Risk | Notes |
|---------|-------|------|-------|
| `src/` core engine/store | — | **None** if Phase 1–2 stay in `integrations/` + examples | Do not import nanoq from `src/` |
| `integrations/` | 1–2 | **Low** | New files; same pattern as LangSmith |
| `examples/` | 1 | **Low** | New demo only |
| `agent/` | 3 | **Low–Medium** | Tool registration + RO classification |
| `readiness/` | 3 | **Low** | Optional scenario; scoring unchanged by default |
| `tests/` default CI | 1 | **Low** | Mock-only; no new required deps |
| `pyproject.toml` | 2 | **Low** | Optional extra only |
| nanoq repo | 2 | **Medium** | May need stable library entrypoint or `--json` CLI |
| Docs / walkthrough | 1 | **Low** | Composition section; avoid “merged product” language |
| Dependency graph | 2 | **Medium** | Version skew 3.11–3.13 vs nanoq 3.12 — prefer subprocess if painful |
| Privacy tests | 1–2 | **Medium** | Ensure digests in persisted step_data by default |

### 7.2 Highest-risk mistakes (avoid)

1. **Import nanoq in `src/engine.py` or store** — breaks offline/stdlib contract.  
2. **ApprovalGate on the SQL tool by default** — confuses RO safety with HITL; teach approval on writes.  
3. **Parsing CLI prose as API** — brittle; require DTO or JSON.  
4. **Persisting full SQL + row dumps in SQLite** — violates DF privacy culture.  
5. **Claiming nanoq eval NFRs from DF readiness** — different methodologies.  
6. **Stage-level DF checkpoints in v1** — scope explosion; dilutes both theses.  
7. **Making default CI install nanoq lockfile** — couples release trains.

### 7.3 Rollback

Delete/disable example and optional extra; core and existing extensions unchanged. Mock tests can remain as documentation of the DTO.

### 7.4 Interaction with other proposals

| Proposal | Interaction |
|----------|-------------|
| Core Lifecycle Evidence | Composition demo benefits from co-committed step events; not a blocker for Phase 1 |
| Front-Pressure | Approve export can later carry intervention envelopes; still DF-side |
| Trajectory evals | Tool call `nanoq_ask` becomes a trajectory node; scorers stay RO-aware |
| Eval gate | Can later score “blocked mutation attempts never reached send”; domain SQL accuracy stays in nanoq |
| LangSmith adapter | Prefer one outer DF span; don’t force dual raw export |

---

## 8. Testing plan

| Test | Asserts | Requires nanoq? |
|------|---------|-----------------|
| `test_mock_backend_ok_shape` | DTO + `as_step_output` keys | No |
| `test_blocked_outcome_completes_step` | Engine continues or skips draft per policy | No |
| `test_composition_approval_then_send` | Side effect only after approve | No |
| `test_composition_reject_no_send` | No side_effect_log row | No |
| `test_crash_resume_requeries_not_double_send` | Resume re-runs nanoq step; send once | No (mock) |
| `test_no_raw_sql_in_step_data_by_default` | Digests only | No |
| `test_inprocess_backend_maps_outcomes` | Live mapping | Yes + gate |
| `test_core_imports_without_nanoq` | `import src.engine` clean | No |

Grep gate (CI): `src/` must not contain `import nanoq` or `from nanoq`.

---

## 9. Documentation plan

1. **This proposal** — design authority.  
2. **`docs/walkthrough.md`** — short “Composition: domain tools under a durable shell” subsection.  
3. **Root `README.md`** — optional one-liner under extensions/integrations (after Phase 1 exists).  
4. **nanoq README** (sibling) — “Used as a RO tool under DurableFlow; see durableflow proposal …” (coordinate separately; not required for DF Phase 1).  
5. **Learning path** — optional track after Stage 5: run composition demo; predict why SQL step has no approval but send does.

---

## 10. Open questions (decide in Phase 0)

| ID | Question | Options | Recommendation |
|----|----------|---------|----------------|
| Q1 | How is real nanoq invoked? | In-process API vs subprocess JSON CLI | Prefer **in-process** if nanoq exposes a stable `run_pipeline`; else **subprocess** for 3.12 isolation |
| Q2 | Does nanoq need a `--json` CLI flag? | Yes / no | **Yes** if subprocess path chosen; small nanoq PR |
| Q3 | Where does sample DB live? | Path into sibling nanoq `data/sample.db` vs copy under `examples/` | Sibling path in docs; copy only if packaging requires |
| Q4 | Fail workflow on `blocked`? | Terminal fail vs continue with skip | **Continue + skip write path** (domain refuse is success of safety) |
| Q5 | Agent tool in same MVP? | Phase 1 vs 3 | **Phase 3** — step composition is the clearer teaching artifact |
| Q6 | Two-phase approve-SQL? | In v1? | **No** — separate later claim |

---

## 11. Acceptance criteria (Phase 1 done)

1. Offline **minimal** composition demo runs with mock backend, no nanoq install.  
2. Offline **flagship** grounded-inbox demo: nanoq digests → context influential → approval → one mock send.  
3. Flow shows RO query step → draft → approval → mock send.  
4. Reject / nanoq-blocked path: no fabricated totals; zero side-effect rows (or escalate-only draft per policy).  
5. Crash/resume test: nanoq step may re-execute; send not duplicated.  
6. Default CI green; no nanoq import under `src/`.  
7. Privacy test: default persistence uses digests, not raw SQL/question.  
8. Walkthrough paragraph states the ownership split + points at the flagship demo.  

Phase 2 adds: gated real backend + documented install; still non-blocking for default CI.  
Phase 3 adds: `--agent` / readiness-slice variants.

---

## 12. Trade-offs

| Choice | Why | Change if |
|--------|-----|-----------|
| Thin adapter, not stage-level DF | Preserves both theses; small blast radius | Product requires resume mid-SQL-pipeline |
| Mock-default in DF | Offline CI / stdlib culture | nanoq becomes a first-class monorepo package with unified pins |
| No approval on SELECT | RO is architectural in nanoq | Compliance requires human sign-off on *queries* (two-phase) |
| Subprocess allowed | Python version skew | Unified 3.12-only DF CI |
| Digests by default | Match DF privacy + nanoq audit posture | Local teaching mode with raw SQL always on |

---

## 13. Decision requested

Approve **Phase 0–1**: freeze the DTO/ownership split and ship an **offline composition demo** with `MockNanoqBackend` so the relationship is runnable, not only rhetorical.

Defer Phase 2–3 until Phase 1 is the default teaching artifact and nanoq’s library/CLI machine interface is confirmed (Q1–Q2).

---

## 14. Title

**Canonical:** `proposals/nanoq-tool-integration-proposal.md`  

**Public name:** *nanoq as a DurableFlow Tool (Thin Adapter)*  

**Alternate:** *Domain Tool Composition — Read-Only SQL under a Durable Shell* (if avoiding the nanoq product name in a portfolio index).

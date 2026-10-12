# Proposal: Interrogate the Control Plane (DurableFlow via nanoq)

**Status:** PROPOSAL  
**Scope:** Catalog, fixtures, demo script, and docs — **not** a DurableFlow core runtime change; **not** the “nanoq as workflow tool” integration  
**Owner:** Marcos Polanco  
**Created:** 2026-08-11  
**Repositories:** `durableflow` (schema + demo DBs), `nanoq` (read-only text-to-SQL client; sibling install)  
**Depends on:** Stable-enough SQLite schema in `WorkflowStore` (and optional extension tables); nanoq CLI/pipeline with catalog + RO enforcement  
**Dependency policy:**  
- DurableFlow core remains stdlib-only; this proposal adds **data and docs**, not required Python deps to `src/`.  
- nanoq remains optional: demos that invoke nanoq are gated or use pre-authored SQL fallback for offline CI.  
- Default `./start.sh test` must not require nanoq.  
**Visibility:** Private implementation guide. Public artifacts: operational catalog, golden questions, post-run interrogation demo, walkthrough section.

**Sibling proposal (do not merge):** [`nanoq-tool-integration-proposal.md`](nanoq-tool-integration-proposal.md) — nanoq *inside* a DurableFlow workflow.  
**This proposal:** DurableFlow SQLite *under* nanoq — natural-language **inspection** of what already ran.

---

## 0. Positioning

DurableFlow persists operational truth in local SQLite: workflow status, step results, approval gates, side-effect log, and (when enabled) context lineage and extension tables. Today, inspection is:

- hand-written `sqlite3` queries,  
- demo stdout,  
- ad-hoc operator CLI ideas (lifecycle-evidence proposal),  
- JSONL telemetry files.

**nanoq** already solves “ask a question → safe read-only SQL → grounded narrative” against a catalogued SQLite database. Pointing it at a DurableFlow DB turns the control plane into something you can **interrogate** after (or during) a run:

> “Which workflows are paused on approval?”  
> “What was the last completed step before the crash?”  
> “Which context digests were marked influential?”

**Load-bearing claim (falsifiable):**

> After shipping a DurableFlow **operational catalog** and a small set of golden questions, an engineer can run a standard DurableFlow demo, then ask natural-language questions about that demo’s SQLite file via nanoq (or equivalent RO SQL from goldens), and receive answers that match held-out SQL expectations for those questions — without any write path to the control-plane DB and without DurableFlow importing nanoq into core.

**What this is not:**

- Embedding nanoq as a workflow step or agent tool (see sibling proposal)  
- A production multi-tenant analytics product  
- Replacing readiness scores, colony benchmarks, or nanoq’s own NFR release gates  
- Granting write/DDL access to workflow state  
- Claiming NL accuracy on arbitrary ad-hoc questions without a measured set  

---

## 1. Problem / opportunity

| Today | Gap |
|-------|-----|
| Crash demo leaves a rich SQLite file | Learner must already know table names and the two-status-layer model |
| Context audit is a specialized CLI | “What was influential?” is natural language in operators’ heads |
| Specs describe schema | Schema is not packaged as a **retrieval catalog** with descriptions |
| Lifecycle-evidence operator CLI (proposed) | Fixed subcommands; NL is a parallel, lower-friction inspection mode |

**Opportunity:** one teaching loop —

```text
act (DurableFlow demo) → persist (SQLite) → ask (nanoq RO) → understand
```

Symmetric to the sibling proposal’s loop (nanoq *produces* evidence *during* a workflow). Here nanoq *consumes* evidence *after* the workflow.

---

## 2. Design overview

```text
┌─────────────────────────────────────┐
│  DurableFlow demos / tests          │
│  write examples/*.sqlite            │
└─────────────────┬───────────────────┘
                  │ read-only
                  ▼
┌─────────────────────────────────────┐
│  catalogs/durableflow_core.json     │  table/column descriptions
│  (+ optional context, colony slices)│
└─────────────────┬───────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│  nanoq CLI / pipeline               │
│  AST + query_only + authorizer     │
│  → answer + narrative (+ verbose)   │
└─────────────────────────────────────┘
```

**v0 needs almost no DurableFlow code** — catalog + paths + docs + optional wrapper script.

---

## 3. Operational catalog

### 3.1 Placement

```text
catalogs/
  durableflow_core.json       # workflows, step_results, approval_queue, side_effect_log
  durableflow_context.json    # optional slice: context_* tables (when present)
  durableflow_colony.json     # optional slice: colony_* (when present)
data/nanoq_goldens/
  control_plane_questions.json  # held-out NL ↔ expected SQL or execution-match fixtures
examples/
  interrogate_control_plane.sh  # or .py: run demo → ask N questions
docs/
  control-plane-catalog.md      # short human guide: two status layers, join patterns
```

Catalog format follows nanoq’s existing `catalog.json` conventions (table names, columns, descriptions, sample values as needed for linking — no secrets).

### 3.2 Core tables (v0)

| Table | Why operators ask about it |
|-------|----------------------------|
| `workflows` | status, current_step, type, timestamps |
| `step_results` | what completed, cost, model_used, order |
| `approval_queue` | pending / approved / rejected gates |
| `side_effect_log` | idempotency keys, whether send happened |

**Catalog copy must teach the two-layer model** (retrieve-time descriptions, not only docs):

- `workflows.status` = **execution** state (`pending`, `running`, `paused_approval`, `approved`, `rejected`, `completed`, `failed`, `crashed`, …).  
- `approval_queue.status` = **operator decision** on a gate (`pending`, `approved`, `rejected`).  
- A workflow can be `paused_approval` while a gate row is `pending`; they are not interchangeable.

### 3.3 Optional slices

| Slice | When to load |
|-------|----------------|
| Context | After `inbox_triage_context_demo` / context-enabled DBs |
| Colony | After chaos benchmark DBs with `colony_*` tables |
| Lifecycle events | Only if/when `workflow_events` ships (lifecycle-evidence proposal) |

v0 ships **core only**. Context slice is the first extension add-on (pairs with post-context-demo interrogation).

### 3.4 Example golden questions (illustrative)

| ID | Natural language | Intent |
|----|------------------|--------|
| CP-Q01 | Which workflows are currently paused waiting for approval? | Filter `workflows.status` |
| CP-Q02 | For workflow `wf-001`, list completed steps in order with cost. | Join/order `step_results` |
| CP-Q03 | How many side-effect log entries exist for workflow `wf-001`? | Count `side_effect_log` |
| CP-Q04 | List pending approval gates with their workflow_id and step_name. | `approval_queue` |
| CP-Q05 | What is the maximum step_index completed for the crashed/resumed demo workflow? | Crash narrative |
| CP-Q06 | *(context slice)* Which artifact digests were marked influential for workflow X? | `context_*` events |

Goldens are **held out** from any fast-path pairs used only for demos. Measurement methodology can piggyback nanoq’s execution-match harness later; v0 may assert fixture SQL only.

---

## 4. Demo: post-run interrogation

### 4.1 Flagship script

**Name:** `examples/interrogate_control_plane.sh` (or `python examples/interrogate_control_plane.py`)

**Default path (offline-friendly):**

1. Ensure a known DB exists (run crash demo non-interactively, or copy a **committed fixture DB** under `data/fixtures/control_plane_crash.sqlite` for CI).  
2. Print: “Control plane DB: …”  
3. For each of 3–5 golden questions:  
   - If nanoq available → `nanoq "…" --db … --catalog catalogs/durableflow_core.json --llm mock` (or http when gated).  
   - Else → run **pre-authored SQL** from the golden file and print a short narrative template (proves catalog value even without NL).  
4. Print teaching closer:

```text
DurableFlow wrote the control plane.
nanoq (or RO SQL) only read it.
No workflow state was modified.
```

### 4.2 Cool one-liners for walkthroughs

After `./start.sh crash`:

```bash
nanoq "What was the last completed step before resume?" \
  --db examples/crash_resume_demo.sqlite \
  --catalog catalogs/durableflow_core.json
```

After inbox + reject:

```bash
nanoq "Are there any side effects logged after a rejection?" \
  --db examples/inbox_triage_demo.sqlite \
  --catalog catalogs/durableflow_core.json
```

After context demo:

```bash
nanoq "Which digests were influential in the context demo workflow?" \
  --db examples/inbox_triage_context_demo.sqlite \
  --catalog catalogs/durableflow_context.json
```

### 4.3 Pairing day (narrative only; two proposals)

| Segment | Proposal | Demo |
|---------|----------|------|
| Act | nanoq-tool-integration | Grounded refund / composition (nanoq *inside* workflow) |
| Inspect | **this** | Interrogate the SQLite that run (or crash/inbox) left behind |

Not required to implement both to ship either.

---

## 5. Safety and privacy

| Rule | Detail |
|------|--------|
| **Read-only** | Only nanoq’s RO stack (or `sqlite3` query_only) touches the DF DB. Never open the demo DB with a write connection from this path. |
| **No second writer** | Interrogation must not call `WorkflowEngine`, approve gates, or append side effects. |
| **Digests** | Catalog and goldens assume DF privacy posture: digests/refs in context tables; goldens must not expect raw email bodies. |
| **Injection** | Catalog descriptions are untrusted data for the generator (nanoq spotlighting); do not put secrets in catalog text. |
| **Multi-tenant** | Out of scope; single local file. |

---

## 6. Relationship to other work

| Work | Relationship |
|------|----------------|
| **nanoq-tool-integration** | Orthogonal direction; link in both docs; separate packages/demos |
| **lifecycle-evidence** | `workflow_events` becomes a high-value catalog table later; operator CLI and NL interrogation are complementary |
| **context extension** | Optional catalog slice; NL audit alongside `context.cli audit` |
| **evals / trajectory** | Future: goldens as execution-match cases on DF schema; not v0 gate |
| **readiness** | Prefer querying SQLite traces if present; do not NL-query `readiness.json` via nanoq |

---

## 7. Phased delivery

### Phase 0 — Schema inventory

- Document current core DDL as the catalog source of truth (from `store.py`).  
- Freeze v0 question list (CP-Q01–Q05).  
- Decide fixture strategy: generate in demo vs commit binary SQLite fixture.

### Phase 1 — Catalog + SQL goldens + script (no nanoq required)

- `catalogs/durableflow_core.json`  
- `data/nanoq_goldens/control_plane_questions.json` with expected SQL  
- `examples/interrogate_control_plane.py` with SQL fallback  
- `docs/control-plane-catalog.md` (two status layers, example joins)  
- Offline tests: expected SQL runs on fixture DB and returns stable row counts/shapes  

**Exit:** CI proves catalog questions without nanoq installed.

### Phase 2 — nanoq path (optional)

- Wrapper invokes nanoq when present (`DURABLEFLOW_NANOQ=1` or `command -v nanoq`).  
- Mock LLM fixtures for CP questions where possible.  
- Document CPython 3.12 pin for live nanoq.  
- Manual or optional CI job only.

### Phase 3 — Context (and later colony) slices

- `durableflow_context.json` + 2–3 goldens after context demo DB.  
- Optional colony slice post-benchmark.

### Phase 4 — Measurement (optional)

- Feed goldens into nanoq eval harness against DF fixture schema.  
- Report execution-match for CP set only; do not overload nanoq product NFRs.

---

## 8. Blast radius

| Surface | Phase | Risk | Notes |
|---------|-------|------|-------|
| `src/` | — | **None** | No runtime coupling |
| `catalogs/`, `data/`, `examples/`, `docs/` | 1 | **Low** | Additive |
| Schema drift | 1–3 | **Medium** | Catalog must track `store.py` / extension DDL; add checklist to CONTRIBUTING or dflow-spec |
| Committed SQLite fixtures | 1 | **Low–Medium** | Binary in git vs generate-on-the-fly; prefer generate from deterministic demo for cleanliness |
| nanoq version skew | 2 | **Medium** | Optional path only |
| Misleading NL answers | 2 | **Medium** | Mitigate with goldens + catalog teaching copy; don’t claim open-ended accuracy |
| Privacy regressions | 1 | **Low** if goldens use digests only | Fail tests that assert on raw PII-like fields |

**Rollback:** remove catalogs/examples; zero impact on engine.

---

## 9. Testing plan

| Test | Asserts | nanoq? |
|------|---------|--------|
| Fixture DB has expected tables | schema smoke | No |
| CP-Q01…Q05 expected SQL | row shape / counts stable | No |
| Two-layer semantic doc test | optional: SQL that would confuse status layers fails golden | No |
| Script exit 0 offline | SQL fallback path | No |
| Live nanoq mock path | maps to same execution-match | Gated |

---

## 10. Open questions

| ID | Question | Recommendation |
|----|----------|----------------|
| Q1 | Commit binary fixture DB or regenerate every run? | **Regenerate** from crash/inbox demo in script; tiny committed fixture only if demo is flaky |
| Q2 | One combined catalog vs slices? | **Core + optional slices** so context-less DBs don’t confuse retrieval |
| Q3 | Should DF ship a `nanoq` optional extra? | **No** for this proposal — document sibling install |
| Q4 | Expose views (SQL VIEW) for “pending approvals” join? | Defer; catalog descriptions first; views if goldens stay painful |
| Q5 | Overlap with operator CLI in lifecycle-evidence? | Complementary: CLI for exact ops; nanoq for exploratory ask |

---

## 11. Acceptance criteria (Phase 1)

1. Core operational catalog exists and matches current `WorkflowStore` DDL.  
2. ≥5 golden questions with expected SQL pass on a deterministic fixture/demo DB.  
3. Interrogation example runs offline without nanoq.  
4. Docs explain two status layers and point to post-crash / post-inbox recipes.  
5. Default CI green with no nanoq dependency.  
6. README/walkthrough one-liner: *act with DurableFlow, inspect with RO SQL/nanoq*.

Phase 2: optional nanoq invocation documented and manually verified.

---

## 12. Trade-offs

| Choice | Why | Change if |
|--------|-----|-----------|
| Separate from tool-integration proposal | Opposite data flow; different blast radius | Monorepo “nanoq chapter” doc index only |
| SQL goldens first, NL second | Offline CI; nanoq PARTIAL live gates | nanoq always available in DF CI |
| Core catalog only in v0 | Smaller drift surface | Context demo is the default teaching path |
| No DF code generation of catalog | Human-maintained clarity | Schema migrations become frequent |

---

## 13. Decision requested

Approve **Phase 0–1**: ship the **operational catalog**, goldens, and offline interrogation example so “query the control plane” is a real lab motion.

Treat nanoq invocation as **Phase 2 garnish**, not a blocker — the catalog and RO questions are the DurableFlow-owned asset.

---

## 14. Title

**Canonical file:** `proposals/nanoq-control-plane-query-proposal.md`  

**Public name:** *Interrogate the Control Plane (DurableFlow via nanoq)*  

**Alternate:** *Operational Catalog for Read-Only Control-Plane Analytics*

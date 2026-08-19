# DurableFlow as evidence for the Trase OS Staff role

DurableFlow is a working argument that the hard parts of an agentic operating
system are **execution semantics under failure**, not agent intelligence. It is
a stdlib-only core (SQLite, plain Python, deterministic mock providers — no
network in default paths) that implements the execution model the Trase role
describes, plus a body of written architectural judgment about where that
model's guarantees end.

| Role requirement | Where this repo demonstrates it |
|---|---|
| Core execution model: state machine, lifecycle, failure semantics | `src/engine.py` — a linear macro-step runner with explicit statuses (`RUNNING`, `PAUSED_APPROVAL`, `WAITING_EXTERNAL_ACTION`, `STALE_DEFINITION`, terminal set). Checkpoint after every completed step (`src/store.py`); `resume()` restarts from `current_step + 1`; crash detection and recovery (`recover_crashed`) with the crash demo as the canonical smoke test. |
| Correctness via idempotency, deterministic replay | `side_effect_log` replay suppression; idempotency keys derived from content digests (`src/workflows.py`, `factory/workspace.py`); deterministic seeded mock providers so every demo and benchmark is reproducible offline. Chaos benchmark (`colony/`) runs a naive retry runner vs. the durable runner under an identical seeded loss schedule and quotes the measured delta. |
| Durable HITL / approval gates | `src/approval.py` — a gate whose pending decision survives process death, with definition-digest refusal: a consequential step paused in *either* wait state refuses to resume under a changed registered implementation (`STALE_DEFINITION`), tested for both states. |
| Saga/compensation-adjacent effect semantics | The WS2 Aegis client (`integrations/aegis_client.py`): request-intent records written before the first submission attempt, action-ID recovery after a lost create response, rebind-refusal under a reused key with changed arguments, receipt binding/integrity verification, one-place terminal-state mapping (`CONFIRMED/DENIED/FAILED/CANCELLED/UNRESOLVED`), and ambiguity that never blind-retries — it waits (`tests/test_aegis_conformance.py`). |
| Audit & lineage | `context/` — a durable information-lineage ledger (observed → retrieved/rejected → selected → consumed → influential) storing digests and source refs, never raw bodies. JSONL telemetry for steps, approvals, crashes, fallback, completion. A hard privacy boundary enforced by `evals/redaction.py` and negative tests. |
| Observability & evaluation hooks | `TelemetryLogger`; optional LangSmith export reached only through a `ContextExporter` protocol the core never imports and whose failures are swallowed. `evals/` — traces → cases → scorers → ship gate with exit-coded pass/fail. `readiness/` scores six failure-mode scenarios naked vs. wrapped, verdict-first. |
| Backpressure / scale primitives | `frontpressure-proposal.md` and the OpenTelemetry adapter proposal — designed, not yet shipped, and explicitly flagged as such. |
| LLM capability folded into system design | Model fallback with per-step USD cost accounting (`src/model_router.py`); TF-IDF context packing against a hard token budget by design (no embeddings dependency); spec-driven CLEAR workflow (`factory/`) with an independent verification ledger. |

## The part that is judgment, not code

The repo's most relevant artifact for this role is
`proposals/drae-dflow-workplan.md`. It is a self-audit against a framework
whose organizing claim is: *agents do not break the mechanisms; they break the
preconditions.* Concretely:

- **Named residuals instead of layer diagrams.** The architecture doc opens
  with a mechanism / assumed-precondition / proved / residual-delta table, not
  a stack picture that looks complete while the hard part goes unnamed.
- **Refusing to build the wrong thing.** A locked decision (`D-NOGROW`)
  forbids the engine from growing canonical action hashing, precondition
  CAS, or an `unknown` state machine — because duplicating the adjacent
  Aegis action authority inside a workflow engine would create a second,
  weaker one. The engine stays deliberately dumb; sophistication lives
  behind a boundary it calls.
- **Claims held to evidence.** A repository-wide claim inventory
  (`docs/delta-conformance.md`) disposes every `prevent`/`guarantee`/`secure`-
  shaped sentence as accurate, fixed, or allowlisted. Falsification conditions
  are written next to verdicts. Target-architecture language is explicitly
  marked as not-yet-current behavior until an exit criterion is met.
- **Exit criteria that gate claims.** "Completes only from a verified
  terminal result" is defined operationally and testably, then covered by a
  conformance suite whose negative tests (foreign receipt, synthesized
  receipt, bypassed submission) prove the invariant can fail loudly rather
  than pass vacuously.

That is the working style the Trase role calls for: primitives that stay
small because their boundaries are written down, correctness demonstrated by
injecting failure rather than asserting success, and documentation that
under-claims by default — the properties a regulated-environment platform
needs to remain auditable as it scales.

## Direct mapping to the "why"

The role's stated risks — tight coupling, execution that is hard to reason
about under failure, capabilities fragmenting instead of compounding — are
each addressed by a concrete choice here: extension packages own their own
tables and sit *beside* the core rather than in it; every failure mode this
repo handles has a persisted status and a resume rule, so post-mortem
reasoning is a database query; and the reusable primitives (checkpoint,
pause, replay suppression, terminal mapping, lineage ledger) are exactly the
paved roads other workflows in the repo are built from.

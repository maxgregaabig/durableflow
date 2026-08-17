# Critique & Plan: DurableFlow against the Delta Framework

**Status:** PLAN. Sections 0–3 are the diagnosis (unchanged in substance from the original critique). Section 4 onward is an executable workplan, not prose recommendations.
**Created:** 2026-08-16
**Applies to:** DurableFlow core, documentation, extensions, and proposal portfolio
**Primary lens:** "The Delta Framework" (internal working doc, not tracked in this repository)
**Related:** [`delta-abep-aegis-alignment-proposal.md`](delta-abep-aegis-alignment-proposal.md) (cross-repo direction; Phase 0 there is this plan's WS0), [`../../aegis/docs/grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md) (Aegis's executable schedule; this plan's WS2 is blocked on its WS2 exit), [`../wip/drae-framework-matrix-evaluation.md`](../wip/drae-framework-matrix-evaluation.md)
**Decision type:** Scope and claim alignment, sequenced as a workplan. Aegis owns the runtime; this repo does not build a second one.

---

## 0. Verdict

Conforming with the Delta Framework is a **scope and claim change**, not a request to implement D1–D6 inside DurableFlow. The lens asks which mature mechanism you are using, which precondition agents break, and whether this repo should own the residual. Most of DurableFlow is the mature mechanism. Treating it as a new agent-platform boundary is the non-conformance.

The organizing principle from the Delta Framework:

> Agents do not break the mechanisms. They break the preconditions.

A layer diagram that can be filled with checkpoints, HITL, context, eval, and traces still looks complete while leaving the residual unnamed. DurableFlow is currently organized that way in `docs/dflow-arch.md`.

[`delta-abep-aegis-alignment-proposal.md`](delta-abep-aegis-alignment-proposal.md) is the cross-repository direction: Phase 0 there is claim alignment; code comes only after ABEP↔Aegis refinement and a consumable gateway. [`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md) is now the executable schedule for the Aegis side of that. This document is the executable schedule for the DurableFlow side. Building more durable HITL or a fatter `side_effect_log` before either gate clears would be the anti-conforming move.

---

## 1. What the project is today, under this lens

The core is a linear macro-step runner: SQLite checkpoints, `resume()` from `current_step + 1`, an `ApprovalGate` that persists a payload and later checks `approved`/`rejected`, a local `side_effect_log` that replays a known mock result, TF-IDF context packing, and model fallback with cost. That is Temporal/LangGraph-shaped teaching machinery. It is useful. It is not a delta.

`docs/dflow-arch.md` opens with the exact layer diagram the framework says to stop using as the first view: Agent → DurableFlow → Recovery / HITL / Context / Eval / Observability → Production.

---

## 2. Score against D1–D6

| Delta | What DurableFlow does | Verdict |
|---|---|---|
| **D1** Optimistic-concurrency authorization | `ApprovalGate` stores draft JSON and later reads `approved`. `send_reply` then builds an idempotency key and writes the mock effect. No hash-stable action, no declared world preconditions, no executor-time compare-and-swap, no single-use authorization. | **Substitutes.** Durable HITL, not authorization. |
| **D2** Mute-API reconciliation | `side_effect_log` records a result after it is already known. No `unknown`, no dispatch attempt, no remote reference, no receipt, no reconciliation deadline. The remote-exactly-once disclaimer is correct and must stay. | **Substitutes.** Local replay suppression, not effect resolution. |
| **D3** Cross-org vocab + revoke | Absent. | **Silent.** Correct. Do not start this. |
| **D4** In-flight behavior change | `resume()` continues against whatever functions are registered in *this* process. No pin of workflow definition, prompt, model route, policy, or canonicalization version. A paused inbox run can finish under new draft/send semantics. | **Silent / implicit migrate.** The mature answer is pin-and-refuse, not a research product. |
| **D5** Provenance under injection | Readiness treats prompt injection as "approval intercepted the write" (`readiness/docs/dflow-readiness-spec.md`). The framework's harder case is a deceived user/approver binding exactly the attacker's act. | **Mediation.** Overstates. Unfalsified; containment is the current answer. |
| **D6** Containment over approval | Inbox, readiness, MCP, and factory default to per-write human gates. `docs/field-pattern.md` says "gate every external write until policy can replace the human." `frontpressure-proposal.md` would industrialize intervention volume. | **Anti.** Cheaper, more auditable approvals raise volume. |

That is the same failure pattern the matrix assigns to LangGraph interrupts, OpenAI `needsApproval`, ADK HITL, and HumanLayer: action identity + durable pause, world state free to drift, no `unknown`, mediation sold as injection defense.

### 2a. Falsification conditions for these verdicts

The framework requires a strongest counterargument and a falsification condition per claim, not just per delta. The verdicts above are DurableFlow-specific claims, not restatements of §2, so they need their own:

| Delta | Verdict | Strongest counterargument | Falsified if |
|---|---|---|---|
| D1 | Substitutes: durable HITL, not authorization | `approval_queue.payload` is JSON-serialized with `sort_keys=True` before storage, which is close to a canonical representation. If `send_reply` re-read and re-hashed live preconditions against that stored payload before dispatch, the gap would be a missing check, not a missing capability | Someone shows `send_reply` (or any commit handler) re-validates a precondition fingerprint immediately before the irreversible call, rather than trusting the payload approved at gate time |
| D2 | Substitutes: local replay suppression, not effect resolution | Idempotency keys are real and would matter the moment `send_reply` calls a live API instead of returning a mock result; the plumbing for the key exists even though the remote call does not | The mock provider is replaced by a real dispatch path that (a) records a remote reference distinct from the local idempotency key, and (b) can enter a state other than success/already-executed — i.e., an `unknown` or `escalated` status appears in `side_effect_log` or its successor |
| D3 | Silent; correct to leave silent | None identified; DurableFlow has no cross-organizational delegation surface at all | Any proposal in this repo introduces delegation across an organizational boundary (not just across roles within one deployment) |
| D4 | Silent / implicit migrate | `resume()` binds to whatever functions are registered in the *current* process, which for a single-operator local demo may never diverge from the checkpoint's original definition in practice | A workflow is shown pausing on `PAUSED_APPROVAL`, the process is redeployed with changed step logic for the same `step_name`, and `resume()` completes the paused run under the new logic without any version check — this is demonstrable with the existing test harness and would confirm rather than merely assert the hole |
| D5 | Mediation; overstates | `ApprovalGate` does add a human read of the payload before dispatch, which is a real (if weak) control against a subset of injected content — namely injected content the approver actually notices | A trial shows the human approver, not the model, is where injected instructions get bound to an approved act at a rate meaningfully above the framework's reported 24/25 deception rate — i.e., that human review of the payload catches what model-level mediation could not |
| D6 | Anti: cheaper approvals raise volume | Frontpressure has not shipped; the claim is about a proposal's direction, not measured behavior | Frontpressure or an equivalent ships and operator override/attention-decay rates (measured, not assumed) stay flat as approval volume rises, rather than following the clinical/DORA pattern cited in D6 |

None of these are resolved by this document. They are the difference between "DurableFlow's shape resembles the anti-pattern" (asserted above) and "DurableFlow's shape *is* the anti-pattern" (would require the falsifying evidence to be absent after someone looks). The verdicts stand until falsified, same status as the framework entries they're drawn from — not stronger.

---

## 3. The five things a platform would have to own

Section 5 of the framework is the actual product test. DurableFlow currently owns none of them as guarantees:

1. **Canonical action identity** — payload JSON in `approval_queue`, not a hash-stable act + preconditions.
2. **Compare-and-swap at the irreversible step** — approve, then send. The send does not re-read declared world state.
3. **Effect resolution including `unknown`** — `side_effect_log` has no executing/ambiguous/escalated states.
4. **Correlation join** — `workflow_id` is propagated. There is no join from workflow → approval → authorization → dispatch → vendor reference → receipt. JSONL telemetry is observational, not an integrity graph.
5. **Conformance suite for those transitions** — crash/resume of *steps* is the canonical demo. There is no fault-injection suite for approval drift, lost dispatch responses, duplicate delivery, mismatched receipts, or precondition change.

Growing `approval_queue` or `side_effect_log` to fake those five inside this repo would create a second, weaker Aegis — and ABEP/Aegis already sit next door as the protocol and gateway. Aegis's own schedule for owning all five is [`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md) §2 and §5.

**Note on item 4, carried over from the framework's own caveat (§5).** The framework states the correlation layer "survived the adversarial passes by not being addressed rather than by being validated" and should be red-teamed before being treated as established. That caveat applies here with the same force: item 4's absence in DurableFlow is real and checkable (`workflow_id` is the only cross-table key in `store.py`), but the *claim that a join key across five namespaces is sufficient to make the invariant statable* has not itself been tested against DurableFlow's schema or Aegis's. Items 1, 2, 3, and 5 are checkable against present code today; item 4 is a design assertion imported at the same confidence level as the checkable items, and it should not be. Before WS2 assumes a join-key design is enough, that assumption needs the same adversarial pass §5 of the framework asks for and has not yet received, in either repo.

---

## 4. Locked decisions

These are not open questions for an implementer. If a later fact falsifies one, amend this document; do not silently invert it in code.

| # | Decision | Consequence |
|---|---|---|
| D-CLAIM | **Public language distinguishes target architecture from current behavior until WS2 exits.** The thesis in `proposals/README.md` already shipped ahead of WS2 — that is now a known inconsistency, not a plan. | Every place the new thesis appears must carry (or link to) an explicit marker: "target architecture; consequential effects still route through the local `ApprovalGate`/`side_effect_log` substitutes described in §2, not through Aegis, until WS2's exit criterion is met." The Delta Conformance Statement in `proposals/README.md` gets this marker as a WS0 task (see WS0 task 8). Do not describe "completion only from verified terminal evidence" as current behavior anywhere until §8 item 4 is true. |
| D-LOCAL | **Local, mock-only workflows may complete from their own step results. Consequential external effects may not**, ever, without a verified terminal result from an action authority. | This is the operational, testable meaning of "Completion only from verified terminal evidence" — not a slogan. |
| D-NOGROW | **The engine stays small and dumb.** Linear macro-steps, no back-edges, extensions own their own tables. | Forbidden regardless of workstream: canonical action hashing, precondition CAS, an `unknown` state machine, or an effect ledger in `src/`. See §5 forbidden list. |
| D-SPLIT | **DurableFlow decides when progress is ready to request an effect. It owns nothing else.** ABEP owns the approval→authority contract. Aegis Gateway owns action identity, CAS, dispatch, unknown, receipt. | One-way dependency: the gateway must not import DurableFlow or read its SQLite. DurableFlow must not retry a consequential effect on its own after an ambiguous outcome. |
| D-PORTFOLIO | **Every proposal is classified core / supporting / experimental / constrained / deferred against the Delta test**, not deleted for being outside D1/D2. | Reflected in `proposals/README.md`'s Delta status column (done). Individual proposal files still carry unreframed claims — WS0 task 6. |
| D-CLIENT | **The only permitted code growth is a narrow Aegis client plus a conformance suite and the minimal caller-side state they require.** That state is external-action waiting, request-intent recovery, and the D4 definition refusal only; no authorization logic, CAS, or `unknown` machine is written locally. | This is WS2, with WS0's stopgap D4 guard. It is blocked on Aegis's own WS2 (HTTP Gateway) exit per `grk-aegis-drae-proposal.md` — DurableFlow has nothing to call until that ships. |

---

## 5. Workplan

Do not start a later workstream's code before the previous one's exit criterion. Docs-only cross-links may proceed in parallel.

### Workstream 0 — Claim alignment (docs and docstrings only)

**Goal.** No current DurableFlow document, docstring, or demo script implies that the engine itself provides D1 authorization, D2 effect resolution, or D5 injection defense.

The original version of this workstream was a fixed file list built by targeted grep on a handful of known phrases. That undercounted the claim surface: a repository-wide sweep turns up overclaiming language in `readiness/README.md`, `docs/walkthrough.md`, and `docs/learning-path.md` that the original list missed, none of which contain the specific strings the old exit criterion grepped for. A fixed list cannot be trusted to be complete; treat WS0 as a **claim inventory**, not a patch set, and keep the inventory itself as the artifact of record.

**Tasks.**

1. ~~Replace the thesis in `proposals/README.md` and add a Delta Conformance Statement.~~ **Done** — but see task 8; it now needs the target-architecture marker from D-CLAIM.
2. ~~Add a Delta status column to the proposal index in `proposals/README.md`, classifying every proposal per §4 of the alignment proposal.~~ **Done.**
3. `docs/dflow-arch.md`: the opening Mermaid diagram (Agent → DurableFlow → Recovery/HITL/Context/Eval/Observability → Production) is descriptive, not discriminating — it is exactly the layer diagram the framework rejects as an organizing view. Move it below a new first section that states, as a table: mechanism | assumed precondition | what DurableFlow proves | residual delta, for checkpointing, the human gate, the idempotency key, and versioned workflows. (The alignment proposal's §2.3 already has this table drafted — reuse it, do not redraft.)
4. `docs/field-pattern.md:10` — "Gate every external write until policy can replace the human." is the D6 anti-pattern stated as a design principle. Replace with: containment and risk-tiered autonomy absorb routine writes; humans see fewer, higher-consequence decisions.
5. **Claim inventory.** Build `docs/delta-conformance.md` (mirroring the schema Aegis uses in its own WS0) by grepping the whole repository — not just `docs/`, `readiness/`, `src/` — for the claim-shaped vocabulary: `prevent`, `block`, `ensure`, `guarantee`, `secure`, `safe`, `authoriz`, `governed`, `unauthorized`, `injection`. Every hit gets one of three dispositions in the inventory: **accurate** (already scoped correctly, no change), **fix** (listed with target file/line, folded into this workstream), or **allowlisted** (explicitly educational/mock framing that is honest about what it demonstrates — e.g., a demo script's inline comment — and does not need doc-level hedging). Known **fix** items already found by this sweep, in addition to the readiness spec item in task 6:
   - `readiness/README.md:66` — "primary blocker: the single unsafe behavior that prevents deployment" reads as a platform guarantee; scope it to "readiness scoring," not deployment safety.
   - `docs/walkthrough.md:281` — describes the harness as injecting prompt-injection failures without stating what "handling" it means (pause for review, not defense). Add the same one-line non-claim used in task 6.
   - `docs/learning-path.md:336` — frames the injection demo as "what the wrapped agent does" without stating the gate is a pause, not a block. Add the non-claim line.
   Do not treat this as exhaustive; the inventory file is the durable artifact, and its exit condition (below) requires it to stay current, not to have been correct once.
6. `readiness/docs/dflow-readiness-spec.md` — the prompt-injection scenario (`Then the approval gate intercepts the write before execution` / `telemetry records an unauthorized_write_blocked event`) reads as a D5 claim. Add an explicit non-claim line to the scenario: this demonstrates the write was paused for human review, not that provenance under injection is solved; a deceived approver binds exactly the attacker's act.
7. Code docstrings (not renames — renaming `ApprovalGate` or `side_effect_log` breaks callers for no conformance benefit; the claim is in the label, not the identifier):
   - `src/approval.py`, `ApprovalGate` class: one-line docstring — "Durable workflow interruption. Not an authorization boundary: does not bind action identity, tenant, policy version, or mutable preconditions."
   - `src/store.py`, `log_side_effect` / `side_effect_log`: one-line docstring or comment — "Local mock-replay suppression. Not effect reconciliation: no remote reference, no `unknown` state, no reconciliation deadline."
   - `src/engine.py`, `resume()`: one-line docstring addition — "Resumes against whatever step functions are registered in the current process. No definition pin: a changed registered function for a paused `step_name` is adopted silently (D4). See task 9 for the consequential-path exception."
8. Add the D-CLAIM target-architecture marker to `proposals/README.md`'s Delta Conformance Statement and to any other place the new thesis is quoted (currently just that one file; the inventory in task 5 is the check that no others exist).
9. **D4 minimal containment for consequential paths.** The framework treats general behavioral-compatibility migration as out of scope (pin-and-refuse is Aegis's problem once WS2 exists), but that non-claim needs to be true locally too, today, not just eventually. Add a definition guard: whenever a consequential path enters either `PAUSED_APPROVAL` (the pre-WS2 path) or `WAITING_EXTERNAL_ACTION` (the routed path), persist a `definition_digest` with the approval row or request-intent record. The digest must identify the deployed registered-step implementation, not merely its module + qualname: use an immutable build/deployment identifier plus a digest of the registered function's code and declared consequential-step configuration. On resume or terminal-result handling, if the persisted digest differs from the currently registered definition, refuse rather than execute (`WorkflowStatus` moves to a new terminal `STALE_DEFINITION`) and require operator action. This is deliberately not general D4 migration — it is a single equality check that turns "silently runs new code" into "refuses and asks," which is the framework's own stated mature answer applied narrowly instead of asserted narrowly.
10. Reclassify the individual proposal files flagged `constrained` or `deferred` in `proposals/README.md` (`frontpressure-proposal.md`, `multiagent-proposal.md`, `dataflow-spec.md`, `aws-deployment-proposal.md`): add the same one-line constraint from the README table to each file's own header block, so the constraint travels with the file, not only the index.

**Exit criterion.** `docs/delta-conformance.md` exists, its inventory covers every file the task-5 grep matches (not a fixed list), every match has a disposition, and every **fix** disposition is closed. `ApprovalGate`, `log_side_effect`, and `resume()` have the docstrings from task 7. `docs/dflow-arch.md`'s first `##` section is the mechanism/precondition/proof/residual table, not the Mermaid diagram. The `STALE_DEFINITION` guard from task 9 has passing tests for both consequential wait states: pause/await, change the implementation while retaining its module + qualname, then assert that `resume()` or terminal-result handling refuses rather than executing the changed definition.

**Files.** `docs/delta-conformance.md` (new), `docs/dflow-arch.md`, `docs/field-pattern.md`, `readiness/docs/dflow-readiness-spec.md`, `readiness/README.md`, `docs/walkthrough.md`, `docs/learning-path.md`, `src/approval.py`, `src/store.py`, `src/engine.py`, `proposals/README.md`, `proposals/frontpressure-proposal.md`, `proposals/multiagent-proposal.md`, `proposals/dataflow-spec.md`, `proposals/aws-deployment-proposal.md`.

---

### Workstream 1 — Engine guardrail (standing constraint, not a one-time task)

**Goal.** The engine does not grow into the delta while WS0 and WS2 are in progress or after they complete.

This workstream has no completion date; it is a gate every PR touching `src/` passes through indefinitely. Restated from §4.2 of the original critique as enforceable rules:

**Forbidden in `src/` at any time:**

- canonical action hashing, precondition CAS, or an `unknown` state machine
- turning `side_effect_log` into an effect ledger (adding remote-reference, receipt, or reconciliation-deadline columns)
- adding fields to `approval_queue` that imply authorization (tenant, policy version, single-use token) while a consequential write still fires directly from workflow or agent code
- treating context lineage, DataFlow, or telemetry volume as a second consistency model
- a docstring, README, or demo claiming a "new discipline" or "governed agent control plane"

**Explicitly not forbidden — sanctioned exceptions.** WS0 task 9's `STALE_DEFINITION` guard (one definition-digest equality check that refuses a changed registered definition) and WS2's caller-side request-intent state are not precondition CAS, authorization, or an effect ledger. The former is local D4 containment; the latter records only the caller's recovery state and immutable submitted envelope, never a receipt, remote outcome, or reconciliation decision. They exist because DurableFlow must recover its own work while Aegis remains the action authority. Do not let either become the seed of a broader local versioning, authorization, or effect-resolution system.

**Exit criterion.** None — this is a standing review checklist, not a workstream with a completion state. Reference it explicitly in code review for any PR touching `src/approval.py`, `src/store.py`, or `src/workflows.py`.

**Files.** None owned; this is a constraint on all future changes to `src/`.

---

### Workstream 2 — Independent-client proof plus conformance bundle

**Goal.** DurableFlow completes a consequential workflow only from a verified terminal result returned by the Aegis Gateway, including after injected failures — and it does so without the engine (`src/`) growing beyond WS1's guardrail.

**Blocked on:** Aegis Workstream 2 (`grk-aegis-drae-proposal.md` §5, "Standalone Gateway") reaching its exit criterion — a foreign process can create and observe an action without Aegis internals or the write credential. DurableFlow has no HTTP endpoint to call before that. Do not start this workstream's code before that signal.

#### 5.2.1 Consequential-write inventory

`send_reply` in `src/workflows.py` is not the only local D1/D2 substitute in this repo, and treating it as such was this workstream's original mistake. Every path that calls `ApprovalGate.request_approval` or `WorkflowStore.log_side_effect`/`get_side_effect`, with disposition:

| Path | Mechanism | Calls an external effect? | Disposition |
|---|---|---|---|
| `src/workflows.py: send_reply` (inbox demo) | `ApprovalGate` + `side_effect_log` | Yes (mock today; a real send in any non-demo deployment) | **Route through Aegis.** Task 3 below. |
| `agent/runner.py: _make_commit_handler` / `_execute_write_once` (generic tool loop) | `ApprovalGate` + `side_effect_log`, keyed on any `tool.is_write` handler | Yes — this is the path the MCP demo (`examples/mcp_demo.py`, `mcp_server/`) and the readiness harness (`readiness/`) actually exercise. It is more general than `send_reply`, not a special case of it. | **Route through Aegis.** Task 3 below covers both call sites through one shared submission helper — do not write the Aegis-submission logic twice. |
| `factory/clear_workflow.py: _plan_approval`, `_report_approval` | `ApprovalGate` only; no `side_effect_log`, no external tool call | No — both gate a human sign-off on artifacts already written to the local workspace (plan review, ship review) | **Out of scope, explicitly.** These are local review gates on internal state, not consequential external effects; D-LOCAL's "local, mock-only workflows may complete from their own step results" covers them as-is. Label them as such in `factory/clear_workflow.py`'s docstrings (WS0-style task, folded in here since it's the same file) so a future reader doesn't assume they need Aegis routing too. |
| `factory/workspace.py: write_file` | `side_effect_log` replay suppression around a workspace-root file write | No external effect — it mutates only the explicitly scoped local workspace; it neither calls a provider nor treats the row as a remote receipt | **Out of scope, explicitly.** Keep the local replay guard, label it as workspace-local in its docstring, and do not cite it as a D1/D2 control for consequential effects. |
| `colony/store_ext.py: dispatch_once` | `side_effect_log` marker before the simulated provider's `run_stage` | No external effect — it records an in-process simulation dispatch marker; it does not dispatch to a provider API | **Out of scope, explicitly.** Keep it as simulation bookkeeping and add an inline non-production label. If `colony` gains a real provider adapter, add that adapter as a new inventory row before it can dispatch. |
| `examples/*_demo.py` | Call into one of the rows above | Inherits | No separate work; fixed when the underlying mechanism is fixed. |

Do not start task 3 until this table (or its replacement, if the sweep in WS0 task 5 finds more call sites) is committed to this document — the point of writing it down is that "the inbox path" quietly became the wrong scope once, and a table is the check against that happening again silently.

#### 5.2.2 Fixing the D6 double-gate

As drafted, replacing only `send_reply`'s dispatch step would still leave the *preceding* local `ApprovalGate` pause in place — a workflow would pause for local human approval, resume, and only then submit to Aegis, which may itself require approval under its own policy. That is two human decisions for one action, which is the D6 anti-pattern this whole plan is supposed to prevent, not preserve.

For every row disposed **"Route through Aegis"** above: the workflow step that currently calls `request_approval` and pauses on `PAUSED_APPROVAL` is replaced with a step that submits the prepared action to Aegis directly and pauses on a new `WorkflowStatus.WAITING_EXTERNAL_ACTION` (or equivalent — name it once, use it everywhere). DurableFlow's local `ApprovalGate` is not called on this path at all. Aegis's own policy decides whether a human approval is required for that action, at what tier, and by whom; DurableFlow only knows "pending" vs. "terminal result," matching the read-only `waiting_external_action` framing already agreed in §4.3 of the alignment proposal. `ApprovalGate` keeps its current job only for the out-of-scope row in §5.2.1 (local artifact review) and for any workflow that has no consequential effect at all.

#### 5.2.3 Durable client protocol (the part "checkpointed atomically" was standing in for)

The original task 2 said `caller_request_key` should be "checkpointed before or atomically with the first submission attempt," and cited "the existing checkpoint machinery in `store.py`." That machinery (`save_checkpoint`) only records a step's result *after* the step function returns — there is no primitive today for "a step is in flight and must not be re-submitted if the process dies before it returns." That gap has to be named and closed, not assumed away by a verb ("checkpointed") that the current schema can't support.

Required additions, all new — not a reuse of `save_checkpoint`:

1. **A request-intent record**, written *before* the first submission attempt, distinct from a step checkpoint: `(workflow_id, step_name, caller_request_key, action_fingerprint, canonical_envelope, canonicalization_version, definition_digest, action_id nullable, status, created_at)`, unique on `(workflow_id, step_name)`, where `status` is `intent_recorded -> submitted -> terminal_read`. `canonical_envelope` is the immutable byte-for-byte request representation (or a durable reference to it) used for every recovery submission; do not reconstruct it from possibly changed workflow code. The record is written in the same local transaction that transitions the workflow into `WAITING_EXTERNAL_ACTION`, so a crash between "decided to submit" and "actually sent the HTTP request" is recoverable: on restart, a `submitted`-or-earlier intent with no terminal read is retried with the *same* `caller_request_key` and envelope (safe, because Aegis's rebind rule fails closed on a reused key with changed arguments — it does not create a duplicate action). Persist the returned `action_id` atomically with the `submitted` transition when a response is received.
2. **Action-ID recovery.** The client's `CreateIntent`-equivalent call must be idempotent under the same `caller_request_key`: if DurableFlow crashes after Aegis accepts the intent but before the response is persisted, resuming must re-derive the same `action_id` from Aegis (by re-submitting the identical envelope under the same key and reading back the existing action) rather than creating a second one. This is table-stakes for `gateway-contract.md`'s rebind-refusal behavior, but DurableFlow has to actually call it on resume, not just rely on the server-side refusal never being triggered.
3. **Terminal-state mapping.** Aegis's public vocabulary (`CONFIRMED`, `DENIED`, `FAILED`, `CANCELLED`, `UNRESOLVED`) maps onto DurableFlow's own step-result shape once, in one place, not ad hoc per call site: `CONFIRMED -> StepResult(success)`, `DENIED/FAILED/CANCELLED -> StepResult(failure, reason=...)`, `UNRESOLVED -> workflow stays in WAITING_EXTERNAL_ACTION, operator-visible, no automatic retry`. This mapping is what task 3's "complete only from a verified terminal result" cashes out to in code.
4. **What "verified receipt" means, stated explicitly, not left implicit:** the client must check, before treating a result as terminal, that (a) the receipt's `action_id` matches the one this workflow submitted, (b) its `caller_execution_ref`/`caller_request_key` pair matches this workflow's own identifiers (binding), and (c) the receipt is read from the Gateway's authenticated response, not reconstructed from a cached or caller-supplied copy (integrity — no local code path may synthesize a receipt shape and pass it to the completion step). A receipt for the right action ID but the wrong workflow, or a locally-constructed stand-in used in a test without going through the client, must fail (c) and must not complete the workflow. This is a required negative test in the conformance suite (task 4), not just a design note.

**Tasks.**

1. Commit the inventory in §5.2.1 (or its corrected version, if WS0's sweep finds more rows) to this document before starting task 3.
2. A narrow, optional Aegis client package (e.g. `integrations/aegis_client/`). Core (`src/`) stays stdlib-only; the client is an optional import, matching the pattern already used for other optional adapters in `integrations/`. Implements the request-intent record, action-ID recovery, terminal-state mapping, and receipt verification from §5.2.3.
3. For every **"Route through Aegis"** row in §5.2.1: replace the local-approval-then-dispatch step with submit-to-Aegis-then-await-terminal-result, per §5.2.2 (no local `ApprovalGate` call on this path) and §5.2.3 (durable intent, not a bare checkpoint). `src/workflows.py: send_reply` and `agent/runner.py`'s commit handler both route through the same client submission helper — one implementation, two call sites. The mock-only path stays as a small teaching example with explicit non-production labeling; it does not get deleted.
4. A cross-runtime conformance suite, run against Aegis's fixture client or a real Aegis instance: crash before submit, lost create-intent response, retry same key, approval denied/expired, duplicate dispatch, worker death after remote commit, lost terminal read, rebind attempt (same key, changed arguments), foreign receipt, precondition drift after approval, **and** the receipt-binding negative test from §5.2.3 item 4. This list matches `gateway-contract.md` §10 on the Aegis side and Aegis Workstream 3's harness — do not re-enumerate a third time; the DurableFlow-side suite runs the *same* cases through this repo's client, not a new list.
5. D2 claims in DurableFlow's own docs stop at explicit uncertainty: `unknown`, adapter-specific evidence, proved absence, escalation, no blind retry. No synthesized certainty against a mute API, and no wording implying DurableFlow itself resolves ambiguity — that stays Aegis's.

**Non-goals here.** D3 delegation vocabulary. General D4 behavioral-compatibility research (pin-and-refuse, per WS0 task 3's table, is enough; the narrow local `STALE_DEFINITION` guard from WS0 task 9 is a stopgap for the period before this workstream exits, not a substitute for it). Containment/sandboxing — rented, not rebuilt in Python.

**Exit criterion.** A DurableFlow run — through both the inbox path and the agent-tool-loop path in §5.2.1 — produces a trace bundle that Aegis's WS3 conformance harness (`grk-aegis-drae-proposal.md` §5, Workstream 3) accepts, including after each injected failure in task 4, with no local `ApprovalGate` call on either path. This is the alignment proposal's Phase 3 exit, recorded as a joint artifact between the two repos — not a DurableFlow-only sign-off. In the same change, remove the D-CLAIM target-architecture marker from `proposals/README.md` (WS0 task 8) — the claim is no longer aspirational once this exit criterion is met, and the marker must not outlive the fact it was hedging.

**Files.** `integrations/aegis_client/` (new); `src/store.py` and `src/engine.py` (only the `WAITING_EXTERNAL_ACTION` / `STALE_DEFINITION` states and transactional request-intent persistence/recovery hooks); `src/workflows.py` (`send_reply` path); `agent/runner.py` (`_make_commit_handler` / `_execute_write_once` path); `factory/clear_workflow.py`, `factory/workspace.py`, and `colony/store_ext.py` (docstrings/comments only, per §5.2.1). No other changes to `src/`.

---

## 6. Sequencing

```text
WS0 claim alignment (docs, docstrings)
  → WS2 client + conformance suite, gated on Aegis WS2 (HTTP Gateway) exit
WS1 engine guardrail — standing, runs throughout, blocks nothing, is blocked by nothing
```

WS0 and WS1 have no ordering dependency on each other or on the sibling repos. WS2 cannot start — not "should not," cannot, since there is no endpoint to call — until Aegis's own Workstream 2 exits.

---

## 7. Cross-repo obligations (not resolved here)

| Repo | Obligation | This document's relationship to it |
|---|---|---|
| `abep` | Refinement mapping targets, D1 world-CAS semantics | Referenced (§2, §3); owned by `abep`/`aegis`, not scheduled here |
| `aegis` | Refinement mapping, precondition identity, executor-time refuse-on-drift, HTTP Gateway, foreign-client harness | WS2 above is blocked on Aegis's WS1–WS3; see `grk-aegis-drae-proposal.md` |
| `durableflow` | WS0–WS2 above | This document |

---

## 8. Acceptance (plan is realized when)

1. No DurableFlow document, docstring, or demo script implies the engine itself enforces ABEP or resolves ambiguous remote effects (WS0 exit), and the claim inventory in `docs/delta-conformance.md` covers the whole repository, not a fixed file list.
2. `src/` has not grown a canonical action hash, precondition CAS, or `unknown` state machine, with the single named exception of the `STALE_DEFINITION` guard (WS1, checked continuously).
3. Every proposal in the portfolio carries its Delta status both in the index and in its own file header (WS0 task 10).
4. Every consequential-write path identified in §5.2.1 — not only `send_reply` — completes only from an Aegis-verified terminal result, including after injected failure, and the resulting trace bundle is accepted by Aegis's independent conformance harness (WS2 exit).
5. On none of those paths does a local `ApprovalGate` pause precede the Aegis submission (§5.2.2 — no double-gate).
6. Ambiguous outcomes never trigger a DurableFlow-side blind retry (WS2 task 5, checked by the conformance suite in task 4), and a receipt that fails the binding/integrity check in §5.2.3 item 4 cannot complete a workflow (checked by a dedicated negative test).
7. A consequential workflow in either local-approval or external-action wait refuses to resume or consume a terminal result under a changed registered definition rather than silently adopting it (WS0 task 9's `STALE_DEFINITION` guard).
8. `docs/dflow-arch.md` opens with the mechanism/precondition/proof/residual table, not the layer diagram.

---

## 9. Non-goals

- DurableFlow becoming the action platform. The gap is a **framework-neutral action/effect boundary** that can sit under LangGraph, Temporal, Claude, or this lab. DurableFlow's distinct value after WS2 is as the *second, differently implemented orchestrator* that proves the gateway is a real boundary, not an internal package convention.
- Building a second Aegis inside `approval_queue` or `side_effect_log` (WS1).
- Claiming D3, D5, or general D4 migration from this repo.
- Treating context lineage, DataFlow, or telemetry volume as a second consistency model.
- If the Aegis integration in WS2 turns out to have no audience, the fallback is smaller than a workplan failure: keep the educational baseline, keep the WS0 claim changes, and do not grow HITL, memory, or side-effect features as if they closed a delta.

---

## 10. Risks

**The thesis change becomes an unearned claim.** Symptom: `proposals/README.md`'s Delta Conformance Statement ships (it has), WS2 never starts or never exits, and six months later a README or demo still reads as if DurableFlow resolves D1/D2. Response: WS0's exit criterion is necessary, not sufficient — §8 item 4 (WS2's actual exit) is the claim's real backstop. Do not treat WS0 completion as the finish line.

**WS1's guardrail erodes one small PR at a time.** Symptom: a reviewer approves "just one field" on `approval_queue` or "just a status enum" on `side_effect_log" because it looks locally reasonable. Response: the forbidden list in WS1 is not a suggestion; a PR that adds any of those fields is out of scope for this repo regardless of how small it looks, full stop — redirect it to the Aegis client work in WS2 or to Aegis itself.

**WS2 is scheduled but Aegis's WS2 slips.** Symptom: this plan's WS2 has nothing to call for an extended period. Response: that is expected and not a reason to build a local substitute — see WS1. Track Aegis's WS2 exit as the trigger, not a calendar date.

**The mechanism/precondition/proof/residual table in `docs/dflow-arch.md` (WS0 task 3) is copied from the alignment proposal and drifts.** Symptom: the alignment proposal's §2.3 table is edited and `dflow-arch.md`'s copy is not. Response: WS0 task 3 should link to the alignment proposal's table rather than duplicate it verbatim, if the doc format allows; if duplicated, note the source and treat divergence as a doc bug, not a design disagreement.

**The consequential-write inventory in §5.2.1 is wrong the same way the original single-file WS2 scope was wrong — undercounted.** Symptom: a write-capable path is added later (a new tool in `agent/runner.py`'s tool map, a new example, a factory workspace writer, a Colony provider adapter) that calls `ApprovalGate` or `side_effect_log` directly, and nobody updates the table. Response: reviewers of `agent/`, `factory/`, `colony/`, and `src/` must treat a new write-capable path as a new §5.2.1 row, not a self-contained feature. An unreviewed new consequential tool is the same category of scope violation as adding a field to `approval_queue`; a newly external `factory` or `colony` operation loses its current out-of-scope disposition until the table is updated.

**The double-gate fix in §5.2.2 removes the local pause, and nothing catches a caller that skips submission entirely.** Symptom: a workflow step is refactored to call an external effect directly, bypassing both the old `ApprovalGate` path and the new Aegis-submission step, because the local gate that used to force a pause is gone. Response: the conformance suite (task 4) must include a test that a workflow *cannot* reach a completed state for a consequential step without a recorded request-intent (§5.2.3 item 1) for that step — absence of the intent record, not just presence of a bad receipt, should fail the suite.

**D-CLAIM's target-architecture marker is added once and goes stale.** Symptom: WS0 task 8 ships the marker, WS2 later exits, and the marker is never removed — the README now underclaims instead of overclaiming. Response: §8 item 4 (WS2 exit) is the trigger to remove the marker in the same change that flips the conformance suite green; make that removal part of WS2's own exit criterion, not a follow-up someone might forget.

---

## 11. Immediate next commit after this file

Workstream 0, remaining tasks in order:

1. `docs/dflow-arch.md` — move the layer diagram below the mechanism/precondition/proof/residual table.
2. `docs/field-pattern.md:10` — reframe the "gate every write" line.
3. `docs/delta-conformance.md` — run the claim-inventory grep, disposition every hit, and fold in the three already-found items (`readiness/README.md:66`, `docs/walkthrough.md:281`, `docs/learning-path.md:336`) plus the readiness spec scenario.
4. `readiness/docs/dflow-readiness-spec.md` — add the D5 non-claim line to the prompt-injection scenario.
5. `src/approval.py`, `src/store.py`, `src/engine.py` — add the three docstrings.
6. `src/engine.py` / `src/store.py` — add the `STALE_DEFINITION` guard and its test.
7. `proposals/README.md` — add the D-CLAIM target-architecture marker to the Delta Conformance Statement.
8. The four flagged proposal files — add the header constraint line each already has in the README table.
9. Commit the §5.2.1 consequential-write inventory table to this document (a documentation-only step; it gates WS2, not WS0's own exit).

Then stop. WS2 does not start until Aegis's WS2 exit is observed, not assumed.

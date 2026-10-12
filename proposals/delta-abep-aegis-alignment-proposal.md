# Proposal: Align DurableFlow with the Delta Framework, ABEP, and Aegis

**Status:** PROPOSAL (direction). Aegis-side schedule is now a PLAN.  
**Created:** 2026-08-16  
**Applies to:** DurableFlow core, documentation, examples, and proposal portfolio  
**Related repositories:** [`abep`](../../abep/README.md), [`aegis`](../../aegis/README.md)  
**Primary lens:** the Delta Framework (an internal working doc, not tracked in this repository)  
**Executable Aegis schedule:** [`aegis/docs/grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md)  
**Decision type:** Scope, ownership, and cross-repository integration. This document is the architectural direction. It is not the Aegis workplan.  

---

## 0. Decision summary

DurableFlow should adopt the Delta Framework as its architectural scope test,
but not present that framework as a wire-level or runtime standard. ABEP should
own the normative approval-to-execution protocol. Aegis should own the concrete
action gateway, enforcement boundary, effect-resolution lifecycle, and runtime
evidence. DurableFlow should remain a small orchestration runtime and become an
independent client of the Aegis Gateway for consequential effects.

The intended relationship is:

```text
Delta Framework
  identifies the residual engineering problem and rejects scope inflation
          |
          v
ABEP
  specifies the approval-to-authorization safety contract
          |
          v
Aegis Action Gateway
  enforces action identity, approval binding, dispatch, resolution, and receipts
          |
          v
DurableFlow
  exercises the boundary as an independent durable workflow client
```

This proposal does **not** merge the repositories. It gives each one a distinct
claim and removes duplicated authority and effect state from DurableFlow.

Aegis owns the runtime. That is locked in
[`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md)
(D-RT, D-TOK): no Python ABEP executor; authorization is a tested refinement
mapping, not a decorative token; declared preconditions are new Aegis work.
Phases 1–4 below are scheduled there. Phase 0 remains the DurableFlow-side
ask of *this* proposal.

---

## 1. Why this proposal exists

DurableFlow was designed as a compact demonstration of durable checkpoints,
crash recovery, approval pauses, model routing, context selection, cost
accounting, and local replay suppression. Those mechanisms are implemented and
useful for teaching orchestration.

The Delta Framework changes the evaluation criterion. It argues that a platform
surface is justified only when it can name:

1. a mature mechanism;
2. the precondition that mechanism assumes;
3. what an agent deployment supplies instead; and
4. the residual delta that one team can actually own.

Under that test, most of DurableFlow is mature workflow machinery rather than a
new agent-platform boundary. That does not make DurableFlow incorrect. It means
its claims, documentation, and roadmap should distinguish **baseline
orchestration** from **delta-closing enforcement**.

The availability of ABEP and Aegis makes that distinction actionable:

- ABEP already specifies the narrow approval-bound execution property.
- Aegis already implements substantial action, approval, dispatch,
  reconciliation, pinning, receipt, and evidence machinery.
- Reimplementing those mechanisms inside DurableFlow would create two
  incompatible authorities for the same effect.

---

## 2. Critique of DurableFlow through the Delta lens

### 2.1 What DurableFlow demonstrates well

DurableFlow has a credible baseline:

- checkpoints persist across process death;
- completed steps are not re-executed during ordinary resume;
- approval queue state is separated from workflow state;
- the crash demo uses a real subprocess exit;
- context selection enforces a hard local budget;
- model routing and cost accounting have explicit contracts;
- the mock send checks a deterministic local idempotency key; and
- the docs correctly disclaim remote exactly-once delivery.

These are strengths. They should remain executable examples and regression
tests. The critique is about the width and organization of the claim, not the
quality of those demonstrations.

### 2.2 The current organizing thesis is too broad

The proposal index currently states:

> Workflow-as-truth. Agent-as-worker. Completion-as-evidence.

That formulation conflicts with the emerging cross-repository architecture in
three ways:

1. **Workflow state is not execution authority.** ABEP makes authorization a
   separately enforced decision. Aegis makes its Gateway ledger authoritative
   for an action and prevents the workflow runtime from mutating that state.
2. **Completion is not evidence by itself.** A workflow can say `completed`
   without possessing an authoritative effect receipt. The Delta Framework
   correctly reframes the issue as referential integrity across request,
   approval, authorization, effect, and receipt.
3. **“Governed control plane” invites scope inflation.** Context governance,
   data lineage, front-pressure, multi-agent coordination, evaluation, policy,
   and deployment can all fit under that phrase without identifying a violated
   precondition or distinct engineering delta.

A narrower DurableFlow thesis should be:

> **Workflow-as-progress. External authority by contract. Completion only from
> verified terminal evidence.**

For local or mock-only workflows, DurableFlow may still complete from its own
step results. For consequential external effects, completion must depend on a
terminal result returned by the action authority.

### 2.3 The opening architecture is descriptive, not discriminating

[`docs/dflow-arch.md`](../docs/dflow-arch.md) opens with a layer diagram that
places recovery, HITL, context, evaluation, and observability between an agent
and production. The Delta Framework explicitly rejects a layer diagram as the
organizing principle because existing mechanisms can populate every box while
leaving the residual problem unnamed.

Component and sequence diagrams remain useful, but the first architectural view
should instead state:

| Mechanism | Assumed precondition | What DurableFlow proves | Residual delta |
|---|---|---|---|
| Workflow checkpointing | Replayed activities are safe | Local steps resume from durable checkpoints | Consequential effects require a separate effect authority |
| Human workflow gate | Approved state remains attached to the intended effect | Pause, persist, approve/reject, resume | Approval must bind exact action and mutable preconditions |
| Idempotency key | Endpoint honors the key and exposes a stable operation identity | Mock result is locally replay-suppressed | Unknown remote outcomes require resolution and reconciliation |
| Versioned workflow | Running work retains compatible semantics | Not currently proved by DurableFlow | Pin or refuse changed definitions for in-flight work |

### 2.4 D1: the approval gate is not authorization

DurableFlow persists a draft payload and later checks whether its approval row
is `approved`. The send step then constructs an idempotency key and produces the
mock effect. The approval does not bind:

- a canonical action identity;
- tenant and requesting principal;
- policy identifier and version;
- canonicalization version;
- the effect's idempotency key;
- mutable external preconditions; or
- an executor-enforced, single-use authorization.

Therefore the current gate demonstrates durable human interruption, not D1's
optimistic-concurrency-aware authorization. Adding fields to
`approval_queue` would not be sufficient if `send_reply` remained directly
reachable from workflow code.

### 2.5 D2: local replay suppression is not effect resolution

`side_effect_log` stores a known mock result after the result is constructed. It
does not represent the interval in which a remote system may have committed an
effect while the caller lost the response.

The current state model has no explicit:

- dispatch attempt;
- executing or ambiguous state;
- remote reference;
- authoritative observation;
- immutable effect receipt;
- reconciliation deadline; or
- manual escalation outcome.

The existing disclaimer about remote exactly-once delivery is correct and must
remain. The architectural consequence is that DurableFlow should delegate this
problem rather than grow `side_effect_log` into a second Aegis ledger.

### 2.6 D4: resume can silently adopt new semantics

DurableFlow resumes from an integer step index against the functions registered
in the current process. It does not pin a workflow definition, prompt, model
route, policy, tool schema, or canonicalization version. A paused or crashed
workflow may therefore continue under code that did not govern its earlier
steps.

The Delta Framework treats behavioral compatibility as unresolved research but
also records the conservative mature answer: pin the artifacts and refuse
implicit migration. Aegis already demonstrates that answer with signed release
manifests and a paused execution that survives a release upgrade. DurableFlow
should either pin a small workflow-definition digest locally or treat the Aegis
release/action identity as authoritative for the consequential portion of a
run.

### 2.7 D5 and D6 constrain the claims

Approval does not solve instruction injection. A model can prepare an
attacker-chosen but internally consistent action, and a deceived human can
approve exactly that action. DurableFlow must not describe mediation or HITL as
a general solution to provenance under injection.

Approval also does not scale as a per-action default. The inbox demo is useful
for pause/resume semantics, but production framing should say that containment
and risk-tiered autonomy absorb routine cases, leaving fewer consequential
decisions for humans. Proposals that optimize approval throughput must first
show that they reduce attention demand rather than industrialize alert fatigue.

### 2.8 Correlation and evidence are partial

`workflow_id` is propagated effectively, but DurableFlow does not join workflow,
approval, authorization, effect, remote operation, and receipt namespaces. Its
JSONL telemetry is observational and is not an authority-bearing evidence
chain.

The core integrity questions cannot currently be asked mechanically:

- Did an effect occur without a matching approval?
- Did the approval bind the action that was dispatched?
- Did workflow completion rely on the correct receipt?
- Does the receipt refer to the same remote operation and idempotency key?

DurableFlow should carry Aegis identifiers and persist the verified terminal
result it receives. It should not reproduce Aegis's evidence ledger.

---

## 3. Portfolio critique and proposed disposition

The existing proposals are not all invalid. They should be classified by their
relationship to the Delta Framework so that optional experiments do not become
core platform claims.

| Area | Delta assessment | Proposed disposition |
|---|---|---|
| Core checkpoint/resume | Mature workflow substrate | Keep as DurableFlow core |
| Core lifecycle evidence | Useful orchestration legibility, not a new evidence consistency model | Keep narrowly; do not compete with Aegis effect evidence |
| Trajectory evals | Potential support for D4 and conformance | Keep experimental; require a falsifiable compatibility question |
| Experiment replay | D4 research support | Keep outside the execution authority path |
| Front-pressure HITL | In tension with D6 if it optimizes approval volume | Reframe around reducing and consolidating interventions |
| Context selection | Application support; governed memory has no identified delta | Keep as a demo/extension, not platform scope |
| DataFlow lineage | Mature typed-artifact lineage | Keep optional and descriptive; do not claim a new control plane |
| Multi-agent governance | No distinct delta currently identified | Defer until a concrete precondition violation is shown |
| AWS deployment | Risks duplicating Aegis enforcement topology | Reconcile around deployment of the Aegis boundary, not a second DurableFlow authority layer |
| nanoq integrations | Useful consumer and operator demonstrations | Keep as integrations, not core guarantees |
| Colony and planner extensions | Domain experiments | Keep isolated from core authority claims |

No proposal needs to be deleted solely because it is outside D1/D2. The rule is
that it must be labeled as application support, research, or demonstration and
must not expand the claimed platform boundary without passing the Delta test.

---

## 4. Reconciliation with ABEP

### 4.1 ABEP's role

ABEP should be the normative protocol for the narrow approval-to-execution
property:

> A high-risk action crosses the protected execution boundary only after a
> valid approval matching that exact action causes issuance of single-use
> execution authority.

ABEP owns:

- protocol states and legal transitions;
- the matching predicate;
- authorization-at-issuance semantics;
- single-use execution authority;
- trust assumptions;
- formal invariants and negative controls; and
- runtime conformance requirements.

DurableFlow should not define a competing meaning of authorization.

### 4.2 Delta-driven extension to ABEP — done

This was open when this proposal was written. It is now implemented in `abep`,
not a pending ask: action identity includes declared preconditions, approval
validity and world-state validity are separate checks, and
`ExecutedImpliesWorldMatchedDeclaration` is a checked TLA+ invariant with a
verified `NaiveWorld` negative control (parameters unchanged, world drifts,
effect still happens — violates as expected). See `abep/README.md` and
`abep/docs/abep-technical-report.md`.

Remaining ABEP-side work is not a new extension. The runtime is Aegis, not a
monitor written inside `abep/`. Closing the refinement gap is Aegis Workstream 1
in [`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md):
publish a tested mapping from Aegis ledger states onto ABEP's `Authorize` /
token-consume transitions. Do not add a decorative bearer token. ABEP keeps the
TLA+ spec, trace schema, and TLC-based validator.

---

## 5. Reconciliation with Aegis

### 5.1 Aegis's role

Aegis already implements much of the target platform boundary:

- `ActionIntent` with immutable action identity;
- canonical argument and policy digests;
- approval binding and atomic state transition;
- release pinning for in-flight work;
- conditional action transitions;
- dispatch obligations, leases, and generation fencing;
- explicit ambiguous-outcome reconciliation;
- authoritative lookup by idempotency key;
- immutable receipts and terminal-result verification; and
- claim-by-claim tests and evidence artifacts.

Aegis should own:

- the standalone Action Gateway contract;
- action, approval, dispatch, verification, and reconciliation state;
- the effect adapter boundary;
- terminal receipts and action evidence; and
- enforcement/conformance tests.

### 5.2 Gaps before claiming ABEP conformance

Aegis does not yet claim or prove full ABEP implementation:

1. Its approval transition leads directly to `AUTHORIZED`; it does not yet
   publish a tested mapping from that edge, the immutable action binding, the
   dispatch obligation, and the generation-fenced lease onto ABEP's `Authorize`
   / token-consume transitions. **Decision (D-TOK):** refinement mapping, not a
   decorative token. Reopen only if a named negative test cannot be expressed
   without a distinct consumed capability. Schedule: Aegis WS1.
2. Complete mediation is structural in the current demo, not established by a
   real credential/network boundary. Unchanged; Aegis WS2.
3. Approver identity is injected; authentication and approver entitlement are
   not implemented. Unchanged; keep explicit (D-UNIMP).
4. Its strongest reconciliation demo uses a participating Change API with a
   stable key and authoritative lookup. D2's hardest case is a non-participating
   endpoint. Unchanged; Aegis WS4.

The refinement must state which Aegis event corresponds to each ABEP abstract
transition and supply negative tests for illegal traces. The working draft is
Aegis plan §4; the filled artifact is `aegis/docs/abep-refinement.md` (not yet
written).

### 5.3 D2 boundary

Aegis correctly refuses to infer absence from a failed lookup and reconciles
ambiguous results before retry. For an endpoint with no stable reference or
status query, the current safe result is escalation.

Future synthesized reconciliation should be adapter-specific and evidence
graded. Possible strategies include:

- searching by stable business attributes;
- reading a secondary resource or event stream;
- correlating provider notifications;
- requesting operator-supplied evidence; or
- declaring the outcome unresolved and prohibiting automatic retry.

No generic strategy should silently upgrade probabilistic evidence into an
authoritative receipt.

---

## 6. Target ownership model

| Concern | DurableFlow | ABEP | Aegis |
|---|---|---|---|
| Workflow progress and checkpoints | **Owns** | — | Owns only its reference Runtime |
| LLM calls, context, and workflow-local data | **Owns** | — | Does not own |
| Approval protocol semantics | Consumes | **Owns** | Implements/refines |
| Action identity and policy binding | Carries references | Specifies | **Owns** |
| External precondition contract | Supplies declared values | Specifies required binding | **Enforces through adapter** |
| Dispatch and retry authority | Must not own | Constrains | **Owns** |
| Ambiguous effect resolution | Observes terminal/non-terminal result | Outside core D1 | **Owns** |
| Effect receipt | Persists verified reference/copy | Names correlation obligation | **Owns authoritative record** |
| Workflow telemetry | **Owns** | — | — |
| Action/effect evidence | References | Specifies required chain | **Owns** |
| Formal protocol model | — | **Owns** | Supplies refinement evidence |
| Cross-runtime integration test | **Owns client side** | Defines expected traces | **Owns gateway side** |

The dependency is one-way: DurableFlow calls the Aegis Gateway. The Gateway
must not import DurableFlow, inspect its SQLite database, or mutate workflow
state.

---

## 7. DurableFlow-to-Aegis integration contract

### 7.1 Required Gateway surface — specified, not shipped

`aegis/docs/gateway-contract.md` now specifies this surface (`POST /actions`,
`GET /actions/{action_id}`, approval and cancel endpoints, receipt read) in
more detail than restating it here would add, including the Action Envelope
schema and the DurableFlow adapter named explicitly as the first foreign-client
proof. That document is the authoritative shape; treat it as such rather than
maintaining a second copy here. Status per that document: experimental
specification, not implemented as a running service — the current Aegis
Gateway is still a Go package called by the Runtime, not a callable API.

### 7.2 DurableFlow workflow shape

The consequential path should become:

```text
ingest_email
select_context
triage_llm
draft_reply
prepare_action
submit_action_to_aegis
await_aegis_terminal_result
complete_from_verified_receipt
```

Approval, authorization, dispatch, and reconciliation are Aegis substates. They
must not be mirrored into independent DurableFlow authority states. DurableFlow
may expose a read-only summary such as `waiting_external_action`, but Aegis
remains the source of truth for why the action is non-terminal.

### 7.3 Stable correlation

The first integration must propagate:

```text
DurableFlow workflow_id       -> Aegis caller_execution_ref
DurableFlow action step key   -> Aegis caller_request_key
Aegis action_id               -> DurableFlow checkpoint data
Aegis receipt identity        -> DurableFlow terminal checkpoint
```

The caller request key must be stable across crash and retry. DurableFlow must
checkpoint it before or atomically with the first submission attempt. Repeating
the request with changed action identity must fail closed as a rebind attempt,
not create a second action.

### 7.4 Completion rule

For a consequential action, DurableFlow may transition its workflow to
`completed` only after the Gateway returns a verified terminal result that:

- references the expected `action_id`;
- carries the expected `caller_execution_ref`;
- is terminal under the Gateway contract; and
- includes the required receipt or denial/escalation evidence.

An HTTP success from submission, an `AUTHORIZED` action, a dispatch
acknowledgement, or a locally cached approval is not workflow completion.

### 7.5 Failure and recovery behavior

`aegis/docs/gateway-contract.md §10` already enumerates the required fault
injections for the Gateway side of this suite (crash before intent creation,
lost response, duplicate submission, reused key with changed arguments,
precondition drift after approval, worker death before/after remote
acceptance, escalation, and the rest). The cross-runtime suite is that list
run against a real DurableFlow client rather than a fixture — it does not need
a second enumeration here. DurableFlow's specific obligation is to prove its
side of each case: it checkpoints the request key before or atomically with
first submission, and it never independently retries or synthesizes a terminal
result while a case is in flight.

---

## 8. Required alignment artifacts

### 8.1 Delta Conformance Statement

Each repository should maintain a short statement with this schema:

```text
Primary delta(s):
Mature mechanism used:
Violated precondition:
Residual property owned here:
Trusted assumptions:
Evidence level:
Explicit non-claims:
Falsified or made redundant if:
```

For DurableFlow the initial statement should say that it owns no new D1/D2
guarantee in standalone mode. It demonstrates mature orchestration and exercises
D1/D2 only through the Aegis integration.

### 8.2 ABEP-to-Aegis refinement matrix

This matrix is a DurableFlow-side reminder of the required artifact. The
working draft, token-consumption mapping, and file/test schedule live in
[`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md) §4
and Workstream 1. Do not maintain a second competing table here.

ABEP and Aegis jointly map:

| ABEP concept/transition | Aegis persisted record/event | Enforcement point | Test |
|---|---|---|---|
| Proposed/normalized action | `ActionIntent PREPARED` | Gateway create-intent transaction | identity/rebind tests |
| Policy evaluated | policy digest transition | Gateway policy actor | write-once policy tests |
| Approval recorded | approval record + transition | approval handler transaction | mutation/expiry/replay tests |
| Authorization issued | documented refinement: `ActionIntent` at `AUTHORIZED` + approval digest + identity snapshot | Gateway ledger | authorization invariant tests (Aegis WS1) |
| Authorization consumed | dispatch-lease generation fence + terminal ActionIntent (not a decorative token) | dispatch boundary | concurrency/replay tests (Aegis WS1) |
| Effect executed | provider operation identity | tool adapter | duplicate-effect tests |
| Outcome resolved | observation + receipt | reconciliation worker | ambiguous-result tests |

### 8.3 Cross-repository conformance bundle

One generated trace bundle should contain enough correlated identifiers to join:

- DurableFlow workflow and checkpoint events;
- Aegis action and transition events;
- approval evidence;
- dispatch and reconciliation attempts;
- the authoritative provider observation; and
- the terminal receipt.

The verifier should be independent of the demo producer and fail when a required
edge or identifier is missing or inconsistent.

---

## 9. Phased evolution plan

Phases 1–4 are scheduled in
[`aegis/docs/grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md)
(Workstreams 1–4). Do not invent a second Aegis sequence here. Phase 0 is the
only phase whose remaining work belongs in DurableFlow.

### Phase 0: align DurableFlow claims — thesis done, arch opening remains

- Adopt this proposal as the cross-repository direction.
- Add a Delta Conformance Statement to each repository.
- Update DurableFlow's architecture opening and core thesis.
- Mark the current approval gate as workflow interruption, not D1
  authorization.
- Mark `side_effect_log` as mock/local replay suppression, not D2 resolution.
- Classify existing DurableFlow proposals as core, supporting, experimental, or
  deferred using section 3.

**Exit criterion:** no current document implies that DurableFlow alone enforces
ABEP or resolves ambiguous remote effects. Thesis and proposal classification
in `proposals/README.md` are updated. Remaining: `docs/dflow-arch.md` still
opens with the layer diagram. DurableFlow-side sequencing is
[`drae-dflow-workplan.md`](drae-dflow-workplan.md). Aegis-side sequencing is
[`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md).

### Phase 1: reconcile ABEP and Aegis semantics — ABEP side done, Aegis WS1 open

- ~~Decide explicit authorization record versus refinement mapping.~~ Locked:
  refinement mapping (D-TOK). See the Aegis plan.
- ~~Add precondition identity and executor-time validation to the protocol design.~~
  Done on the ABEP side — see §4.2. Aegis still lacks declared-world identity
  and executor-time refuse-on-drift (D-PRE).
- Map ABEP transitions to Aegis records and events (Aegis WS1.1).
- Add missing negative controls for precondition drift and authorization reuse.
  Done on the ABEP side (`NaiveWorld` config); Aegis WS1.4.
- Keep Aegis's current claim boundaries around authentication and real IAM.

**Exit criterion:** every ABEP safety transition has a named Aegis enforcement
point or is explicitly unimplemented. Not yet met — scheduled as Aegis
Workstream 1. HTTP Gateway code must not start before that exit.

### Phase 2: make the Aegis Gateway independently consumable — specified, not shipped

- ~~Expose the narrow authenticated Gateway API.~~ Specified in
  `aegis/docs/gateway-contract.md`; not implemented as a running service.
- Add coherent terminal-result reads.
- Establish trusted caller and approver identity handling.
- Add an integration credential that cannot call the Change API directly.
- Preserve Aegis Runtime as the first reference client.

**Exit criterion:** a foreign process can create and observe an action without
access to Aegis internals or the external effect credential. Not yet met — the
Gateway is still a Go package called by the Runtime, not a callable API.

### Phase 3: add the DurableFlow adapter

- Add an optional Aegis client package; keep DurableFlow core stdlib-only where
  practical.
- Replace the consequential inbox send path with Gateway submission and terminal
  observation.
- Persist stable request/action/receipt correlation.
- Add crash and retry tests spanning both runtimes.
- Retain the existing mock-only path as a small teaching example with explicit
  non-production labeling.

**Exit criterion:** DurableFlow completes a consequential workflow only from an
Aegis verified terminal result, including after injected failures.

### Phase 4: exercise the actual deltas

- Add a resource-version drift scenario and conditional executor refusal for D1.
- Add at least one limited/non-participating endpoint profile for D2.
- Demonstrate safe escalation when reconciliation cannot establish an outcome.
- Publish the correlated, independently validated trace bundle.

**Exit criterion:** the integration tests distinguish action drift, unknown
outcome, proved absence, confirmed effect, and unresolved escalation.

---

## 10. Acceptance criteria

This proposal is successfully realized when:

1. DurableFlow is documented as an orchestration runtime, not the authority for
   consequential effects.
2. ABEP is the only normative approval-bound execution protocol in the project
   family.
3. Aegis publishes a tested ABEP refinement mapping (D-TOK). A decorative
   token is forbidden unless that mapping fails a named negative test.
4. Mutable external preconditions are represented and checked at effect time.
5. A standalone Aegis Gateway accepts a DurableFlow caller without importing or
   reading DurableFlow state.
6. DurableFlow uses stable request identity across crash and retry.
7. Workflow completion is correlated to an Aegis verified terminal result.
8. Ambiguous outcomes never trigger a blind DurableFlow retry.
9. The conformance suite includes approval drift, duplicate delivery, lost
   responses, worker death, reconciliation, and mismatched receipt cases.
10. Every public guarantee names its evidence level and trusted assumptions.

---

## 11. Non-goals

- Combining the three repositories into a monorepo
- Replacing DurableFlow with the Aegis Runtime
- Making ABEP a general agent-governance or policy language
- Claiming prompt-injection prevention from approval binding
- Building cross-organizational delegation vocabulary under D3
- Solving behavioral compatibility migration under D4
- Treating telemetry volume as evidence integrity
- Claiming exactly-once effects against endpoints that do not support the
  required identity or reconciliation contract
- Requiring every low-risk or reversible action to receive human approval

---

## 12. Risks and counterarguments

### “Aegis already has a Runtime; DurableFlow adds no value.”

That is true if DurableFlow duplicates the Aegis Runtime. Its distinct value is
as an independent, differently implemented orchestration client proving that the
Gateway boundary is real rather than an internal package convention. If that
integration reveals no reusable contract and has no audience, DurableFlow
should remain only an educational baseline rather than force a product role.

### “A separate Gateway adds latency and operational complexity.”

It does. The boundary is justified only for consequential effects where exact
authority, ambiguous-outcome handling, and independent enforcement matter.
Low-risk local steps remain inside DurableFlow.

### “Aegis already solves D2.”

Aegis strongly solves the participating-endpoint case represented by its Change
API. The Delta residual concerns endpoints without stable keys, authoritative
lookup, or references. Safe escalation is correct but is not synthesized
resolution. Claims must preserve that boundary.

### “The Delta Framework may later be falsified.”

That is expected. It is a scope and decision framework, not a wire contract.
ABEP and Aegis invariants must stand on their own, while their investment and
positioning may change as empirical evidence changes.

---

## 13. Recommended immediate decision

Phase 1's ABEP-side work and Phase 2's Aegis contract spec are already done
(§4.2, §7.1). The Aegis executable schedule is
[`grk-aegis-drae-proposal.md`](../../aegis/docs/grk-aegis-drae-proposal.md).
Phase 0 is not done, and it is the only phase that requires action in *this*
repository: approve the ownership model and do the documentation alignment
before implementing additional DurableFlow governance or side-effect features.
Aegis Workstream 1 (refinement mapping + declared-precondition CAS) is the
remaining gate for any cross-repository code.

The central rule is:

> DurableFlow may decide **when workflow progress is ready to request an
> effect**. It must not decide **whether that consequential effect is authorized
> or whether an ambiguous remote effect occurred**. Those decisions belong to
> the target ABEP-conformant Aegis boundary.

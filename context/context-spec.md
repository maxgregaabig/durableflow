# Specification: DurableFlow Context (`/context`)

**Status:** DRAFT (v0.1 implemented; see §14 for next evolution)
**Extension level:** Peer extension to Colony and Planner. Context extends DurableFlow core by making information state durable and inspectable alongside workflow execution state.
**Author:** Marcos Polanco
**Created:** 2026-06-19
**Repository:** `durableflow`
**Applies:** `process/spec-policy.md`, `process/semantics-policy.md`
**Depends on:** DurableFlow core SQLite persistence, `WorkflowStore`, `StepResult`, `TelemetryLogger`, and the existing inbox triage context-selection path.
**Dependency policy:** Core implementation remains Python standard library only. Optional development dependency remains `pytest==8.4.2`.
**Visibility:** Private implementation guide. The public artifact is the repo: README, code, tests, examples, and audit traces.

---

## 0. Positioning Note

DurableFlow already proves that agentic execution needs a durable shell: checkpoint every step, survive crashes, gate side effects, and emit enough telemetry to explain what happened.

This extension makes the same claim for **information**.

The load-bearing claim is:

> A workflow checkpoint is incomplete unless the runtime can also explain what information entered context, what was selected, what was consumed by the model, and what the workflow credited as influential in a decision.

This is not a vector database, RAG framework, knowledge-management platform, or observability platform. It is not trying to replace broad tracing/evaluation products such as LangSmith, Langfuse, Phoenix, or Braintrust. It does not trace every token, span, or tool call. It records the minimal context lineage needed to answer what information was mounted and credited inside a durable workflow.

The project deliberately starts below the knowledge-platform layer. It records the lifecycle of information artifacts inside workflow execution so a human reviewer can answer:

- What did the workflow know at this step?
- Where did that information come from?
- Which artifacts were mounted into the prompt?
- Which selected artifacts were credited as influential by the instrumented workflow?
- Can an operator inspect the context trail without querying SQLite tables?

### 0.0.1 Lineage Vocabulary

DurableFlow Context borrows the data-lineage mental model without adopting an OpenLineage dependency in v0.1.

| OpenLineage Concept | DurableFlow Context Analog |
|---------------------|----------------------------|
| Dataset | `InfoArtifact` |
| Job | workflow step |
| Run | workflow execution |
| Lineage event | `ContextLedgerEvent` plus `DecisionLineage` |

This vocabulary keeps the architecture legible to data-infrastructure readers while preserving the repo's local, SQLite-first implementation boundary.

### 0.1 MVP Cutline: v0.1 Context Ledger

The MVP is a deterministic extension of the existing inbox triage workflow.

MVP must include:

- artifact registration for incoming email, selected prior emails, calendar events, prompt payloads, and model responses
- artifact lifecycle events for `observed`, `selected`, and `consumed`
- system events for `decision_recorded` and `lineage_recorded`
- decision lineage from `triage_llm` and `draft_reply` outputs back to selected context artifacts, using explicit structured attribution only
- an audit CLI/read model that shows a workflow's context trail without exposing raw backend table names
- deterministic tests covering artifact registration, lifecycle events, decision records, lineage, crash/resume idempotency, and audit rendering

Deferred until after MVP:

- trust/freshness policy and upstream context blocking
- supersession/current-source resolution
- context replay and prompt replay
- context compaction and summary parent/child lineage
- OpenLineage export
- graph visualization beyond static Mermaid output
- vector search or embedding stores
- collaborative human knowledge-review workflows
- multi-tenant policy administration

The first demo must be:

> Run inbox triage. Open audit trace. See the exact artifacts selected, consumed, and credited as influential in the model decision.

---

## 1. Requirement & Narrative

### 1.1 What

Add a `context` extension to DurableFlow that tracks information artifacts as first-class workflow state.

The extension introduces:

- `InfoArtifact`: a registered piece of information, such as an incoming email, prior email, calendar event, tool output, prompt, or model response
- `ContextLedgerEvent`: an append-only event describing how an artifact moved through context
- `DecisionRecord`: a durable record of an LLM/model decision with prompt/response digests, token counts, and step linkage
- `DecisionLineage`: a junction record connecting a decision to the artifacts that influenced it
- `ContextLedger`: a small API for recording artifacts, lifecycle events, decisions, lineage, and audit summaries
- audit read models and CLI commands that answer "what information did this workflow use?"

The default integration instruments the existing inbox triage workflow. When `select_context` chooses prior messages and calendar entries, those artifacts are registered and marked `selected`. When `triage_llm` or `draft_reply` builds a prompt, the mounted artifacts are marked `consumed`. When the mock model returns explicit `influential_artifact_ids`, the extension records lineage from the decision to those artifacts. v0.1 does not infer influence from free text.

### 1.2 Why

Durable execution answers "did the process survive?" It does not fully answer "was the process operating on correct information?"

In agentic workflows, a technically successful run can still be wrong if the model relied on stale, poisoned, contradictory, or irrelevant context. This is the gap surfaced by the context research:

- execution state and information state are distinct
- context engineering selects and compacts information but rarely records the lifecycle of those operations
- knowledge management treats trusted operational knowledge as scarce infrastructure, not content decoration
- event sourcing and data lineage provide proven patterns for replay, audit, and root-cause analysis
- upstream context approval can prevent failures that downstream action approval cannot catch

The extension gives DurableFlow a concrete answer to the enterprise AI question Ashu Roy-style knowledge-system leaders tend to ask:

> Can the system show which knowledge was used and credited in this answer or action?

### 1.3 Who

**Primary persona -- backend/AI infrastructure engineer:** wants a small, inspectable implementation of context provenance and lineage that can be studied, tested, and extended.

**Secondary persona -- enterprise knowledge architect:** cares that AI workflows preserve lineage now and can grow into trust, freshness, and supersession controls later.

**Audit persona -- reviewer/operator:** opens a trace after a workflow and needs a plain-language explanation of what information was used and which decision it influenced.

### 1.4 Relationship to DurableFlow Core

Context is an additive extension. It MUST NOT change existing `WorkflowEngine` semantics or require existing workflows to adopt the ledger.

The extension MAY import:

- `WorkflowStore` for SQLite connection/path alignment
- `StepResult` for step output integration
- `TelemetryLogger` for structured event emission
- `ContextSelector` and `ContextItem` for default inbox triage instrumentation

The extension MUST keep all new persistence additive. Existing tests and demos must continue to pass if the context extension is not used.

---

## 2. Experience Semantics

### 2.1 Intent Mapping

**Business intent:** Make DurableFlow credible for enterprise agentic workflows where operational knowledge, auditability, and governance matter as much as crash recovery.

**Experience intent:** The reviewer should feel they are inspecting a trace of knowledge use, not spelunking a database. Success feels like: "I can see what the workflow saw and credited."

**Technical intent:** Preserve a deterministic mapping from workflow step to mounted context artifacts to model decisions. The system must be inspectable through SQLite and reproducible without network services.

### 2.2 Experience Semantics Template

#### WHO THEY ARE

Primary persona: AI infrastructure engineer or enterprise knowledge architect.
Core job: Decide whether an agentic workflow used the right information safely.
Technical proficiency: High, but the audit readout should not require internal table knowledge.

#### WHAT THEY BELIEVE THEY ARE DOING

"Reviewing the knowledge trail behind a workflow decision" -- not "querying context tables."

#### QUESTIONS THEY WAKE UP ASKING

- What did the workflow know before the model call?
- Where did that information come from?
- Which sources influenced the classification or draft?
- Can I inspect the context trail without querying tables?

#### EMOTIONAL CONTEXT

Skeptical, accountability-focused, and often time-constrained. Failure means approving an agentic system whose errors cannot be traced after the fact.

#### PRIMARY CONCEPTS

- Knowledge trail
- Context mounted for a step
- Decision influence
- Context audit trace

#### SECONDARY CONCEPTS

- SQLite table names
- foreign keys
- prompt payload hashes
- model response JSON
- token accounting rows

#### SUCCESS FEELS LIKE

"I can tell what information the workflow used and credited in this decision."

#### FAILURE FEELS LIKE

"The workflow completed, but I cannot tell what context the model saw or what it credited."

#### PRIMARY SCREEN

Context Audit Trace -- a CLI/read-model view for one workflow that lists each step, mounted artifacts, and decision lineage.

#### PRIMARY ACTION

Open the audit trace for review.

#### UBIQUITOUS LANGUAGE

| User Term | Technical Term (not shown as primary language) |
|-----------|-------------------------------------------------|
| Knowledge trail | `context_ledger_events` joined to `info_artifacts` |
| Mounted context | active artifacts consumed by a step prompt |
| Decision influence | `decision_lineage` relationship with influence type/score |
| Context audit trace | presentation view built from ledger, decision, and lineage rows |

---

## 3. Gherkin Scenarios

### 3.1 Behavioral Gherkin

```gherkin
Scenario: Golden path -- selected context is durably traced
  Given an inbox triage workflow with an incoming email and a corpus of prior emails and calendar events
  When the select_context step chooses artifacts for the token budget
  Then each selected artifact is registered in the context ledger
  And each artifact receives a selected event linked to workflow_id and step_name
  And the selected artifacts preserve source, content_digest, observed_at, token_count, and metadata

Scenario: LLM step consumes mounted context
  Given select_context has produced selected artifacts
  When triage_llm builds the prompt
  Then the prompt input artifacts receive consumed events for step triage_llm
  And a decision record is created with prompt_digest, response_digest, token usage, model_used, and cost
  And the decision record links to the DurableFlow step result

Scenario: Decision lineage records influence
  Given triage_llm classifies an email as action_required
  And the mock model response contains influential_artifact_ids ["email-042", "cal-003"]
  When the decision is saved
  Then decision_lineage links the decision to both artifacts
  And each linkage records influence_type explicit_model_attribution
  And selected artifacts absent from influential_artifact_ids are shown as selected but not influential

Scenario: Crash after context selection preserves ledger state
  Given select_context has registered selected artifacts
  And the process crashes before triage_llm starts
  When the engine resumes from the last checkpoint
  Then selected artifacts are not duplicated
  And triage_llm consumes the already registered artifact ids
  And the audit trace shows one selected event per artifact for the original step

Scenario: Workflow completes with context audit summary
  Given an inbox triage workflow completes
  When the operator asks for its context audit trace
  Then the trace lists each step in order
  And shows observed, selected, consumed, influential, and non-influential artifacts
  And summarizes selected_count, consumed_count, influential_count, and decision_count
```

### 3.2 Conceptual Gherkin

```gherkin
Scenario: Reviewer believes the decision is explainable
  Given a reviewer is skeptical of an action_required classification
  When they open the Context Audit Trace
  Then they see the incoming email, selected prior context, and two influential sources in plain language
  And they form the belief: "I can explain why the workflow classified this as action_required"

Scenario: Reviewer sees the boundary of the v0.1 claim
  Given a reviewer asks whether an artifact was stale or trusted
  When they open the v0.1 Context Audit Trace
  Then the trace states that trust and freshness policy are roadmap capabilities
  And the reviewer forms the belief: "this version proves lineage, not full knowledge governance"
```

---

## 4. Contracts

### 4.1 Domain Contract

Domain models live in `context/models.py`.

| Type | Fields | Purpose |
|------|--------|---------|
| `InfoArtifact` | `artifact_id`, `workflow_id`, `artifact_role`, `source`, `source_type`, `content_digest`, `content_ref`, `token_count`, `observed_at`, `metadata` | Catalogs information that can enter context |
| `ContextLedgerEvent` | `event_id`, `workflow_id`, `step_name`, `artifact_id \| None`, `event_type`, `event_scope`, `event_time`, `reason`, `metadata` | Append-only artifact lifecycle or system bookkeeping event |
| `DecisionRecord` | `decision_id`, `workflow_id`, `step_name`, `step_result_id`, `prompt_digest`, `response_digest`, `model_used`, `input_tokens`, `output_tokens`, `cost_usd`, `created_at` | Durable record of model decision |
| `DecisionLineage` | `decision_id`, `artifact_id`, `influence_type`, `influence_score`, `evidence_ref` | Links decision to source artifacts |

Allowed artifact roles:

- `source_artifact`: incoming email, prior email, calendar event, tool output, or other source information that may influence a model decision
- `prompt_artifact`: prompt payload digest/ref recorded for audit completeness
- `response_artifact`: model response digest/ref recorded for audit completeness

DecisionLineage links decisions to `source_artifact` rows only in v0.1. Prompt and response artifacts are recorded for audit completeness, but they are not eligible influence sources. "Prompt influenced decision" is tautological and MUST NOT appear as a lineage claim.

`content_ref` semantics:

- For fixture data, `content_ref` is a stable source identifier such as `mock_emails:email-042`.
- For local files, `content_ref` is a relative path within the repository or demo data directory.
- For external systems, `content_ref` is an opaque source ID, not a URL that requires network access.
- v0.1 stores `content_digest` and `content_ref` by default. Raw content storage is out of scope.
- `content` may be supplied to APIs for digest calculation only. It is never persisted in v0.1.

`DecisionLineage.evidence_ref` is a privacy-safe reference to structured attribution evidence. It MUST NOT store raw email snippets or prompt excerpts in v0.1.

Schema stance:

- v0.1 is an append-only ledger plus derived audit read models.
- Mutable current-state tables, such as trust state or supersession pointers, are roadmap work.
- The same real-world artifact appearing in multiple workflows receives separate v0.1 artifact rows. Cross-workflow identity and deduplication are deferred.

Allowed artifact lifecycle event values:

- `observed`
- `selected`
- `consumed`

Allowed system event values:

- `decision_recorded`
- `lineage_recorded`

Allowed event scope values:

- `artifact`: event describes an artifact lifecycle transition and MUST include `artifact_id`
- `system`: event describes ledger bookkeeping and MAY omit `artifact_id`

Allowed influence types:

- `explicit_model_attribution`
- `deterministic_fixture_attribution`

MVP influence attribution is deliberately strict:

| Influence Mode | v0.1 Status | Reliability |
|----------------|-------------|-------------|
| Explicit `influential_artifact_ids` emitted by mock model | Allowed | High |
| Deterministic fixture map from output to artifact IDs | Allowed | High |
| LLM self-reported influence from free text | Deferred | Low |
| Heuristic semantic matching | Deferred | Medium-low |

v0.1 MUST NOT infer influence from free-form model text.

### 4.2 API Contract

Implementation lives in `context/ledger.py`.

| Method | Signature | Behavior |
|--------|-----------|----------|
| `record_artifact` | `(workflow_id: str, artifact_role: str, source: str, source_type: str, content: str | None, content_ref: str | None, token_count: int, metadata: dict) -> InfoArtifact` | Computes digest from transient `content` when supplied, never persists raw content, and inserts or reuses artifact by `(workflow_id, artifact_role, content_digest, source)` |
| `record_event` | `(workflow_id: str, step_name: str, artifact_id: str | None, event_type: str, reason: str | None = None, metadata: dict | None = None) -> ContextLedgerEvent` | Appends artifact lifecycle or system event. System events may omit `artifact_id` when they describe decision bookkeeping |
| `record_decision` | `(workflow_id: str, step_name: str, step_result_id: str | None, prompt: str, response: str, model_used: str, input_tokens: int, output_tokens: int, cost_usd: float) -> DecisionRecord` | Saves prompt/response digests and model metadata |
| `record_lineage` | `(decision_id: str, artifact_id: str, influence_type: str, influence_score: float, evidence_ref: str | None = None) -> DecisionLineage` | Links a decision to an explicitly attributed `source_artifact` only |
| `audit_workflow` | `(workflow_id: str) -> ContextAudit` | Builds domain audit summary for presentation builder |

### 4.3 Presentation Contract

Although the extension has no web UI, the audit CLI is a user-facing surface. It MUST NOT print backend DTOs or raw table rows directly.

Presentation models live in `context/audit_view.py`.

| View Type | Fields | Purpose |
|-----------|--------|---------|
| `ContextAuditView` | `workflow_id`, `headline`, `lineage_summary`, `steps`, `claim_boundary_footer`, `roadmap_notice` | Top-level audit read model |
| `ContextAuditStepView` | `step_name`, `plain_status`, `mounted_context`, `decision_summary`, `notes` | Per-step user-facing summary |
| `ArtifactView` | `label`, `source_label`, `event_labels`, `influence_label`, `content_ref_label` | User-language artifact display |
| `DecisionView` | `label`, `model_label`, `cost_label`, `token_label`, `influential_sources` | User-language decision display |

Mandatory builder:

```python
def build_context_audit_view(audit: ContextAudit) -> ContextAuditView:
    ...
```

Renderer contract:

```python
def render_context_audit(view: ContextAuditView) -> str:
    ...
```

The renderer consumes `ContextAuditView` only. It MUST NOT import SQLite row types, `InfoArtifact`, `DecisionRecord`, or `DecisionLineage` directly.

The CLI renderer MUST print this footer verbatim:

```text
v0.1 audit boundary:
This trace shows selected, consumed, and explicitly credited artifacts.
It does not evaluate freshness, trust, contradiction, or policy compliance.
```

### 4.4 Runtime Traceability

Golden path for inbox triage with context ledger:

```text
examples/inbox_triage_demo.py
  -> WorkflowStore(db_path)
  -> ContextLedger.from_store(store)                         # context/ledger.py
  -> InboxTriageWorkflow(..., dependencies={"context_ledger": ledger})
  -> WorkflowEngine.execute(workflow_id)
       -> ingest_email_fn(...)
            -> ledger.record_artifact(artifact_role="source_artifact", source_type="incoming_email")
            -> ledger.record_event(event_type="observed")
            -> store.save_checkpoint(...)
       -> select_context_fn(...)
            -> ContextSelector.select(query, corpus, budget)
            -> for each selected ContextItem:
                 -> ledger.record_artifact(artifact_role="source_artifact", source_type=item.source_type)
                 -> ledger.record_event(event_type="selected")
            -> store.save_checkpoint(...)
       -> triage_llm_fn(...)
            -> for each selected artifact mounted into prompt:
                 -> ledger.record_event(event_type="consumed")
            -> ModelRouter.route(prompt, system, policy)
            -> ledger.record_artifact(artifact_role="prompt_artifact", source_type="prompt")
            -> ledger.record_artifact(artifact_role="response_artifact", source_type="model_response")
            -> ledger.record_decision(...)
            -> parse explicit influential_artifact_ids from mock response
            -> ledger.record_lineage(...)
            -> store.save_checkpoint(...)
       -> draft_reply_fn(...)
            -> repeat consume/decision/lineage recording
       -> approval_gate_fn(...)
       -> send_reply_fn(...)
  -> ledger.audit_workflow(workflow_id)
  -> build_context_audit_view(audit)
  -> render_context_audit(view)
```

---

## 5. Phased Implementation Plan

### Phase 1: Core Data Models & SQLite Schema

**Scope:** Add context extension package with domain models, schema initialization, and migrations.

**Files:**

- `context/__init__.py`
- `context/models.py`
- `context/schema.py`
- `context/ledger.py`

**Deliverables:**

- dataclasses listed in §4.1
- `ContextLedger` constructor accepting a SQLite path or `WorkflowStore`
- additive SQLite tables:
  - `context_artifacts`
  - `context_ledger_events`
  - `context_decisions`
  - `context_decision_lineage`
- idempotent schema creation with `CREATE TABLE IF NOT EXISTS`
- foreign keys to core workflows where possible without changing core schema

**Acceptance criteria:**

- [ ] Existing DurableFlow tests pass without using `ContextLedger`
- [ ] Context schema initializes on an existing DurableFlow SQLite database without dropping or altering core tables
- [ ] `record_artifact` deduplicates by workflow, artifact role, source, and digest
- [ ] `record_artifact` never persists raw `content`
- [ ] `record_event` is append-only
- [ ] artifact lifecycle, system event, artifact role, and influence enum values are validated before insert

### Phase 2: Context Ledger API and Explicit Lineage

**Scope:** Implement artifact lifecycle operations, decision records, and explicit lineage recording.

**Files:**

- `context/ledger.py`
- `context/lineage.py`

**Deliverables:**

- artifact registration and append-only lifecycle event recording
- decision records with prompt/response digests, model metadata, token counts, and cost
- lineage recording from explicit `influential_artifact_ids` or deterministic fixtures only
- validation that lineage artifact IDs were selected or consumed in the same workflow
- validation that lineage artifact IDs refer to `source_artifact` rows only
- audit summary query for observed, selected, consumed, and influential artifacts

**Acceptance criteria:**

- [ ] every model decision can be listed with model, token, and cost metadata
- [ ] lineage cannot be recorded for an artifact outside the workflow
- [ ] lineage cannot be recorded for prompt or response artifacts
- [ ] v0.1 rejects free-text influence inference
- [ ] selected-but-not-influential artifacts remain visible in audit output
- [ ] prompt/response digests persist without storing raw prompt or raw response by default

### Phase 3: Inbox Triage Instrumentation and Telemetry

**Scope:** Wire the extension into the existing inbox triage workflow while preserving current behavior when the extension is absent.

**Files:**

- `src/workflows.py`
- `src/context_selector.py`
- `src/telemetry.py`
- `examples/inbox_triage_context_demo.py`

**Deliverables:**

- optional `context_ledger` dependency in workflow step dependencies
- artifact registration for incoming email, prior emails, calendar events, prompts, and model responses
- prompt and response artifacts use `prompt_artifact` and `response_artifact` roles
- selected/consumed events plus explicit lineage records for `select_context`, `triage_llm`, and `draft_reply`
- telemetry events:
  - `context_artifact_observed`
  - `context_selected`
  - `context_consumed`
  - `context_decision_recorded`
  - `context_lineage_recorded`
- deterministic context demo using mock data and mock providers

**Acceptance criteria:**

- [ ] inbox triage behavior and statuses are unchanged when no ledger is provided
- [ ] context demo runs without API keys or network
- [ ] crash/resume does not duplicate selected artifact rows
- [ ] telemetry JSON lines include workflow_id, step_name, artifact_id or decision_id, and event_type
- [ ] model-router cost accounting remains the source of truth for decision cost

### Phase 4: Audit Read Model and CLI Presentation

**Scope:** Provide a semantic audit surface over the domain ledger.

**Files:**

- `context/audit.py`
- `context/audit_view.py`
- `context/cli.py`
- `examples/context_audit_demo.py`

**Deliverables:**

- `ContextAudit` domain summary from `ContextLedger.audit_workflow()`
- `build_context_audit_view(audit) -> ContextAuditView`
- `render_context_audit(view) -> str`
- CLI commands:
  - `python -m context.cli audit --db <path> --workflow-id <id>`
- no raw table names in default CLI output

**Acceptance criteria:**

- [ ] renderer accepts `ContextAuditView` only
- [ ] output uses ubiquitous language from §2.2
- [ ] audit view lists observed, selected, consumed, influential, and non-influential artifacts
- [ ] audit output includes the mandatory v0.1 claim-boundary footer
- [ ] audit output states that trust policy, supersession, and replay are roadmap capabilities
- [ ] raw prompt, raw response, and raw artifact content are omitted by default

### Phase 5: Tests, Documentation, and Example Trace

**Scope:** Prove the extension is deterministic, documented, and reviewable.

**Files:**

- `tests/test_context_ledger.py`
- `tests/test_context_lineage.py`
- `tests/test_context_audit_view.py`
- `README.md`
- `docs/context-extension.md`

**Deliverables:**

- focused unit tests for models, schema, lineage, and view builder
- integration test for inbox triage context demo
- README section positioning context durability as separate from execution durability
- docs page with schema, example audit trace, and limitations

**Acceptance criteria:**

- [ ] all context tests pass with `pytest==8.4.2`
- [ ] existing tests still pass
- [ ] docs include a before/after explanation: execution trace alone versus execution + context trace
- [ ] docs include the OpenLineage analogy table from §0.0.1
- [ ] docs include the "not an observability platform" boundary
- [ ] docs clearly state privacy limits and raw-content handling
- [ ] no new required external dependency is introduced

---

## 6. Entry Gates

Before implementation begins, the following must pass:

### 6.1 Specification Completeness

- [ ] Domain models are fully defined in §4.1
- [ ] API contracts are fully defined in §4.2
- [ ] Presentation/read-model contracts are fully defined in §4.3
- [ ] Behavioral and conceptual Gherkin scenarios cover success, failure, and audit paths
- [ ] Dependencies are listed and pinned
- [ ] No implementation requirement depends on an unchosen external service
- [ ] All trust, supersession, compaction, and replay requirements are marked roadmap, not v0.1
- [ ] Artifact lifecycle events and system bookkeeping events are modeled separately

### 6.2 Cross-Reference Consistency

- [ ] Requirement narrative matches the phased plan
- [ ] Test plan covers every acceptance criterion
- [ ] Conceptual Gherkin states map to audit view fields
- [ ] Runtime traceability lists every golden-path method call and import

### 6.3 Implementation Readiness

- [ ] Required files and module names are specified
- [ ] SQLite tables are additive and isolated from core DurableFlow schema changes
- [ ] Extension behavior is optional for existing workflows
- [ ] Renderer consumes presentation view types only
- [ ] Scenario catalog covers golden path, explicit influence attribution, crash/resume idempotency, and audit output

---

## 7. Test Plan

| Test ID | File | Scenario | Assertions |
|---------|------|----------|------------|
| CTX-LED-001 | `tests/test_context_ledger.py` | artifact registration | duplicate source/digest/workflow reuses artifact |
| CTX-LED-002 | `tests/test_context_ledger.py` | event append | lifecycle events are append-only and ordered |
| CTX-LED-003 | `tests/test_context_ledger.py` | enum validation | invalid artifact role, lifecycle, system event, or influence values are rejected |
| CTX-LED-004 | `tests/test_context_ledger.py` | transient content privacy | supplied content computes digest but is not persisted |
| CTX-DEC-001 | `tests/test_context_ledger.py` | decision record | prompt/response digests and token/cost data persist |
| CTX-LIN-001 | `tests/test_context_lineage.py` | explicit influence lineage | decision links to explicitly attributed artifacts |
| CTX-LIN-002 | `tests/test_context_lineage.py` | free-text inference rejected | lineage API rejects unsupported influence mode |
| CTX-LIN-003 | `tests/test_context_lineage.py` | foreign artifact rejected | lineage cannot reference artifact outside workflow |
| CTX-LIN-004 | `tests/test_context_lineage.py` | prompt/response lineage rejected | lineage cannot reference prompt or response artifacts |
| CTX-RES-001 | `tests/test_context_ledger.py` | crash after selection | resume does not duplicate artifacts or selected events |
| CTX-AUD-001 | `tests/test_context_audit_view.py` | audit builder | primary concepts map to view fields |
| CTX-AUD-002 | `tests/test_context_audit_view.py` | renderer imports | renderer consumes only `ContextAuditView` |
| CTX-INT-001 | `tests/test_context_ledger.py` | inbox context demo | selected/consumed events and lineage records are present |

### Semantic Fitness Functions

| Test ID | Cognitive Scenario | Invariant Assertion | Pass Criteria |
|---------|--------------------|---------------------|---------------|
| SEM-CTX-001 | Reviewer asks what the workflow knew | Audit headline identifies selected, consumed, and influential context counts | Manual review of CLI output |
| SEM-CTX-002 | Reviewer asks for trust status | Audit output states trust policy is roadmap, not implemented | Snapshot test |
| SEM-CTX-003 | Engineer debugs model output | Audit output lists selected, consumed, and influential artifacts for the decision | Automated test |
| SEM-CTX-004 | Reviewer inspects influence | Influential artifacts are visually/textually separated from ignored artifacts | Snapshot test of renderer output |
| SEM-CTX-005 | Raw content is sensitive | Default audit command omits raw prompt, response, and artifact content | Automated CLI test |
| SEM-CTX-006 | Reviewer calibrates trust in the trace | CLI prints the mandatory v0.1 audit boundary footer | Snapshot test |

---

## 8. Exit Gates

Before a phase is marked COMPLETE:

### 8.1 Implementation Verification

- [ ] Read the implemented code for each claimed capability
- [ ] Verify schema is additive and idempotent
- [ ] Verify no core DurableFlow behavior changes when the extension is absent
- [ ] Verify context events are written at the claimed steps
- [ ] Verify influence is recorded only from explicit structured attribution or deterministic fixtures
- [ ] Verify lineage points only to `source_artifact` rows
- [ ] Verify prompt and response artifacts are recorded but never treated as influence sources

### 8.2 Acceptance Criteria Checklist

- [ ] All phase acceptance criteria are checked off
- [ ] Each checked item has a corresponding test
- [ ] Known bugs are documented before status changes

### 8.3 Dependency Verification

- [ ] No new required external dependencies
- [ ] Optional dependencies remain pinned
- [ ] Tests run with local SQLite and mock providers

### 8.4 Semantic Verification

- [ ] CLI renderer accepts presentation view types only
- [ ] Audit output uses ubiquitous language
- [ ] No raw SQLite table or column names appear in default CLI output
- [ ] Mandatory claim-boundary footer appears in CLI output
- [ ] Scenario fixtures cover all conceptual outcomes
- [ ] Runtime trace remains `workflow -> context ledger -> model decision -> audit view -> renderer`

---

## 9. Pre-Mortem Analysis

### Failure: Ledger Becomes a Logging Dump

Risk: The extension records many rows but fails to answer which information influenced a decision.

Mitigation: `DecisionLineage` is mandatory for model decisions, and tests assert influential versus non-influential selected artifacts.

### Failure: Influence Is Overclaimed

Risk: The extension infers influence from free text and presents a weak heuristic as fact.

Mitigation: v0.1 accepts only explicit `influential_artifact_ids` from the mock model or deterministic fixture maps. LLM self-reporting from free text and semantic matching move to roadmap.

### Failure: Context Policy Only Warns

Risk: Stale or blocked artifacts are flagged but still mounted into prompts.

Mitigation: Trust and blocking policy are not v0.1 completion criteria. They are roadmap work and must not be claimed as implemented until a structured policy API proves blocked artifacts are not consumed.

### Failure: Audit Surface Leaks Implementation Terms

Risk: CLI output prints table names, hashes, and foreign keys as the primary experience.

Mitigation: `build_context_audit_view()` is required; renderer cannot consume domain DTOs directly.

### Failure: Privacy Risk from Storing Raw Content

Risk: The ledger becomes a second ungoverned copy of sensitive emails and tool outputs.

Mitigation: Store content digests and refs by default. Raw content is optional, local-only, and excluded from default audit output. Replay features must preserve the same default.

### Failure: Extension Coupling Breaks Core DurableFlow

Risk: Existing workflows must change to accommodate context tracking.

Mitigation: All ledger use is optional through dependencies; additive tables only; existing test suite remains an exit gate.

### Failure: Replay Claims Too Much

Risk: The extension claims deterministic replay even though LLM output remains probabilistic.

Mitigation: v0.1 does not ship rehydration. Roadmap distinguishes context replay from prompt replay; prompt replay requires exact prompt assembly and digest verification.

---

## 10. Remediation & Acceptance

Accepted recommendations:

- Implement context durability as a small ledger first, not a full knowledge platform
- Treat trust/freshness as upstream policy in v0.2, not v0.1
- Keep raw content out of the default persistence path
- Require decision lineage for each model decision, using explicit structured attribution only
- Require a presentation builder for audit output so user mental models are preserved
- Make the inbox triage demo the first integration target because it already has context selection, model decisions, approvals, and telemetry

Deferred items:

- Trust policy is deferred to v0.2
- Supersession/current-source resolution is deferred to v0.2
- Context replay and prompt replay are deferred to v0.3
- Compaction and summary parent/child lineage are deferred to v0.3
- Context governance and upstream approval queues are deferred to v0.4
- OpenLineage export is deferred until the internal schema is stable
- Graph visualization is deferred until the audit read model proves useful
- Human knowledge-review queues are deferred because approval workflows already exist at the action layer and context approval needs a separate product design
- Vector search integration is deferred because the extension's purpose is provenance and lineage, not retrieval quality

---

## 11. Roadmap

The following items are intentionally preserved but moved out of the v0.1 implementation scope.

### v0.2: Trust Policy

Adds input-side trust and freshness governance. Feeds **Context Provenance Quality** (§14.4): once trust state exists, the audit surface can answer not only "was this context used?" but "should it have been used?" via derived Context Quality Scores.

Scope:

- `InfoTrustState` current-state read model
- trust/freshness policy API
- stale, unverified, blocked, and superseded labels
- source-type policy such as "calendar context must be fresh"
- telemetry event `context_policy_block`

Roadmap scenarios:

```gherkin
Scenario: Stale context is blocked by policy
  Given a calendar event artifact has valid_until earlier than the workflow start time
  And the context policy requires fresh calendar context
  When triage_llm attempts to consume the artifact
  Then the ledger records a trust check failure
  And the artifact is not mounted into the prompt
  And telemetry emits a context_policy_block event

Scenario: Untrusted context is allowed with warning under permissive policy
  Given a prior email artifact has trust status unverified
  And the context policy permits unverified prior emails with warnings
  When draft_reply consumes the artifact
  Then the artifact is mounted
  And the audit trace shows an unverified source warning
  And the decision record includes context_warnings
```

Exit gate for v0.2:

- [ ] blocked artifacts have no `consumed` event
- [ ] warnings appear in audit output in user language
- [ ] trust state is explicitly modeled as current state derived from append-only events, or the spec is revised to justify mutable state

### v0.2: Supersession

Adds current-source resolution without changing the v0.1 workflow-local artifact identity model.

Scope:

- `superseded_by_artifact_id`
- current artifact resolver
- audit labels for superseded sources
- optional cross-workflow source identity map

Roadmap scenario:

```gherkin
Scenario: Superseded artifact is replaced before model use
  Given artifact email-042-v1 is superseded by email-042-v2
  When select_context chooses email-042-v1 by digest
  Then the ledger resolves the current artifact to email-042-v2
  And records a superseded event for email-042-v1
  And records selected and consumed events only for email-042-v2
```

### v0.3: Context Replay and Prompt Replay

Renames and splits the original rehydration concept.

Definitions:

- **Context replay:** reconstructs the artifact list, order, source labels, content refs, and metadata that were mounted for a step.
- **Prompt replay:** reconstructs the exact prompt string and verifies it against `DecisionRecord.prompt_digest`.

v0.3 starts with context replay. Prompt replay is optional and only valid for instrumented workflows where prompt assembly, ordering, separators, system prompt inclusion, and omission behavior are all deterministic.

Roadmap scenarios:

```gherkin
Scenario: Context replay reconstructs mounted artifact metadata
  Given a completed triage_llm decision
  When the operator runs context replay for that workflow and step
  Then the extension reconstructs the ordered mounted artifact list
  And raw content is omitted unless the caller explicitly asks for local unsafe debug output

Scenario: Prompt replay verifies exact prompt digest
  Given an instrumented workflow with deterministic prompt assembly
  When the operator runs prompt replay for a decision
  Then the reconstructed prompt digest matches the stored decision prompt_digest
```

### v0.3: Context Compaction

Adds parent-child lineage for summaries created from larger context sets.

Scope:

- summary artifacts
- `parent_artifact_ids`
- `evicted` and `compacted` lifecycle events
- audit labels for compacted context

Roadmap scenario:

```gherkin
Scenario: Context compaction records information loss
  Given selected artifacts exceed the prompt token budget
  When the context extension compacts older artifacts into a summary artifact
  Then the original artifacts receive evicted events with reason compaction
  And the summary artifact is registered with parent_artifact_ids
  And the audit trace marks the summary as compacted context
```

### v0.4: Context Governance

Adds human review and upstream approval workflows for knowledge inputs.

Scope:

- review queue for context artifacts
- human validation events
- policy-specific approval gates before model consumption
- domain-specific governance workflows

This is intentionally later than v0.1 because it is product design, not just ledger plumbing.

### Later: Exports and Retrieval Systems

Deferred integrations:

- OpenLineage/Marquez export
- graph visualization from ledger/read models
- vector search or embedding-backed retrieval
- multi-tenant policy administration

These remain downstream of the core ledger because the first invariant must be local, deterministic, and inspectable.

---

## 12. Declaration Standards

### 12.1 Status Definitions

- **DRAFT:** Spec written; entry gates not yet evaluated
- **READY:** Entry gates passed; implementation may begin
- **IN_PROGRESS:** Implementation underway
- **PARTIAL:** Core ledger exists but some v0.1 lineage or audit gaps remain
- **COMPLETE:** All exit gates passed and tests cover acceptance criteria
- **DEFERRED:** Explicitly postponed outside MVP

### 12.2 Prohibited Completion Claims

Do not mark this extension COMPLETE if:

- context events are recorded but decision lineage is absent
- influence is inferred from free text in v0.1
- roadmap items are implied as implemented
- audit CLI prints raw database rows as its primary surface
- existing DurableFlow tests fail
- raw content is stored by default without an explicit opt-in path

### 12.3 Code Review Gates

Implementer self-review must answer:

- [ ] Are all new imports used?
- [ ] Are enum values validated at the boundary?
- [ ] Can existing workflows run without constructing `ContextLedger`?
- [ ] Does each model decision write a decision record and lineage?
- [ ] Is influence accepted only from explicit structured attribution or deterministic fixtures?
- [ ] Does default audit output avoid raw content?

Spec compliance review must verify:

- [ ] Every Gherkin scenario has a test or explicit deferral
- [ ] Domain, presentation, and render contracts are implemented as specified
- [ ] No accepted risk is claimed as solved
- [ ] No TODO comments exist for claimed MVP capabilities

---

## 13. README Positioning Draft

DurableFlow tracks more than whether a workflow completed. With the Context extension, it can also track what information the workflow used.

Execution durability answers:

> Did the workflow survive crashes, retries, approval pauses, and side effects?

Context durability answers:

> What did the workflow know, where did that knowledge come from, and which sources influenced the model's decision?

The v0.1 extension adds a local SQLite context ledger for artifacts such as emails, calendar events, tool outputs, prompts, and model responses. Each artifact can be observed, selected, consumed, and linked to a decision through explicit lineage. The result is an audit trace that shows which context was selected, which context was mounted, and which artifacts the instrumented model credited as influential.

This is intentionally small. It is not a knowledge-management product. It is the missing operational primitive between "we selected some context" and "we can prove which information the workflow used and credited." Trust policy, supersession, compaction, and replay are roadmap layers built on this ledger.

---

## 14. Next Evolution: Assembly Lineage

**Status:** DRAFT — forward specification. Does not modify v0.1 completion criteria.
**Applies to:** Post-v0.1 evolution. Builds on the implemented ledger in §0–§13 without replacing them.

### 14.1 The Missing Primitive

v0.1 proves that agentic workflows need durable information lineage. The v0.1 lifecycle is:

```text
observed → selected → consumed → influential
```

This leaves a blind spot. When a workflow starts with 500 artifacts and selects 9, the ledger records that 9 were selected and consumed. It does not record:

- What retrieval method produced the candidate set?
- What were the candidates that were NOT selected?
- What scores and ranks determined selection?
- Why was artifact A chosen over artifact B?

The question "why was this artifact selected while others were not?" cannot be answered from v0.1 events alone.

The missing primitive is **assembly lineage** — durable events that record how candidate information competed for limited context budget before model consumption.

The extended lifecycle:

```text
observed → retrieved → {selected, rejected} → consumed → influential
```

`selected` and `rejected` are parallel terminal outcomes, not sequential events. An artifact retrieved from the candidate pool is either selected for the active context set or explicitly rejected with a reason.

This is not a platform feature. It is another set of durable events in the same lineage model that v0.1 established.

### 14.2 Assembly Lineage Events

**New lifecycle event types:**

| Event | Meaning |
|-------|---------|
| `retrieved` | Artifact returned by a retrieval step (search, index lookup, memory fetch) |
| `rejected` | Artifact retrieved but explicitly excluded from selection |

These extend the v0.1 lifecycle without replacing it:

```text
observed → retrieved → {selected, rejected} → consumed → influential
```

**Event metadata:**

`retrieved` and `rejected` events SHOULD carry optional metadata:

- `retrieval_method` — e.g., `bm25`, `hybrid`, `memory_lookup`, `deterministic_fixture`
- `retrieval_score` — numeric score from the retrieval method
- `rank_position` — ordinal position in ranked results
- `rejection_reason` — why the artifact was not selected (e.g., `token_budget`, `low_score`, `duplicate`)

Most retrieval systems combine retrieval and ranking in a single operation. If a future workflow implements separate reranking, a `reranked` event can be added then. v0.2 does not require it.

**Event-sourced modeling:**

The extension remains event-sourced. Retrieval metadata is stored in `ContextLedgerEvent.metadata`:

```python
ContextLedgerEvent(
    event_type="retrieved",
    artifact_id="email-042",
    metadata={
        "retrieval_method": "bm25",
        "retrieval_score": 0.82,
        "rank_position": 4
    }
)

ContextLedgerEvent(
    event_type="rejected",
    artifact_id="email-019",
    metadata={
        "rejection_reason": "token_budget"
    }
)
```

Separate `RetrievalRecord` or `RetrievalCandidate` tables are NOT required unless implementation pressure proves they are necessary. The event-sourced model is sufficient.

**Audit trace additions:**

The `ContextAudit` summary MUST include:

- `observed_count` — total artifacts that entered the workflow's information universe
- `retrieved_count` — artifacts returned by retrieval
- `selected_count` — artifacts chosen for the active context set
- `rejected_count` — artifacts retrieved but not selected

**Gherkin:**

```gherkin
Scenario: Assembly pipeline is durably traced
  Given a corpus of 500 prior emails and calendar events
  When select_context retrieves 37 candidates and selects 9
  Then each retrieved artifact receives a retrieved event with retrieval_method and score
  And each rejected candidate receives a rejected event with rejection_reason
  And the audit trace shows observed_count=500, retrieved_count=37, selected_count=9, rejected_count=28
  And the reviewer can inspect retrieval scores, ranks, and rejection reasons
```

### 14.3 Supersession

Supersession is already preserved in §11 v0.2. This evolution reaffirms it as a primitive.

When artifact `email-042-v1` is superseded by `email-042-v2`, the ledger records:

- `superseded_by_artifact_id` on `email-042-v1`
- `superseded` lifecycle event on `email-042-v1`

The audit trace shows superseded artifacts with a clear label. Supersession resolution is a read-mode operation over these events — not a separate service.

### 14.4 Context Replay

Context replay is already preserved in §11 v0.3. With assembly lineage, replay reconstructs:

- The ordered retrieved artifact list with retrieval_method, score, and rank_position
- The selected set
- The rejected set with rejection_reason
- The consumed set (what was mounted into the prompt)
- The influential set (what the decision credited)

Replay is a read-mode operation over durable events. It does not require storing raw prompts or responses by default.

**Gherkin:**

```gherkin
Scenario: Context replay reconstructs the assembly pipeline
  Given a completed triage_llm decision with assembly lineage
  When the operator requests context replay for that workflow and step
  Then the extension reconstructs the retrieved, selected, and rejected artifact lists
  And shows retrieval_method, score, and rank_position for each retrieved artifact
  And shows rejection_reason for each rejected artifact
  And omits raw content unless the caller explicitly requests unsafe debug output
```

### 14.5 Revised Positioning

The v0.1 claim remains valid:

> A workflow checkpoint is incomplete unless the runtime can also explain what information entered context, what was selected, what was consumed by the model, and what the workflow credited as influential in a decision.

Assembly lineage extends this claim:

> A workflow checkpoint is incomplete unless the runtime can also explain how candidate information competed for limited context budget and why some artifacts were selected while others were not.

This is not "context infrastructure." It is the upstream primitive that makes infrastructure possible. Observability platforms can build on these events. DurableFlow provides the events.

The README positioning becomes:

> v0.1 proves information lineage. Assembly lineage extends lineage one step upstream. Together, they provide the minimal durable surface for asking "what information did the workflow use, and how did it get there?"

### 14.6 Evolution Exit Gates

Before claiming **full** assembly lineage is implemented (§14.3–§14.4 included):

- [x] `retrieved` and `rejected` event types are valid `event_type` values — verified: `context/ledger.py` `ARTIFACT_EVENTS`; `test_ctx_led_assembly_001`–`011`
- [x] retrieval metadata (method, score, rank, rejection_reason) appears in audit output — verified: `context/audit_view.py` renderer; `test_ctx_audit_assembly_004_renderer_shows_visible_evidence`
- [x] audit trace exposes retrieval scores, ranks, and rejection reasons sufficient to inspect why artifact A was preferred over artifact B — verified: `examples/inbox_triage_context_demo.py` shows per-artifact `Retrieval:` and `Rejected context:` with `Reason:`
- [x] existing v0.1 workflows continue to work without retrieval instrumentation — verified: `test_ctx_led_assembly_050_backward_compatibility_v01`
- [ ] replay reconstructs retrieved, selected, and rejected sets from events — deferred: §14.4 / §11 v0.3
- [ ] superseded artifacts are labeled in the audit trace — deferred: §14.3 / design doc

For the **end-to-end demo minimum**, see §14.8. Ledger-only delivery is tracked in §14.7.

The spec does NOT claim:

- Context quality scores
- Retrieval experiment frameworks
- Evaluation dashboards
- Memory lifecycle management

Those are platform features that can be built on top of these primitives.

### 14.7 v0.2a Implementation Status (June 2026)

**Ledger primitives (complete):**

- [x] `retrieved` and `rejected` event types in `ARTIFACT_EVENTS`
- [x] Metadata validation: required keys, unknown keys, type constraints — including `metadata=None`/`{}` rejection
- [x] Aggregate audit counts: `observed_count`, `retrieved_count`, `selected_count`, `rejected_count` in `assembly_summary`
- [x] Backward compatibility without retrieval instrumentation

**End-to-end demo (complete — see §14.8):**

- [x] Workflow instrumentation in `select_context`
- [x] Per-artifact retrieval metadata in audit renderer
- [x] Non-zero rejected count in demo with visible rejection reasons

**Remaining for full §14 completion (§14.6 gates still open):**

- [ ] Replay reconstruction of retrieved, selected, and rejected sets
- [ ] Superseded artifact labeling in audit trace

**Deferred (per design doc — not required for the demo minimum):**

The design document (`docs/superpowers/specs/2025-01-31-assembly-lineage-design.md`) explicitly deferred:
- Superseded event type and resolution (future pass)
- Current-state read model (future pass)
- Retrieval table normalization (future pass)

### 14.8 End-to-End Demo Exit Gates (June 2026)

Before claiming assembly lineage is **visibly demonstrated** (does not require §14.3 supersession or §14.4 replay):

- [x] `select_context` emits `retrieved` events with `retrieval_method`, `retrieval_score`, `rank_position` — verified: `src/workflows.py`; demo output
- [x] `select_context` emits `rejected` events with `rejection_reason` and retrieval metadata — verified: `src/workflows.py`; demo output
- [x] Audit renderer shows per-artifact retrieval detail (`Retrieval: method/score/rank`) for selected artifacts — verified: `test_ctx_audit_assembly_004_renderer_shows_visible_evidence`
- [x] Audit renderer shows `Rejected context:` with `Reason:` for rejected artifacts — verified: same test; demo output
- [x] Demo produces non-zero `rejected_count` — verified: `python examples/inbox_triage_context_demo.py` → `Assembly: 64 observed, 59 retrieved, 11 selected, 48 rejected`
- [x] `context/README.md` example matches captured demo output (counts and format, not hand-written fiction) — verified: README cites `wf-context-demo` counts and `python examples/inbox_triage_context_demo.py`
- [x] Tests cover assembly renderer output — verified: `test_ctx_audit_assembly_004_renderer_shows_visible_evidence`, `test_assembly_lineage_tracks_retrieved_and_rejected`

**Demo command:**

```bash
python examples/inbox_triage_context_demo.py
```

**Evidence boundary once §14.8 is complete:**

The project may state that context lineage and assembly tracing are visibly demonstrated for the inbox triage workflow: retrieval, selection, rejection, model consumption, and decision influence are auditable through local SQLite-backed traces with per-artifact scores, ranks, and rejection reasons.

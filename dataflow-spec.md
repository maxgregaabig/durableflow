# Specification: DurableFlow DataFlow

**Status:** DRAFT
**Extension level:** Peer extension above DurableFlow core and complementary to `/context`.
**Author:** Marcos Polanco
**Created:** 2026-06-23
**Repository:** `durableflow`
**Extends:** `context/context-spec.md`
**Applies:** `process/spec-policy.md`, `process/semantics-policy.md`
**Dependency policy:** Core implementation remains Python standard library only. Optional runtime dependency: `pydantic>=2.0` for enhanced validation. Optional development dependency: `pytest==8.4.2`.
**Visibility:** Private implementation guide. Public artifacts are repo docs, examples, tests, and audit traces.
**Package:** `dataflow`

---

## 0. Positioning Note

`context/context-spec.md` makes information lineage durable:

```text
observed -> retrieved -> {selected, rejected} -> consumed -> influential
```

That answers:

- What information entered the workflow?
- What was searched, selected, rejected, mounted, and credited?
- Can an operator audit the knowledge trail behind a decision?

This proposal extends that foundation from **context lineage** to **dataflow lineage**.

The load-bearing claim is:

> An agentic workflow is a typed dataflow transformation graph. A durable runtime should let a designer declare the data DAG first, attach computation to nodes, and inspect how typed data products flowed through the run.

DurableFlow already checkpoints execution. `/context` records information artifacts around prompts and decisions. DataFlow adds the missing design surface:

- typed data artifacts as first-class workflow design objects
- step contracts that declare consumed and produced data types
- a dataflow graph that records actual runtime materializations
- read models that show the data DAG, not just the execution log
- validation gates that catch mismatched data before agent computation runs

This is not a replacement for LangGraph, Dagster, dbt, OpenLineage, or a full visual workflow builder. It is a local, SQLite-first primitive for treating agentic runs as typed transformation graphs.

The first demo should be:

> Design inbox triage as a data DAG. Attach existing computation to each node. Run the workflow. Open a dataflow audit and see typed data products flowing from incoming email, to selected context, to triage decision, to draft reply, to approval, to sent reply.

---

## 1. Relationship to `/context`

`/context` tracks information used by model decisions.

DataFlow tracks the typed data products created, consumed, and transformed by workflow steps.

They are complementary:

| Concern | `/context` | DataFlow |
|---------|------------|-------------------|
| Primary question | What information did the model see and credit? | What typed data flowed through the workflow? |
| Main unit | `InfoArtifact` | `DataArtifact` |
| Main event | `ContextLedgerEvent` | `DataflowEvent` |
| Main edge | `DecisionLineage` | `DataDependency` |
| Main surface | Context Audit Trace | Dataflow Graph Audit |
| Failure caught | Unknown/stale/irrelevant context use | Invalid/missing/miswired data transformation |

DataFlow may reference context artifacts when context data becomes a formal input or output of a step. For example, `SelectedContextSet` can be both:

- a data artifact produced by `select_context`
- a set of context ledger artifacts with retrieved, selected, and rejected events

The systems stay decoupled:

- DataFlow MUST NOT require `/context` to be enabled.
- `/context` MUST NOT require DataFlow to be enabled.
- When both are enabled, read models cross-link through explicit references only.

---

## 2. Requirement & Narrative

### 2.1 What

Add a `dataflow` extension to DurableFlow that lets a workflow declare a typed data DAG and record runtime data materializations against that DAG.

The extension introduces:

- `DataTypeSpec`: a named contract for a data shape, schema version, semantic meaning, and validation rules
- `StepContract`: a declaration of the data types a workflow step consumes and produces
- `DataflowSpec`: the design-time data DAG for a workflow
- `DataArtifact`: a runtime materialization of a typed data product
- `DataDependency`: a lineage edge from input artifact to output artifact
- `DataflowEvent`: an append-only event describing validation, materialization, consumption, and transformation
- `DataflowLedger`: API for registering specs, validating artifacts, recording dependencies, and building graph read models
- `DataflowGraphView`: audit/read model showing the designed DAG and actual run path

### 2.2 Why

Agentic workflows are usually described as control flow: steps, tools, model calls, branches, approvals, and side effects.

That is incomplete. A reliable agentic workflow also has data flow:

- What data type enters this step?
- What computation transforms it?
- What data type leaves the step?
- Which downstream steps depend on that output?
- Did runtime data match the declared contract?
- Which data products led to the final action?

The design insight is:

> Agent nodes are computations attached to a data DAG. The data DAG should be visible before the workflow runs and auditable after it runs.

This borrows proven data engineering ideas: typed assets, transformation DAGs, lineage, contracts, validation, materialization metadata, and impact analysis.

### 2.3 Who

**Primary persona -- workflow designer:** wants to sketch the data products and dependencies first, then attach Python functions, LLM calls, tools, or approval gates as computation nodes.

**Secondary persona -- backend/AI infrastructure engineer:** wants step contracts, validation, lineage, replay boundaries, and testable data flow.

**Audit persona -- reviewer/operator:** wants to inspect what data products led to a model decision or external side effect without reading code or SQLite tables.

---

## 3. Experience Semantics

### 3.1 Intent Mapping

**Business intent:** Make DurableFlow credible for production agent workflows where data dependencies, contracts, and auditability matter as much as execution durability.

**Experience intent:** The designer should feel they are designing a typed data flow with agent computation attached, not wiring an opaque sequence of prompts.

**Technical intent:** Preserve a deterministic mapping from declared step contracts to runtime data artifacts and lineage edges.

### 3.2 Ubiquitous Language

| User Term | Technical Term |
|-----------|----------------|
| Data DAG | `DataflowSpec` plus `StepContract` dependencies |
| Data product | `DataArtifact` |
| Data type | `DataTypeSpec` |
| Agent node | workflow step with attached computation and a `StepContract` |
| Transformation | step execution that consumes input artifacts and produces output artifacts |
| Dataflow run | actual path and data materializations for one workflow run |
| Data lineage | `DataDependency` edges between artifacts |
| Dataflow audit | `DataflowGraphView` rendered for a workflow run |

### 3.3 Success Feels Like

"I can design the data flow first, attach agent computation to each node, and later inspect the exact typed data products that led to the final result."

### 3.4 Failure Feels Like

"The workflow ran, but I cannot tell what data type each node expected, what it produced, or how the final output was composed from earlier outputs."

---

## 4. Conceptual Model

### 4.1 Design-Time DAG

A workflow can declare a data DAG before runtime:

```text
IncomingEmail
  -> ContextQuery
  -> SelectedContextSet
  -> TriageDecision
  -> DraftReply
  -> ApprovalDecision
  -> SentReplyReceipt
```

Each edge represents a data dependency. Each node has:

- a stable data type name
- a schema version
- a semantic description
- optional validation rules
- one or more producing steps
- zero or more consuming steps

Computation attaches to the graph:

```text
Data node: SelectedContextSet
Producer computation: select_context_fn
Inputs: IncomingEmail, PriorEmailCorpus, CalendarEventCorpus
Output: SelectedContextSet
```

### 4.2 Runtime Dataflow

Runtime does not merely say `select_context` completed. It records:

- which `DataArtifact` rows were consumed
- which output `DataArtifact` rows were materialized
- whether each artifact passed validation
- which input artifacts each output artifact depends on
- which branch of the designed graph actually executed

### 4.3 Data vs Context

Context artifacts are information mounted for a model. Data artifacts are typed products in the workflow graph.

Sometimes they overlap:

- `IncomingEmail` is a data artifact and may also be a context source artifact.
- `SelectedContextSet` is a data artifact and points to selected context artifact IDs.
- `TriageDecision` is a data artifact and may point to a `/context` `DecisionRecord`.

Cross-linking is explicit through `metadata` references, not hidden coupling:

```python
# SelectedContextSet referencing context artifacts
DataArtifact(
    artifact_id="df-001",
    workflow_id="wf-inbox-123",
    type_name="SelectedContextSet",
    type_version="1",
    producer_step="select_context",
    content_digest="abc123...",
    content_ref="select_context:wf-inbox-123:select_context",
    validation_status="valid",
    created_at="2026-06-23T10:00:00Z",
    metadata={
        "context_artifact_ids": ["ctx-042", "ctx-007", "ctx-151"],
        "context_artifact_count": 3,
        "context_ledger_workflow_id": "wf-inbox-123",
    }
)

# TriageDecision referencing a DecisionRecord
DataArtifact(
    artifact_id="df-002",
    workflow_id="wf-inbox-123",
    type_name="TriageDecision",
    type_version="1",
    producer_step="triage_llm",
    content_digest="def456...",
    content_ref="triage_llm:wf-inbox-123:triage_llm",
    validation_status="valid",
    created_at="2026-06-23T10:01:00Z",
    metadata={
        "context_decision_id": "decision-001",
        "context_ledger_workflow_id": "wf-inbox-123",
    }
)
```

---

## 5. Contracts

### 5.1 Domain Contract

Domain models live in `dataflow/models.py`.

| Type | Fields | Purpose |
|------|--------|---------|
| `DataTypeSpec` | `type_name`, `version`, `description`, `schema_kind`, `schema_ref`, `schema_digest`, `validation_mode`, `metadata` | Declares a durable data type contract |
| `StepContract` | `workflow_name`, `step_name`, `input_types`, `output_types`, `computation_kind`, `is_optional`, `metadata` | Declares what a step consumes and produces |
| `DataflowSpec` | `spec_id`, `workflow_name`, `version`, `data_types`, `step_contracts`, `edges`, `created_at`, `metadata` | Design-time data DAG |
| `DataArtifact` | `artifact_id`, `workflow_id`, `type_name`, `type_version`, `producer_step`, `content_digest`, `content_ref`, `validation_status`, `created_at`, `metadata` | Runtime materialization of a typed data product |
| `DataDependency` | `from_artifact_id`, `to_artifact_id`, `dependency_type`, `step_name`, `metadata` | Runtime lineage edge |
| `DataflowEvent` | `event_id`, `workflow_id`, `step_name`, `artifact_id`, `event_type`, `event_time`, `reason`, `metadata` | Append-only dataflow event |

Allowed `schema_kind` values (v0.1):

- `opaque` — no schema contract, digest-based identity only
- `python_dataclass` — conforms to `@dataclass` field structure

Deferred to v0.2:
- `typeddict`
- `json_schema`
- `pydantic` (Pydantic models as first-class schema kind)

**Pydantic integration (v0.1):** When `validation_mode=shape` and `pydantic>=2.0` is available, `python_dataclass` validation uses Pydantic's type checking for enhanced field validation. When Pydantic is unavailable, validation uses stdlib `isinstance` checks. Core behavior MUST NOT depend on Pydantic — it is a validation quality enhancement only.

Allowed `validation_mode` values (v0.1):

- `none` — skip validation
- `shape` — check field presence and basic type compatibility

Deferred to v0.2:
- `required_fields`
- `custom_validator`

Allowed `validation_status` values:

- `not_validated`
- `valid`
- `invalid`
- `warning`

Allowed `computation_kind` values:

- `pure_function`
- `llm_call`
- `tool_call`
- `approval_gate`
- `side_effect`
- `subworkflow`
- `human_input`

Allowed `dependency_type` values:

- `consumed_to_produce`
- `branched_from`
- `summarized_from`
- `approved_from`
- `sent_from`
- `context_derived_from`

Allowed `event_type` values:

- `spec_registered`
- `contract_registered`
- `artifact_expected`
- `artifact_consumed`
- `artifact_materialized`
- `artifact_validated`
- `artifact_rejected`
- `dependency_recorded`
- `contract_violation`
- `dataflow_completed`

Raw data storage policy:

- v0.1 stores `content_digest`, `content_ref`, type name, schema version, and metadata by default.
- Raw data payloads MUST NOT be persisted by default.
- `content` may be supplied transiently for digest calculation and validation.
- Unsafe local debug payload storage, if ever added, MUST be explicit and excluded from default audit output.

### 5.2 API Contract

Implementation lives in `dataflow/ledger.py`.

| Method | Signature | Behavior |
|--------|-----------|----------|
| `register_type` | `(type_spec: DataTypeSpec) -> DataTypeSpec` | Registers or reuses a data type contract by name, version, and schema digest |
| `register_step_contract` | `(contract: StepContract) -> StepContract` | Registers a step's declared inputs and outputs |
| `register_dataflow_spec` | `(spec: DataflowSpec) -> DataflowSpec` | Registers the design-time data DAG |
| `expect_artifact` | `(workflow_id: str, step_name: str, type_name: str, type_version: str) -> DataflowEvent` | Records that a step expects a typed input or output |
| `record_artifact` | `(workflow_id: str, type_name: str, type_version: str, producer_step: str, content: object | None, content_ref: str | None, metadata: dict | None = None) -> DataArtifact` | Computes digest, validates shape when possible, and records materialized artifact metadata |
| `record_consumption` | `(workflow_id: str, step_name: str, artifact_id: str) -> DataflowEvent` | Records that a step consumed a typed artifact |
| `record_dependency` | `(workflow_id: str, step_name: str, from_artifact_id: str, to_artifact_id: str, dependency_type: str) -> DataDependency` | Links output artifact to input artifact lineage |
| `validate_step_inputs` | `(workflow_id: str, step_name: str, artifacts: list[DataArtifact]) -> ValidationResult` | Checks runtime inputs against the step contract |
| `audit_dataflow` | `(workflow_id: str) -> DataflowAudit` | Builds a domain summary for graph presentation |

### 5.3 Step Contract Semantics

A step contract declares the data boundary around computation:

```python
StepContract(
    workflow_name="inbox_triage",
    step_name="triage_llm",
    input_types=[
        DataRef("IncomingEmail", "1"),
        DataRef("SelectedContextSet", "1"),
    ],
    output_types=[
        DataRef("TriageDecision", "1"),
    ],
    computation_kind="llm_call",
)
```

Before step execution:

- In strict mode, required input validation blocks execution if inputs are missing or invalid
- In permissive mode, missing or invalid inputs record warnings and allow execution
- Optional inputs produce warnings instead of blocking in either mode

After step execution:

- Every declared output SHOULD be materialized or explicitly skipped
- Undeclared outputs SHOULD produce a warning in v0.1
- A future output-strict mode MAY reject undeclared outputs

### 5.4 Graph Read Model Contract

Presentation models live in `dataflow/audit_view.py`.

| View Type | Fields | Purpose |
|-----------|--------|---------|
| `DataflowGraphView` | `workflow_id`, `headline`, `data_nodes`, `step_nodes`, `edges`, `violations`, `summary`, `claim_boundary_footer` | Top-level audit read model |
| `DataNodeView` | `label`, `type_label`, `version_label`, `producer_step`, `validation_label`, `artifact_ref_label` | User-facing data artifact display |
| `StepNodeView` | `step_name`, `computation_kind`, `input_labels`, `output_labels`, `status_label` | User-facing computation node display |
| `DataEdgeView` | `from_label`, `to_label`, `dependency_label`, `step_label` | User-facing lineage edge |
| `ContractViolationView` | `step_name`, `severity`, `message`, `expected_label`, `actual_label` | Contract mismatch display |

Mandatory builder:

```python
def build_dataflow_graph_view(audit: DataflowAudit) -> DataflowGraphView:
    ...
```

Renderer contract:

```python
def render_dataflow_graph(view: DataflowGraphView) -> str:
    ...
```

The renderer consumes `DataflowGraphView` only. It MUST NOT import SQLite row types or domain DTOs directly.

The CLI renderer MUST print this footer:

```text
v0.1 dataflow boundary:
This trace shows declared data contracts, runtime data artifacts, validation status, and lineage edges.
It does not prove semantic correctness of model reasoning or external system truth.
```

---

## 6. Gherkin Scenarios

### 6.1 Design-Time Scenarios

```gherkin
Scenario: Designer declares a data DAG before attaching computation
  Given a workflow designer defines data types IncomingEmail, SelectedContextSet, TriageDecision, DraftReply, ApprovalDecision, and SentReplyReceipt
  When they register the inbox_triage dataflow spec
  Then the spec records data nodes and dependency edges
  And each workflow step declares input and output data types
  And no model prompt or tool implementation is required to inspect the data DAG

Scenario: Agent computation attaches to typed data nodes
  Given a step contract for triage_llm consumes IncomingEmail and SelectedContextSet
  And it produces TriageDecision
  When the workflow binds triage_llm_fn to that contract
  Then the runtime can validate inputs before calling the model
  And can validate the output after the model returns
```

### 6.2 Runtime Scenarios

```gherkin
Scenario: Step materializes typed output
  Given ingest_email consumes a raw fixture email
  When ingest_email completes
  Then it materializes an IncomingEmail data artifact
  And the artifact records type_name IncomingEmail and type_version 1
  And raw email content is not persisted by default

Scenario: Transformation lineage links input artifacts to output artifacts
  Given select_context consumes IncomingEmail, PriorEmailCorpus, and CalendarEventCorpus
  When it produces SelectedContextSet
  Then the dataflow ledger records dependency edges from each consumed input artifact to SelectedContextSet
  And the dataflow audit shows SelectedContextSet as composed from those inputs

Scenario: Contract violation is visible before agent computation
  Given triage_llm requires SelectedContextSet
  And no valid SelectedContextSet artifact exists for the workflow
  When the runtime validates triage_llm inputs
  Then it records a contract_violation event
  And triage_llm is not called in strict mode
  And the audit trace shows the missing input in user language

Scenario: Final side effect is traced to typed data products
  Given send_reply sends an email reply
  When the side effect succeeds
  Then SentReplyReceipt is materialized
  And SentReplyReceipt links back to ApprovalDecision and DraftReply
  And the dataflow audit can trace the sent reply back to the original IncomingEmail
```

### 6.3 Context Composition Scenarios

```gherkin
Scenario: Selected context is both data and context lineage
  Given select_context records retrieved, selected, and rejected context artifacts
  When it materializes SelectedContextSet
  Then the data artifact metadata references the selected context artifact ids
  And the context audit explains which information was selected and rejected
  And the dataflow audit explains which typed data product flowed into triage_llm

Scenario: Model decision cross-links dataflow and context
  Given triage_llm produces TriageDecision
  And the context ledger records a DecisionRecord and DecisionLineage
  When the dataflow audit renders TriageDecision
  Then it includes a privacy-safe reference to the context decision id
  And the context audit remains the source of truth for influential context artifacts
```

---

## 7. Inbox Triage Example Data DAG

### 7.1 Data Types

| Type | Version | Meaning |
|------|---------|---------|
| `IncomingEmail` | `1` | Normalized incoming email under triage |
| `PriorEmailCorpus` | `1` | Available prior email search space |
| `CalendarEventCorpus` | `1` | Available calendar search space |
| `ContextQuery` | `1` | Query or selection intent derived from incoming email |
| `SelectedContextSet` | `1` | Context selected for model consumption, with context artifact references |
| `TriageDecision` | `1` | Classification, urgency, rationale refs, and routing decision |
| `DraftReply` | `1` | Proposed reply content reference and metadata |
| `ApprovalDecision` | `1` | Human or policy approval outcome |
| `SentReplyReceipt` | `1` | External send result reference |

### 7.2 Step Contracts

| Step | Computation Kind | Inputs | Outputs |
|------|------------------|--------|---------|
| `ingest_email` | `pure_function` | raw fixture/source ref | `IncomingEmail` |
| `select_context` | `pure_function` | `IncomingEmail`, `PriorEmailCorpus`, `CalendarEventCorpus` | `ContextQuery`, `SelectedContextSet` |
| `triage_llm` | `llm_call` | `IncomingEmail`, `SelectedContextSet` | `TriageDecision` |
| `draft_reply` | `llm_call` | `IncomingEmail`, `SelectedContextSet`, `TriageDecision` | `DraftReply` |
| `approval_gate` | `approval_gate` | `TriageDecision`, `DraftReply` | `ApprovalDecision` |
| `send_reply` | `side_effect` | `DraftReply`, `ApprovalDecision` | `SentReplyReceipt` |

### 7.3 Graph Sketch

```text
IncomingEmail ------------------------------+
    |                                       |
    v                                       |
ContextQuery -> SelectedContextSet --------+--> TriageDecision
                                              |       |
                                              v       v
                                           DraftReply |
                                              |       |
                                              v       |
                                       ApprovalDecision
                                              |
                                              v
                                      SentReplyReceipt
```

The context extension explains the contents and influence of `SelectedContextSet`.

The dataflow extension explains how `SelectedContextSet`, `TriageDecision`, `DraftReply`, and `ApprovalDecision` compose into `SentReplyReceipt`.

---

## 8. Phased Implementation Plan

### Phase 1: Contracts and Schema

**Scope:** Add design-time data type and step contract registration.

**Files:**

- `dataflow/__init__.py`
- `dataflow/models.py`
- `dataflow/schema.py`
- `dataflow/ledger.py`

**Deliverables:**

- dataclasses listed in section 5.1
- additive SQLite tables:
  - `dataflow_type_specs`
  - `dataflow_step_contracts`
  - `dataflow_specs`
  - `dataflow_artifacts`
  - `dataflow_dependencies`
  - `dataflow_events`
- idempotent schema creation
- validation for allowed enum values
- optional Pydantic validation fallback to stdlib

**Acceptance criteria:**

- [ ] Existing DurableFlow and context tests pass without using `DataflowLedger`
- [ ] Schema initializes on an existing DurableFlow database without altering core or context tables
- [ ] Data type contracts deduplicate by type name, version, and schema digest
- [ ] Step contracts validate referenced data types
- [ ] Raw content is not persisted by default
- [ ] Extension works without Pydantic installed
- [ ] Enhanced validation activates when Pydantic is available

### Phase 2: Runtime Materialization and Validation

**Scope:** Record typed runtime artifacts and validate step boundaries.

**Deliverables:**

- `record_artifact`
- `record_consumption`
- `record_dependency`
- `validate_step_inputs`
- append-only dataflow events
- validation result model

**Acceptance criteria:**

- [ ] Missing required inputs produce `contract_violation`
- [ ] Invalid artifacts cannot satisfy strict required inputs
- [ ] Consumed inputs and produced outputs are linked through dependencies
- [ ] Undeclared outputs are visible as warnings
- [ ] Validation behavior is deterministic and network-free

### Phase 3: Inbox Triage Integration

**Scope:** Instrument the existing inbox triage workflow with optional dataflow ledger support.

**Files:**

- `src/workflows.py`
- `examples/inbox_triage_dataflow_demo.py`
- `dataflow/examples.py`

**Deliverables:**

- inbox triage `DataflowSpec`
- step contracts listed in section 7.2
- optional `dataflow_ledger` dependency
- artifact materialization at each workflow step
- cross-links to `/context` artifacts and decisions when context ledger is enabled

**Acceptance criteria:**

- [ ] Workflow behavior is unchanged when no dataflow ledger is provided
- [ ] Demo runs without API keys or network
- [ ] Final `SentReplyReceipt` traces back to `IncomingEmail`
- [ ] `SelectedContextSet` cross-links to context artifact IDs when available
- [ ] Crash/resume does not duplicate data artifacts for already completed steps

### Phase 4: Dataflow Graph Audit

**Scope:** Provide a user-facing read model and CLI renderer.

**Files:**

- `dataflow/audit.py`
- `dataflow/audit_view.py`
- `dataflow/cli.py`

**Deliverables:**

- `DataflowAudit` domain summary
- `build_dataflow_graph_view(audit)`
- `render_dataflow_graph(view)`
- CLI command:
  - `python -m dataflow.cli audit --db <path> --workflow-id <id>`

**Acceptance criteria:**

- [ ] Renderer consumes `DataflowGraphView` only
- [ ] Audit output uses user-facing data DAG language
- [ ] Audit lists data types, step contracts, validation status, materialized artifacts, and dependency edges
- [ ] Audit cross-links context decision IDs without duplicating context audit responsibilities
- [ ] Raw payloads are omitted by default

### Phase 5: Tests and Documentation

**Scope:** Make the extension deterministic, reviewable, and understandable.

**Files:**

- `tests/test_dataflow_contracts.py`
- `tests/test_dataflow_ledger.py`
- `tests/test_dataflow_audit_view.py`
- `tests/test_inbox_triage_dataflow_demo.py`
- `docs/dataflow.md`

**Acceptance criteria:**

- [ ] Every Gherkin scenario has a test or explicit deferral
- [ ] Docs include before/after: execution trace versus execution + context + dataflow trace
- [ ] Docs explain relationship to data engineering DAGs
- [ ] Docs explain relationship to `/context`
- [ ] Docs describe optional Pydantic validation behavior
- [ ] Existing tests still pass

---

## 9. Entry Gates

Before implementation begins:

**Decided:**
- [x] Package name: `dataflow` (decided 2026-06-22)
- [x] Schema kinds for v0.1: `opaque`, `python_dataclass` only
- [x] Validation modes for v0.1: `none`, `shape` only
- [x] Pydantic: optional runtime dependency for enhanced validation only
- [x] Mermaid output: deferred to v0.2
- [x] Inbox triage: first integration target
- [x] Strict mode: missing required inputs block execution; permissive mode warns (decided 2026-06-22)

All entry gates satisfied. Implementation may begin.

---

## 10. Exit Gates

Before claiming v0.1 complete:

- [ ] Data type contracts and step contracts are persisted
- [ ] Runtime data artifacts are recorded with type name and version
- [ ] Step input validation records visible contract violations
- [ ] Data dependency edges connect consumed inputs to produced outputs
- [ ] Inbox triage demo renders a dataflow audit
- [ ] Existing DurableFlow workflows run without constructing `DataflowLedger`
- [ ] `/context` still runs independently
- [ ] No raw payloads are persisted by default
- [ ] All tests pass locally
- [ ] Extension works without Pydantic installed

Do not mark complete if:

- the implementation only logs step status without typed data artifacts
- outputs are recorded but not linked to inputs
- context lineage is duplicated instead of referenced
- raw email, prompt, response, or tool payload content is stored by default
- the audit output exposes raw table names as its primary surface
- Pydantic is required for core functionality

---

## 11. Pre-Mortem Analysis

### Failure: Data DAG Becomes Decorative

Risk: Designers declare a graph, but runtime does not enforce or record anything meaningful.

Mitigation: Step input validation and output materialization are exit gates. A graph without runtime artifact linkage is not complete.

### Failure: Contracts Are Too Heavy

Risk: Strong schema requirements make simple workflows painful.

Mitigation: v0.1 supports `opaque`, `python_dataclass` with `shape` validation, and lightweight standard-library validation. Stronger validation modes are deferred to v0.2.

### Failure: This Duplicates `/context`

Risk: Selected context and model decisions are represented twice with inconsistent semantics.

Mitigation: DataFlow records typed data products. `/context` remains source of truth for retrieved, selected, rejected, consumed, and influential information artifacts. Cross-links are references only.

### Failure: Agent Non-Determinism Is Overclaimed

Risk: The graph suggests deterministic semantic correctness even when LLM reasoning is probabilistic.

Mitigation: The audit footer states that dataflow lineage does not prove semantic correctness. It proves declared contracts, runtime artifacts, validation status, and lineage edges.

### Failure: Runtime Coupling Breaks Core DurableFlow

Risk: Existing workflows must be rewritten to use the data DAG.

Mitigation: The dataflow ledger is optional and additive. Existing step functions can be wrapped or instrumented gradually.

---

## 12. Roadmap

### v0.2: Schema and Validation Expansion

- Additional `schema_kind` values: `typeddict`, `json_schema`, `pydantic`
- Additional `validation_mode` values: `required_fields`, `custom_validator`
- Pydantic-based validation becomes first-class when installed
- Schema versioning and migration helpers

### v0.2: Design-Time Authoring Helpers

- Python builder API for data DAGs
- contract generation from dataclasses or TypedDicts
- Mermaid renderer for design-time graph
- static validation for missing producers or consumers
- decorator/wrapper API for step instrumentation

### v0.3: Replay and Impact Analysis

- reconstruct a dataflow from artifact and dependency rows
- show all downstream artifacts affected by a data artifact
- compare designed DAG versus actual runtime path
- detect skipped optional branches

### v0.4: Policy and Governance

- require approval before high-risk data products feed side effects
- attach policy labels to data types
- enforce source trust requirements through `/context`
- review queue for invalid or warning-state data artifacts

### Later: External Lineage Export

- OpenLineage/Marquez export
- Dagster/dbt-style asset graph export
- graph visualization beyond static Mermaid
- integration with external schema registries

---

## 13. README Positioning Draft

DurableFlow treats agentic workflows as more than step sequences. With DataFlow, a workflow can be designed as a typed data DAG, with agent computation attached to each node.

Execution durability answers:

> Did the workflow survive crashes, retries, approvals, and side effects?

Context durability answers:

> What information did the workflow retrieve, select, consume, and credit?

Dataflow durability answers:

> What typed data products flowed through the workflow, what transformed them, and how did they compose into the final result?

Together, these make agentic workflows inspectable in the language of production data systems: contracts, artifacts, transformations, materializations, validation, and lineage.

The first target is inbox triage. The workflow can be read as a data DAG from `IncomingEmail` to `SelectedContextSet`, `TriageDecision`, `DraftReply`, `ApprovalDecision`, and `SentReplyReceipt`. The existing step functions remain the computation. The new layer makes the data flow explicit, durable, and auditable.

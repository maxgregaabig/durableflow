# Specification: Eval Gate for DurableFlow

**Status:** DRAFT
**Scope:** Reusable DurableFlow platform capability for turning recorded workflow runs into deterministic evaluation cases and pass/fail gates.
**Owner:** Marcos Polanco
**Applies:** `/Users/marcos/Downloads/helios/process/verification-policy.md`, `/Users/marcos/Downloads/agentel/docs/spec-policy.md`, `/Users/marcos/Downloads/agentel/docs/semantics-policy.md`
**Dependency policy:** Core implementation remains Python standard library only. External evaluators and LangSmith export are optional integrations and MUST NOT be required for local tests, examples, or workflow execution.
**Visibility:** Platform implementation guide. Application-specific datasets, scorers, and fixtures belong in application repos such as SupportFlow.

---

## Policy Reference Resolution

This private spec intentionally references process policies outside the DurableFlow repo:

- `/Users/marcos/Downloads/helios/process/verification-policy.md`
- `/Users/marcos/Downloads/agentel/docs/spec-policy.md`
- `/Users/marcos/Downloads/agentel/docs/semantics-policy.md`

Before this spec can move from DRAFT to READY, the owner MUST either confirm these cross-repo references are the authoritative policy source for this work, or copy/link the policies into a stable repo-relative location and update the `Applies` header.

---

## 0. Positioning Note

This spec defines the DurableFlow-side eval gate that was implied by `golden.md`.

The application-level workflow should live outside this repo. DurableFlow owns the reusable machinery:

- normalize completed workflow runs into evaluation cases;
- replay or score those cases through a generic scorer interface;
- emit a pass/fail gate report with evidence pointers;
- optionally export compatible records to LangSmith or another external eval system.

DurableFlow does not own customer-support tickets, refund policies, support-specific agents, or domain-specific scoring rubrics. Those belong to the consuming application.

---

## 1. Intent Mapping

### 1.1 Business Intent

DurableFlow should demonstrate that durable agent workflows can be governed after they run. The organizational outcome is deployment confidence: teams can reject a workflow, prompt, model, or tool change before it ships if it regresses known-good trajectories, violates safety boundaries, loses context fidelity, or increases cost beyond declared limits.

### 1.2 Experience Intent

The operator believes they are "deciding whether this workflow change is safe to ship." They are not debugging raw telemetry events, reading SQLite rows, or trusting an implementer's completion claim.

**Emotional context:** cautious and accountable. A false pass means unsafe automation may reach a real application; a false fail means useful changes are blocked. The gate report must make the verdict defensible.

### 1.3 Technical Intent

The eval gate MUST preserve DurableFlow's core invariants:

1. Workflow correctness never depends on LangSmith, network access, or an external eval service.
2. Local SQLite records remain the source of truth for checkpointing, approval state, side-effect idempotency, telemetry, and context lineage.
3. Eval cases are deterministic local artifacts by default.
4. Domain-specific scorers are plug-ins supplied by the application, not hardcoded into DurableFlow.
5. Pass/fail verdicts cite reproducible evidence artifacts, not prose-only assertions.
6. Raw prompts, customer data, model responses, and sensitive artifacts are not exported by default.

---

## 2. Requirement & Narrative

### 2.1 What

Build a reusable eval gate capability for DurableFlow:

1. Select one or more completed workflow runs.
2. Convert each selected run into an `EvalCase` containing redacted inputs, expected outputs, trace metadata, context lineage metadata, cost metadata, and approval metadata.
3. Run a set of generic and application-provided scorers over each case.
4. Aggregate scorer results into an `EvalGateReport`.
5. Return a deterministic pass/fail verdict suitable for local CLI use and CI.
6. Optionally export eval cases or run summaries to LangSmith through the optional integration described in `docs/langsmith-adapter.md`.

### 2.2 Why

DurableFlow already shows durable execution, approval gates, context lineage, telemetry, and recovery behavior. The missing platform step is the closed loop: traces become eval cases, eval cases become regression suites, and regression suites gate future workflow changes.

### 2.3 Who

**Primary persona:** Application engineer building a workflow on DurableFlow and deciding whether a change can ship.

**Secondary persona:** Platform engineer evaluating whether DurableFlow's records are sufficient to support reproducible eval gates.

**Verifier persona:** Independent reviewer or CI process that must reproduce the gate verdict from local artifacts.

### 2.4 Non-Goals

- No customer-support, factory, or other application-specific scorer in this repo.
- No required LangSmith dependency.
- No raw-data export mode in the first implementation.
- No replacement for `WorkflowStore`, `ContextLedger`, or `TelemetryLogger`.
- No graphical dashboard in the initial scope.
- No claim that generic scorers can determine domain task success without application-provided rubric code.

---

## 3. Experience Semantics

### 3.1 Experience Semantics Template

#### WHO THEY ARE

Primary persona: Application engineer or platform reviewer.
Core job: Decide whether a workflow change is safe to ship.
Technical proficiency: High, but they should not inspect SQLite manually to understand the verdict.

#### WHAT THEY BELIEVE THEY ARE DOING

"Reviewing a release gate" -- not "reading telemetry rows."

#### QUESTIONS THEY WAKE UP ASKING

- Did the workflow still complete the task correctly?
- Did it use the right context and tools?
- Did any safety or approval boundary regress?
- Did cost, latency, or retry behavior exceed the budget?
- What evidence supports the pass/fail verdict?

#### EMOTIONAL CONTEXT

Cautious and skeptical. The operator is accountable for a ship/no-ship decision and expects agent changes to regress in non-obvious ways.

#### PRIMARY CONCEPTS

- Eval case
- Golden set
- Gate verdict
- Scorer result
- Regression
- Evidence artifact
- Release blocker

#### SECONDARY CONCEPTS

- telemetry event dictionary
- SQLite row
- context ledger event type
- model routing metadata
- scorer protocol object
- JSON serialization detail

#### SUCCESS FEELS LIKE

"I know whether this change can ship, and I can defend the verdict with evidence."

#### FAILURE FEELS LIKE

"The gate says pass or fail, but I cannot tell what was evaluated or why."

#### PRIMARY SCREEN

Eval Gate Report -- CLI or markdown summary for one gate run.

#### PRIMARY ACTION

Accept the gate verdict, inspect the failing evidence, or rerun after remediation.

#### UBIQUITOUS LANGUAGE

| User Term | Technical Term |
|-----------|----------------|
| Eval case | Serialized `EvalCase` created from a completed workflow run |
| Golden set | Versioned collection of eval cases |
| Gate verdict | Aggregated pass/fail result from scorer thresholds |
| Scorer result | One `ScoreResult` for one case and one scorer |
| Regression | Score or budget movement outside configured threshold |
| Evidence artifact | Path to JSON report, trace summary, log, or verifier output |
| Release blocker | Failing scorer result that makes the gate fail |
| Context fidelity | Context lineage completeness and expected artifact use |
| Safety boundary | Approval, write, redaction, or policy rule that must hold |

### 3.2 Presentation Contract

The initial feature is CLI and markdown only. It still requires a presentation layer so report renderers do not expose raw backend DTOs.

| Contract | Purpose | This feature |
|----------|---------|--------------|
| Domain contract | Eval execution data | `EvalCase`, `ScoreResult`, `EvalGateReport` |
| Presentation contract | Operator-facing view model | `EvalGateReportView`, `build_eval_gate_report_view(report) -> EvalGateReportView` |
| Render contract | CLI / markdown rendering | `render_eval_gate_report(view: EvalGateReportView) -> str` |

### 3.3 EvalGateReportView Schema

```python
@dataclass
class EvalGateReportView:
    """Operator-facing summary of one eval gate run."""

    gate_name: str
    status: Literal["passed", "failed", "incomplete"]
    summary: GateSummaryView
    failing_checks: list[FailingCheckView]
    case_results: list[CaseResultView]
    evidence: list[GateEvidenceView]
    next_action: GateNextActionView

@dataclass
class GateSummaryView:
    total_cases: int
    passed_cases: int
    failed_cases: int
    scorer_count: int
    cost_delta: float | None
    latency_delta_ms: int | None

@dataclass
class FailingCheckView:
    case_id: str
    scorer_name: str
    user_facing_reason: str
    threshold: str
    observed: str
    evidence_path: str

@dataclass
class CaseResultView:
    case_id: str
    workflow_id: str
    status: Literal["passed", "failed", "skipped"]
    score_summary: str
    release_blockers: list[str]

@dataclass
class GateEvidenceView:
    evidence_id: str
    evidence_kind: Literal["eval_report", "trace_summary", "context_summary", "scorer_log"]
    path: str
    digest: str

@dataclass
class GateNextActionView:
    action_type: Literal["ship", "inspect_failures", "rerun", "fix_spec"]
    description: str
```

### 3.4 UI Semantic Data Model

| User mental model object | Presentation field | Source field(s) | Builder responsibility |
|--------------------------|--------------------|-----------------|------------------------|
| Gate verdict | `status`, `summary` | `EvalGateReport.status`, aggregate scores | Convert scorer outcomes to pass/fail/incomplete with user-facing reason |
| Release blocker | `failing_checks[]` | failed `ScoreResult` rows | Sort by severity, hide raw scorer payloads, cite evidence paths |
| Golden set | `summary.total_cases`, `case_results[]` | eval case manifest | Present case count and case IDs, not storage internals |
| Evidence artifact | `evidence[]` | report paths and digests | Show inspectable artifact pointers with digests |
| Next decision | `next_action` | aggregate verdict | Map pass to "ship"; fail to "inspect failures"; incomplete to "fix spec" |

### 3.5 Semantic Fitness Functions

| Test ID | Scenario | Assertion | Pass Criteria |
|---------|----------|-----------|---------------|
| SEM-EVAL-001 | Operator reviews a failed gate | The report states the gate verdict and release blockers before case detail | Rendered report order is verdict, blockers, case results, evidence |
| SEM-EVAL-002 | Operator reviews an incomplete gate | The report distinguishes missing evidence from failed behavior | `status == "incomplete"` and next action is `fix_spec` or `rerun`, not `ship` |
| SEM-EVAL-003 | Operator reviews evidence | Every failing check cites an evidence path | All `FailingCheckView.evidence_path` values are non-empty paths |
| SEM-EVAL-004 | Operator reads report language | Primary report sections avoid backend terms | Blocklist scan returns zero hits in headings and primary labels |
| SEM-EVAL-005 | Renderer contract | Renderer accepts only `EvalGateReportView` | Architecture test shows no renderer imports domain DTO modules |

### 3.6 Technical Term Blocklist

These terms MUST NOT appear in report headings or primary labels:

| Forbidden Term | Ubiquitous Replacement |
|----------------|------------------------|
| `step_data` | workflow state |
| SQLite | workflow records |
| `ContextLedger` | context records |
| telemetry dict | trace summary |
| `ScoreResult` | scorer result |
| raw payload | evidence details |
| UUIDv5 | stable run ID |
| `WorkflowStore` | workflow records |

---

## 4. Gherkin Scenarios

### 4.1 Behavioral Gherkin

```gherkin
Scenario: Create eval case from a completed workflow
  Given a completed DurableFlow workflow with telemetry and context lineage
  When the eval case builder reads the workflow record
  Then it writes an EvalCase JSON artifact
  And the artifact contains workflow_id, case_id, expected outcome, trace summary, context summary, cost summary, and approval summary
  And raw prompts and raw model responses are represented by digests by default

Scenario: Reject eval case creation for incomplete workflow
  Given a workflow that has not reached completed status
  When the eval case builder attempts to promote it into a golden set
  Then no EvalCase is written
  And the builder records a user-facing reason that the workflow is incomplete

Scenario: Run generic eval gate over local cases
  Given a golden set manifest with three EvalCase artifacts
  And two registered scorers with explicit thresholds
  When the eval gate runs
  Then it executes each scorer for each case
  And it writes an EvalGateReport JSON artifact
  And the aggregate verdict is passed only if every required scorer meets its threshold

Scenario: Failing scorer blocks the gate
  Given an EvalCase whose context fidelity score is below threshold
  When the eval gate aggregates scorer results
  Then the gate verdict is failed
  And the failing scorer appears in release_blockers
  And the report cites the evidence artifact for the failure

Scenario: Missing application scorer makes task success incomplete
  Given a golden set requires the scorer "task_success"
  And no scorer named "task_success" is registered
  When the eval gate runs
  Then the gate verdict is incomplete
  And the report explains that required scorer registration is missing
  And the gate does not pass

Scenario: Optional LangSmith export failure does not affect local verdict
  Given local eval scoring has completed
  And LangSmith export is enabled but the network request fails
  When the eval gate writes the local report
  Then the local pass/fail verdict remains based only on local scorer results
  And the report records export_status = "failed"
  And the workflow or gate process does not raise due to the export failure

Scenario: CI exits nonzero on failed gate
  Given an eval gate report with status failed
  When the CLI command runs in CI mode
  Then the command exits with code 1
  And it prints the report path and release blockers
```

### 4.2 Conceptual Gherkin

```gherkin
Scenario: Operator trusts a passed gate
  Given an application engineer is cautious about shipping an agent workflow change
  When they open a passed eval gate report
  Then they see which golden set ran, which scorers passed, and where the evidence is stored
  And they can explain why the change is safe to ship

Scenario: Operator investigates a failed gate
  Given a release gate failed minutes before deployment
  When the operator opens the report
  Then the report highlights the release blockers first
  And it shows the failing case, scorer, threshold, observed value, and evidence path
  And it avoids burying the decision under raw telemetry payloads

Scenario: Operator distinguishes failure from unverifiable result
  Given the gate cannot run a required scorer
  When the operator reads the report
  Then they understand this is incomplete evidence, not proof that the workflow behavior failed
  And the next action is to fix the scorer registration or case manifest

Scenario: Reviewer audits evidence
  Given a verifier needs to reproduce the gate verdict
  When they inspect the report
  Then every claim has an evidence artifact path and digest
  And every required scorer has a result for each applicable case
```

---

## 5. Runtime Traceability

Golden path: promote completed local workflow runs into a golden set, run local eval gate, render report.

```text
evals/cli.py: main(argv)
  ├─ parse args: make-case | gate | render-report
  ├─ WorkflowStore(db_path)
  ├─ ContextLedger(...) when context DB is configured
  └─ dispatch command

make-case command
  ├─ evals/cases.py: build_eval_case_from_workflow(store, context_ledger, workflow_id, config)
  │    ├─ store.get_workflow(workflow_id)
  │    ├─ store.get_step_results(workflow_id)
  │    ├─ telemetry_loader.load_events(workflow_id)
  │    ├─ context_export.build_context_summary(context_ledger, workflow_id)
  │    ├─ redaction.digest_payloads(...)
  │    └─ EvalCase(...)
  ├─ evals/manifest.py: append_case_to_manifest(manifest_path, eval_case_path)
  └─ evals/io.py: write_json_with_digest(eval_case, output_path)

gate command
  ├─ evals/manifest.py: load_eval_manifest(manifest_path)
  ├─ evals/io.py: load_eval_case(path)
  ├─ evals/registry.py: ScorerRegistry.resolve(required_scorers)
  ├─ evals/gate.py: run_eval_gate(cases, scorers, config)
  │    ├─ scorer.score(case) -> ScoreResult
  │    ├─ aggregate_score_results(...)
  │    └─ EvalGateReport(...)
  ├─ evals/io.py: write_json_with_digest(report, output_path)
  ├─ integrations/langsmith_adapter.py: optional dataset/report export when enabled
  ├─ evals/view.py: build_eval_gate_report_view(report)
  └─ evals/render.py: render_eval_gate_report(view)
```

Undefined implementation items above are part of this spec unless marked DEFERRED. No item requires LangSmith, network access, or a domain application.

---

## 6. Architecture and Contracts

### 6.1 Package Shape

```text
evals/
  __init__.py
  cases.py
  cli.py
  gate.py
  io.py
  manifest.py
  redaction.py
  registry.py
  scorers.py
  view.py
  render.py
```

### 6.2 Domain Models

```python
@dataclass(frozen=True)
class EvalCase:
    case_id: str
    workflow_id: str
    workflow_name: str
    created_at: str
    input_summary: dict[str, Any]
    expected: dict[str, Any]
    trace_summary: dict[str, Any]
    context_summary: dict[str, Any]
    approval_summary: dict[str, Any]
    cost_summary: dict[str, Any]
    metadata: dict[str, Any]

@dataclass(frozen=True)
class EvalManifest:
    manifest_id: str
    version: int
    cases: list[str]
    required_scorers: list[str]
    thresholds: dict[str, float]

@dataclass(frozen=True)
class ScoreResult:
    case_id: str
    scorer_name: str
    score: float | None
    threshold: float
    status: Literal["passed", "failed", "skipped", "error"]
    reason: str
    evidence_path: str

@dataclass(frozen=True)
class EvalGateReport:
    report_id: str
    manifest_id: str
    status: Literal["passed", "failed", "incomplete"]
    results: list[ScoreResult]
    release_blockers: list[str]
    evidence: list[dict[str, str]]
    export_status: Literal["not_configured", "succeeded", "failed"]
```

### 6.3 Scorer Protocol

```python
class EvalScorer(Protocol):
    name: str

    def score(self, case: EvalCase) -> ScoreResult:
        ...
```

Generic scorers may include context lineage completeness, approval boundary preservation, cost threshold, latency threshold, and trace completeness. Domain scorers such as support-ticket task success are registered by application code.

### 6.4 Redaction Contract

Default export mode is `digest_only`.

| Field class | Default representation |
|-------------|------------------------|
| raw prompt | SHA-256 digest and byte length |
| raw model response | SHA-256 digest and byte length |
| customer or application payload | app-provided redacted summary or digest |
| context artifact content | artifact ID, source, role, digest, token count |
| tool arguments | allow-listed metadata only; unknown keys dropped |

Raw export is DEFERRED. It requires a separate compliance review and explicit opt-in.

### 6.5 Gate Aggregation Rules

1. A required scorer with status `failed` makes the gate `failed`.
2. A required scorer with status `error` makes the gate `incomplete` unless another required scorer already failed.
3. A missing required scorer makes the gate `incomplete`.
4. Optional scorer failures are warnings unless configured as release blockers.
5. A gate with zero cases is `incomplete`.
6. A gate with no required scorers is `incomplete`.

### 6.6 Deferred Items

| Item | Claim ID | Rationale |
|------|----------|-----------|
| Raw-data dataset export | C-EVAL-DEFER-001 | Requires compliance review and explicit opt-in |
| Managed LangSmith evaluator execution | C-EVAL-DEFER-002 | Local gate must work before remote execution |
| Graphical eval dashboard | C-EVAL-DEFER-003 | CLI and markdown report are sufficient for initial verification |
| Application-specific task-success scorer | C-EVAL-DEFER-004 | Belongs in application repo |
| Statistical A/B significance testing | C-EVAL-DEFER-005 | Initial gate is deterministic regression testing |

Deferred items MUST NOT be claimed as complete.

---

## 7. Phased Implementation Plan

### Phase 1: Eval Case and Manifest Models

Deliverables:

- `evals/cases.py`, `evals/manifest.py`, `evals/io.py`, and `evals/redaction.py`.
- JSON serialization with stable key ordering and digest recording.
- `build_eval_case_from_workflow(...)`.

Acceptance criteria:

- [ ] Completed workflow runs can be converted into deterministic `EvalCase` JSON. Verification: T-EVAL-001.
- [ ] Incomplete workflow runs are rejected with a user-facing reason. Verification: T-EVAL-002.
- [ ] Default case artifacts contain digests, not raw prompts or raw responses. Verification: T-EVAL-001, T-EVAL-013.
- [ ] Manifest loading rejects zero-case manifests when used for a gate. Verification: T-EVAL-003.

### Phase 2: Scorer Protocol and Generic Scorers

Deliverables:

- `EvalScorer` protocol and `ScorerRegistry`.
- Generic scorers for trace completeness, approval boundary preservation, context lineage completeness, cost threshold, and latency threshold.
- Unit tests using deterministic local fixtures.

Acceptance criteria:

- [ ] Required scorers must be registered by name before a gate can pass. Verification: T-EVAL-004, T-EVAL-006.
- [ ] Each scorer returns `ScoreResult` with status, threshold, reason, and evidence path. Verification: T-EVAL-004, T-EVAL-005, T-EVAL-012.
- [ ] Generic safety and budget scorers do not require application-specific payloads. Verification: T-EVAL-004, T-EVAL-014.
- [ ] Scorer errors are recorded and make the gate incomplete unless a failure already blocks the gate. Verification: T-EVAL-007.

### Phase 3: Gate Runner and Report

Deliverables:

- `run_eval_gate(cases, scorers, config) -> EvalGateReport`.
- Gate aggregation rules from §6.5.
- JSON report writer with evidence digests.

Acceptance criteria:

- [ ] Any failed required scorer blocks the gate. Verification: T-EVAL-005.
- [ ] Missing required scorer makes the gate incomplete. Verification: T-EVAL-006.
- [ ] Zero-case and zero-required-scorer manifests cannot pass. Verification: T-EVAL-003.
- [ ] Report evidence paths point to inspectable artifacts. Verification: T-EVAL-012.

### Phase 4: CLI and Presentation Layer

Deliverables:

- `evals/cli.py` with `make-case`, `gate`, and `render-report` commands.
- `EvalGateReportView`, `build_eval_gate_report_view(...)`, and `render_eval_gate_report(...)`.
- CI mode exit codes: `0` for passed, `1` for failed, `2` for incomplete or invalid configuration.

Acceptance criteria:

- [ ] CLI prints the report path and concise verdict. Verification: T-EVAL-008.
- [ ] Rendered report shows verdict and release blockers before case details. Verification: T-EVAL-009, T-EVAL-010.
- [ ] Rendered report headings and primary labels pass the technical-term blocklist. Verification: T-EVAL-010.
- [ ] Renderer accepts presentation view types only. Verification: T-EVAL-010.

### Phase 5: Optional LangSmith Dataset Export Hook

Deliverables:

- Optional export hook that reuses the integration boundary in `docs/langsmith-adapter.md`.
- Local gate verdict remains authoritative when export fails.

Acceptance criteria:

- [ ] LangSmith is never imported by core eval modules. Verification: T-EVAL-010, T-EVAL-011.
- [ ] Missing LangSmith dependency does not affect local gates. Verification: T-EVAL-011.
- [ ] Export failures are recorded as `export_status = "failed"` and do not raise into local scoring. Verification: T-EVAL-011.

### Phase 6: Documentation and Verification Ledger

Deliverables:

- README or docs section explaining how application repos register scorers.
- Verification ledger rows for every claim in this spec.
- Example local fixtures that exercise pass, fail, and incomplete outcomes.

Acceptance criteria:

- [ ] Docs distinguish platform scorers from application scorers. Verification: T-EVAL-014 plus cross-read against docs.
- [ ] Verification ledger cites evidence artifacts for each accepted claim. Verification: T-EVAL-012 and ledger audit in §10.
- [ ] Pass, fail, and incomplete report fixtures exist. Verification: T-EVAL-009, T-EVAL-010.

---

## 8. Entry Gates

Implementation MUST NOT begin until these gates pass.

**DRAFT readiness note:** These checkboxes are intentionally unchecked while this spec is DRAFT. Moving to READY requires an explicit readiness review that records pass/fail for every item in §8.1-§8.4.

### 8.1 Specification Completeness

- [ ] All acceptance criteria are explicit and unambiguous.
- [ ] No placeholder text remains in this spec.
- [ ] Required file paths and module names are specified.
- [ ] Dependencies are listed and pinned if introduced.
- [ ] Deferred items are explicitly scoped and excluded from MVP completion.
- [ ] Cross-repo policy references in Policy Reference Resolution are confirmed or converted to repo-relative references.

### 8.2 Cross-Reference Consistency

- [ ] Runtime traceability names every golden-path method and import.
- [ ] Gherkin scenarios map to test IDs in §9.
- [ ] Presentation contract maps to primary concepts in §3.
- [ ] LangSmith remains optional in all architecture sections.
- [ ] Domain-specific scoring is consistently assigned to application repos.

### 8.3 Semantic Entry Gates

- [ ] Operator persona, mental model, and primary questions are defined.
- [ ] Ubiquitous language table is complete.
- [ ] `EvalGateReportView` and renderer contract are specified.
- [ ] Semantic fitness functions have objective pass criteria.
- [ ] Technical term blocklist is defined.

### 8.4 Verification Entry Gates

- [ ] Each claim is falsifiable.
- [ ] Each claim is classified by type in §10.
- [ ] Each claim declares a verification method and expected evidence artifact.
- [ ] Deterministic fixtures exist for pass, fail, incomplete, missing scorer, and export failure.
- [ ] Independent verifier role is assigned before a VERIFIED verdict can be written.

---

## 9. Test Plan

| Test ID | Scenario | Type | Assertions |
|---------|----------|------|------------|
| T-EVAL-001 | Completed workflow to eval case | Unit | `EvalCase` contains required fields; raw prompt/response fields are digests |
| T-EVAL-002 | Incomplete workflow rejection | Unit | no case written; reason states workflow is incomplete |
| T-EVAL-003 | Manifest validation | Unit | zero-case manifest and zero-required-scorer manifest cannot pass |
| T-EVAL-004 | Required scorer pass | Unit | all required scorer pass results aggregate to gate `passed` |
| T-EVAL-005 | Required scorer failure | Unit | failed required scorer aggregates to gate `failed` and release blocker |
| T-EVAL-006 | Missing required scorer | Unit | missing scorer aggregates to gate `incomplete` |
| T-EVAL-007 | Scorer error handling | Unit | scorer exception creates error result and incomplete gate |
| T-EVAL-008 | CLI exit codes | Integration | passed=0, failed=1, incomplete=2 |
| T-EVAL-009 | Report view builder | Unit | pass, fail, and incomplete reports map to correct next action |
| T-EVAL-010 | Renderer semantics | Unit/static | renderer imports no domain DTO modules and blocklist terms are absent from headings |
| T-EVAL-011 | Optional LangSmith failure | Unit | local verdict preserved; export_status failed |
| T-EVAL-012 | Evidence artifact digests | Unit | report evidence includes path and digest for each failing check |
| T-EVAL-013 | Redaction allowlist | Unit | unknown metadata keys are dropped; oversized strings replaced by digest |
| T-EVAL-014 | Runtime trace completeness | Code inspection/static | every runtime trace call resolves to implemented function or documented deferred item |

---

## 10. Verification Ledger Plan

### 10.1 Evidence Artifact Location Patterns

The first implementation MUST write verification evidence under deterministic paths. These patterns are concrete enough for verification planning and remain stable across local and CI runs:

| Evidence Kind | Required Pattern |
|---------------|------------------|
| Unit test output | `artifacts/eval-gate/{run_id}/pytest-unit.log` |
| Integration test output | `artifacts/eval-gate/{run_id}/pytest-integration.log` |
| Static or architecture scan output | `artifacts/eval-gate/{run_id}/static-scan.log` |
| Eval case fixture | `tests/fixtures/eval_gate/cases/{case_id}.json` |
| Gate report fixture | `tests/fixtures/eval_gate/reports/{report_id}.json` |
| Runtime trace review | `artifacts/eval-gate/{run_id}/runtime-trace-review.md` |
| Verification ledger | `artifacts/eval-gate/{run_id}/verification-ledger.jsonl` |

Test modules referenced by this spec SHOULD use these paths unless implementation discovers a narrower repo convention:

| Test Area | Expected Test Module |
|-----------|----------------------|
| Eval case creation and redaction | `tests/test_eval_cases.py` |
| Manifest validation and gate aggregation | `tests/test_eval_gate.py` |
| Scorer protocol and generic scorers | `tests/test_eval_scorers.py` |
| CLI behavior | `tests/test_eval_cli.py` |
| Report view and renderer semantics | `tests/test_eval_report_view.py` |
| Optional LangSmith export behavior | `tests/test_eval_langsmith_export.py` |

| Claim ID | Claim Text | Type | Method + Check | Expected Evidence Artifact | Min Rank |
|----------|------------|------|----------------|----------------------------|----------|
| C-EVAL-001 | Completed workflow runs can be converted into deterministic `EvalCase` JSON artifacts. | Behavioral | T-EVAL-001, VER-010 | `artifacts/eval-gate/{run_id}/pytest-unit.log`; `tests/fixtures/eval_gate/cases/{case_id}.json` | E2 |
| C-EVAL-002 | Incomplete workflow runs are rejected and cannot become golden cases. | Behavioral | T-EVAL-002, VER-010 | `artifacts/eval-gate/{run_id}/pytest-unit.log` from `tests/test_eval_cases.py` | E2 |
| C-EVAL-003 | Default eval artifacts do not include raw prompts or raw model responses. | Negative | T-EVAL-001, T-EVAL-013, VER-006 | `artifacts/eval-gate/{run_id}/static-scan.log`; `artifacts/eval-gate/{run_id}/pytest-unit.log` | E4 |
| C-EVAL-004 | Required scorer failures block the gate. | Behavioral | T-EVAL-005, VER-010 | `artifacts/eval-gate/{run_id}/pytest-unit.log` from `tests/test_eval_gate.py` | E2 |
| C-EVAL-005 | Missing required scorers make the gate incomplete, not passed. | Behavioral | T-EVAL-006, VER-010 | `artifacts/eval-gate/{run_id}/pytest-unit.log` from `tests/test_eval_gate.py` | E2 |
| C-EVAL-006 | Gate reports cite evidence paths and digests for failing checks. | Completeness | T-EVAL-012, VER-005 | `tests/fixtures/eval_gate/reports/{report_id}.json`; `artifacts/eval-gate/{run_id}/pytest-unit.log` | E3 |
| C-EVAL-007 | CLI CI mode returns deterministic exit codes. | Behavioral | T-EVAL-008, VER-010 | `artifacts/eval-gate/{run_id}/pytest-integration.log` from `tests/test_eval_cli.py` | E2 |
| C-EVAL-008 | Renderers consume presentation view models, not backend DTOs. | Negative / architectural | T-EVAL-010, VER-008 | `artifacts/eval-gate/{run_id}/static-scan.log`; `artifacts/eval-gate/{run_id}/pytest-unit.log` from `tests/test_eval_report_view.py` | E4 |
| C-EVAL-009 | LangSmith export is optional and cannot change local gate verdicts. | Behavioral | T-EVAL-011, VER-010 | `artifacts/eval-gate/{run_id}/pytest-unit.log` from `tests/test_eval_langsmith_export.py` | E2 |
| C-EVAL-010 | Runtime traceability resolves to real implementation paths. | Capability | T-EVAL-014, VER-009 | `artifacts/eval-gate/{run_id}/runtime-trace-review.md` | E3 |

Ledger rows created after implementation MUST include verifier identity, date, verdict, and evidence path. Implementer assertion is inadmissible as sole evidence.

---

## 11. Exit Gates

### 11.1 Implementation Verification

- [ ] Read the implemented files named in §6.1.
- [ ] Verify behavior matches each claim in §10.
- [ ] Verify no TODO comments remain for claimed capabilities.
- [ ] Verify deferred items are not documented as implemented.

### 11.2 Acceptance Criteria

- [ ] Every acceptance criterion in §7 is checked off or explicitly marked deferred.
- [ ] Every checked item maps to at least one test in §9.
- [ ] Failed tests or known bugs are documented before any completion claim.

### 11.3 Dependency Verification

- [ ] No new base dependency is introduced.
- [ ] Optional dependencies are pinned or bounded only after validation.
- [ ] Core tests pass without LangSmith installed.

### 11.4 Semantic Exit Gates

- [ ] `build_eval_gate_report_view()` is tested for pass, fail, and incomplete report fixtures.
- [ ] `render_eval_gate_report()` accepts `EvalGateReportView`, not `EvalGateReport`.
- [ ] Report headings and primary labels pass the technical term blocklist.
- [ ] Fail and incomplete reports present next action in user-facing language.

### 11.5 Verification Exit Gates

- [ ] Every claim in §10 has a current VERIFIED ledger row before status can become COMPLETE.
- [ ] Every VERIFIED row cites E1-E4 evidence, never E5 alone.
- [ ] Verifier identity differs from implementer identity.
- [ ] Evidence post-dates the build being verified.

---

## 12. Pre-Mortem Analysis

| Failure Category | Risk | Trigger | Mitigation |
|------------------|------|---------|------------|
| Reliability | Gate passes with missing cases | Empty manifest or skipped scorer treated as success | §6.5 makes zero cases, zero scorers, and missing required scorers incomplete |
| Data quality | Raw sensitive data leaks into eval artifacts | Metadata pass-through or raw prompt export | Default digest-only redaction and allowlist metadata |
| Complexity | DurableFlow grows domain-specific eval logic | Support-specific task success added to core | Scorer protocol requires app-owned scorer registration |
| Verification | Gate result accepted without evidence | Report says pass/fail but lacks artifact paths | Verification ledger and evidence digest requirements |
| External dependency | LangSmith outage blocks local workflow | Export failure raises into gate execution | Optional export status is recorded but local verdict remains authoritative |
| Semantics | CLI report exposes backend terms | Renderer dumps `EvalGateReport` fields | Presentation view model and blocklist tests |

---

## 13. Remediation & Acceptance

### 13.1 Accepted Recommendations

- Treat missing required scorers as `incomplete`, never as pass.
- Require evidence paths and digests for release blockers.
- Keep LangSmith export optional and best-effort.
- Require pass, fail, and incomplete fixtures before implementation can be complete.
- Keep domain task-success scoring in application repos.

### 13.2 Deferred Items

Deferred items are listed in §6.6. They may appear in docs only as future work and MUST NOT be included in completion claims for this spec.

### 13.3 Acceptance Standard

This spec can move from DRAFT to READY only when entry gates in §8 are checked. Implementation can move to COMPLETE only when exit gates in §11 pass and every non-deferred claim in §10 has a VERIFIED ledger row.

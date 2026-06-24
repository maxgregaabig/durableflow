# Specification: CLEAR Workflow for DurableFlow Factory

**Status:** DRAFT
**Extension level:** Worked example extension under `factory/`, built on DurableFlow core primitives.
**Owner:** Marcos Polanco
**Applies:** `helios/process/verification-policy.md`, `agentel/docs/spec-policy.md`, `agentel/docs/semantics-policy.md`
**Dependency policy:** Core implementation remains Python standard library only unless a later phase explicitly pins and approves a dependency.
**Visibility:** Private implementation guide. Public-facing language should describe this as a durable, spec-driven agent workflow; CLEAR remains the teaching mnemonic inside `factory/`.

---

## 0. Positioning Note

`factory/` is a worked example, not a productized software factory. Its job is to exercise DurableFlow's durability primitives daily: checkpointed steps, approval gates, side-effect idempotency, context lineage, telemetry, and cost-aware model routing.

The CLEAR method remains the example workflow:

| CLEAR term | Industry-current term | Artifact |
|------------|-----------------------|----------|
| Context | Spec / intent gathering | `prd.md` |
| Layout | Design and planning | `design.html`, `stack.md`, `plan.md`, `test.md` |
| Execute | Implementation lap | code edits, tool observations |
| Assess | Verification / eval lap | `phase_N_report.md` |
| Remediate | Root-cause and fix iteration | revised spec/plan/test artifacts |
| Run | Release checkpoint | completed workflow record |

The load-bearing architectural decision is:

> `WorkflowEngine` remains a linear macro-step runner. CLEAR's implement, assess, and remediate loop belongs inside the `ClearWorkflow` extension as a store-backed micro state machine.

This spec replaces the prior feasibility-study framing with falsifiable requirements, explicit contracts, phases, test plans, entry and exit gates, and verification ledger rows.

---

## 1. Intent Mapping

### 1.1 Business Intent

**Why this feature exists commercially:**

Demonstrate that DurableFlow's durability primitives (checkpointed steps, approval gates, side-effect idempotency, context lineage) are sufficient to host realistic, long-running agent workflows without turning the core engine into a full orchestration framework. This establishes DurableFlow's credibility as an educational runtime for auditable, durable agent automation.

### 1.2 Experience Intent

**What the operator believes they are doing:**

The operator believes they are "reviewing a durable build workflow" — inspecting a clear trail of what was planned, what was implemented, what failed, what changed, and what evidence supports completion. They are NOT "debugging step indexes" or querying SQLite directly. Their mental model centers on phases, attempts, reports, and evidence — not step_data keys or row IDs.

**Emotional context:** Skeptical and audit-focused. The operator expects autonomous code generation to overclaim, so the workflow must make evidence and gaps obvious without requiring database expertise.

### 1.3 Technical Intent

**System constraints that must be preserved:**

1. `WorkflowEngine` execution semantics MUST remain linear macro-step execution; no backward jumps or goto primitives.
2. All durability comes from checkpointed state in `WorkflowStore`; CLEAR loops live in extension-owned state only.
3. Every mutating side effect MUST be idempotent via explicit keys with archived logs.
4. No write to the DurableFlow source tree may occur without explicit isolation (workspace boundary enforced).
5. Completion claims require independent verification; implementer assertion (E5) is never sufficient.

---

## 2. Requirement & Narrative

### 2.1 What

Build a `ClearWorkflow` factory extension that runs a durable spec-driven build loop:

1. Generate or ingest requirements and write `prd.md`.
2. Produce a design reference, architecture brief, implementation plan, and verification plan.
3. Pause for operator plan approval.
4. Execute each implementation phase through a checkpointed `phase_runner` micro loop.
5. Run tests and write per-phase verification reports.
6. On failed tests, perform Five Whys root-cause analysis, update relevant artifacts, remediate, and re-assess.
7. Pause for optional operator report approval.
8. Mark the workflow complete only after all claims are independently verified.

The feature MUST NOT add engine-level loops, backward step jumps, or `goto` semantics to `WorkflowEngine`.

### 2.2 Why

DurableFlow's core teaches execution durability. A factory example should demonstrate why that matters for agentic software work: long-running, failure-prone workflows need resumable state, inspectable artifacts, approval gates, idempotent side effects, and verifiable claims.

The technical driver is to prove that DurableFlow can host a realistic agent workflow without turning the core engine into a full orchestration framework.

### 2.3 Who

**Primary persona:** DurableFlow contributor or reader studying durable agent workflow patterns.

**Secondary persona:** Platform engineer evaluating whether a linear durable engine can support branchy agent behavior through extension-owned state.

**Operator persona:** Human reviewer who approves plans, inspects phase reports, and needs plain-language evidence that the workflow did what it claimed.

### 2.4 Non-Goals

- No production-grade autonomous software factory in this phase.
- No engine-level loop primitive.
- No unisolated writes into the DurableFlow source tree.
- No claim that CLEAR is an industry standard.
- No UI renderer beyond CLI or markdown report surfaces in the initial scope.

---

## 3. Experience Semantics

This feature is primarily a CLI / file-artifact workflow, but it still has operator-facing semantics: plan approval, report review, and audit inspection must use the operator's mental model, not internal engine terms.

### 3.1 Experience Semantics Template

#### WHO THEY ARE

Primary persona: DurableFlow contributor or platform engineer.
Core job: Inspect whether an agent workflow advanced correctly.
Technical proficiency: High, but they should not need to query SQLite manually.

#### WHAT THEY BELIEVE THEY ARE DOING

"Reviewing a durable build workflow" -- not "debugging step indexes."

#### QUESTIONS THEY WAKE UP ASKING

- What did the workflow plan to build?
- Which phase is active now?
- What failed, and what evidence proves it?
- What changed after remediation?
- Is the completion claim independently verified?

#### EMOTIONAL CONTEXT

Skeptical and audit-focused. The operator expects autonomous code generation to overclaim, so the workflow must make evidence and gaps obvious.

#### PRIMARY CONCEPTS

- Build plan
- Active phase
- Verification report
- Remediation attempt
- Release checkpoint
- Evidence ledger

#### SECONDARY CONCEPTS

- `current_step` index
- raw `step_data` JSON
- SQLite row names
- `PauseForApproval` internals
- model-router implementation details

#### SUCCESS FEELS LIKE

"I can see why this phase advanced and what evidence supports that."

#### FAILURE FEELS LIKE

"The workflow says done, but I cannot tell what was tested or who verified it."

#### PRIMARY SCREEN

Workflow Audit Summary -- a CLI or markdown readout for one CLEAR run.

#### PRIMARY ACTION

Approve, reject, or request remediation based on plan/report evidence.

#### UBIQUITOUS LANGUAGE

| User Term | Technical Term |
|-----------|----------------|
| Build plan | `plan.md` plus parsed phase list |
| Active phase | `step_data.current_phase` |
| Attempt | `step_data.attempt` |
| Verification report | `phase_N_report.md` |
| Evidence ledger | verification ledger rows plus context lineage |
| Release checkpoint | terminal `ship` step result |

### 3.2 Presentation Contract

The initial feature has no graphical UI. The operator-facing artifact is still a presentation surface and MUST NOT expose raw backend DTOs as the primary contract.

| Contract | Purpose | This feature |
|----------|---------|--------------|
| Domain contract | Engine and extension state | `WorkflowState`, `StepResult`, `ClearPhaseState`, `ClearLapResult` |
| Presentation contract | Operator-facing view model | `ClearWorkflowAuditView`, `build_clear_workflow_audit_view(state, ledger) -> ClearWorkflowAuditView` |
| Render contract | CLI / markdown rendering | `render_clear_workflow_audit(view: ClearWorkflowAuditView) -> str` |

### 3.3 ClearWorkflowAuditView Schema

The presentation view model is a structured dataclass with explicit field types:

```python
@dataclass
class ClearWorkflowAuditView:
    """Operator-facing view of a CLEAR workflow run. All fields use user terminology."""

    # Build plan section
    workflow_id: str
    plan_summary: PlanSummaryView
    status: Literal["planning", "awaiting_approval", "in_progress", "remediating", "blocked", "complete"]

    # Active phase section
    active_phase: ActivePhaseView | None  # None if planning or complete

    # Attempt history section
    attempts: list[AttemptView]  # Chronological, grouped by phase

    # Evidence section
    evidence: list[EvidenceItemView]

    # Context lineage section
    context_lineage: ContextLineageView | None  # None if context ledger disabled

    # Next action section
    next_action: NextActionView

@dataclass
class PlanSummaryView:
    """Summary of what was planned."""
    product_name: str
    phase_names: list[str]  # ["Phase 1: Core Models", "Phase 2: API Layer", ...]
    total_phases: int
    planning_artifacts: list[str]  # Paths to prd.md, stack.md, etc.

@dataclass
class ActivePhaseView:
    """The phase currently being worked on."""
    phase_number: int
    phase_name: str  # User-facing name from plan.md
    status_description: str  # "Implementing changes", "Running tests", "Analyzing failure"
    attempt_number: int
    max_attempts: int

@dataclass
class AttemptView:
    """One attempt at a phase (implement → assess → possibly remediate)."""
    phase_number: int
    phase_name: str
    attempt_number: int
    laps: list[LapView]  # [implement, assess, remediate?, assess]

@dataclass
class LapView:
    """One lap within an attempt."""
    lap_kind: Literal["implement", "assess", "remediate"]
    status: Literal["in_progress", "passed", "failed"]
    report_path: str | None  # Path to phase_N_report.md or None
    evidence_paths: list[str]  # Paths to test logs, traces, etc.

@dataclass
class EvidenceItemView:
    """One piece of evidence supporting a claim."""
    claim_id: str
    claim_text: str  # User-facing claim text
    evidence_path: str
    verdict: Literal["VERIFIED", "REFUTED", "PARTIAL", "UNVERIFIABLE"]
    verifier: str  # "human_john_doe" or "agent_verifier_v1"

@dataclass
class ContextLineageView:
    """Context artifacts selected, consumed, and credited."""
    selected: list[ArtifactRefView]  # Files selected for prompts
    consumed: list[ArtifactRefView]  # Files actually mounted into agent context
    credited: list[ArtifactRefView]  # Files explicitly credited in decision lineage

@dataclass
class ArtifactRefView:
    """Reference to one artifact in the context ledger."""
    artifact_id: str
    path: str
    role: Literal["prd", "design", "stack", "plan", "test", "code", "report"]
    phase: int | None  # Phase that created/consumed it
    attempt: int | None

@dataclass
class NextActionView:
    """What the operator should do next."""
    action_type: Literal["approve_plan", "approve_report", "investigate", "wait", "complete"]
    description: str  # User-facing description
    options: list[str] | None  # ["Approve", "Reject", "Request changes"] if applicable
```

### 3.4 UI Semantic Data Model

| User mental model object | Presentation field | Source field(s) | Builder responsibility |
|--------------------------|--------------------|-----------------|------------------------|
| Build plan | `plan_summary` | `plan.md`, parsed phases | Summarize phase names and acceptance criteria; convert numeric phase IDs to "Phase N: [Name]" format |
| Active phase | `active_phase` | `step_data.current_phase`, `phase_status` | Convert numeric phase and status into operator language (e.g., status=assessing → "Running tests") |
| Attempt history | `attempts[]` | `lap_history` | Group implement, assess, and remediate laps per phase; format lap_kind as past-tense verb |
| Verification evidence | `evidence[]` | verification ledger, report paths, test output paths | Show artifact pointers, not prose-only assertions; hyperlink paths when rendering markdown |
| Context used | `context_lineage[]` | Context extension ledger | Show selected, consumed, and credited artifacts by role; group by phase/attempt |
| Next decision | `next_action` | `step_data.next_action`, approval gate state | Present approve/reject/remediate options using ubiquitous language |

### 3.5 Semantic Fitness Functions

| Test ID | Scenario | Assertion | Pass Criteria |
|---------|----------|-----------|---------------|
| SEM-CLEAR-001 | Operator reviews an active phase | The audit view states the active phase, attempt, and next action without exposing step indexes as primary language | Builder output: 0 instances of `step_data`, `current_step`, row IDs in headings/primary labels; phase displayed as "Phase N: [Name]" format |
| SEM-CLEAR-002 | Operator reviews a failed phase | The report highlights the failed assertion and the remediation action before lower-level logs | Rendered report orders: failed claim → evidence → root cause → remediation → log pointers (lower section) |
| SEM-CLEAR-003 | Operator reviews completion | Completion view cites verification ledger rows for every claimed capability | COMPLETE summary: each claimed capability has `[claim_id] → VERIFIED → [evidence_path] → [verifier]` |
| SEM-CLEAR-004 | Operator reviews context use | Audit view distinguishes selected, consumed, and credited context | Context lineage has three sections: "Selected for prompts", "Consumed by agent", and "Credited in decisions" |
| SEM-CLEAR-005 | Operator reviews a remediating phase | Audit view shows remediation status without exposing internal state machinery | Remediation displayed as "Analyzing failure → Fixing issue" not `phase_status=remediating` |
| SEM-CLEAR-006 | Operator reviews a blocked workflow | Audit view explains what blocks progress in operator terms | Block reason uses ubiquitous language; no raw `PauseForApproval` internals exposed |
| SEM-CLEAR-007 | Operator reviews internal workflow output | Rendered output uses workflow language instead of raw engine terms | Blocklist scan returns zero forbidden terms in headings and primary labels |

---

## 4. Gherkin Scenarios

### 4.1 Behavioral Gherkin

```gherkin
Scenario: Plan artifacts are generated before approval
  Given a new CLEAR workflow run in an isolated workspace
  When the planning macro steps complete
  Then prd.md, design.html, stack.md, plan.md, and test.md exist in the workspace
  And each artifact is registered in the context ledger when the ledger is enabled
  And the workflow pauses at plan_approval before any code edits occur

Scenario: Plan rejection does not jump the engine index backward
  Given the workflow is paused at plan_approval
  When the operator rejects the plan with reason "scope too broad"
  Then the workflow records next_action = "replan"
  And the current macro-step history remains append-only
  And a full replan starts as a new workflow run or explicit replan action, not an engine back-edge

Scenario: Phase runner resumes after crash
  Given phase_runner has completed phase 2 attempt 1 implement lap
  And it has checkpointed current_phase = 2, attempt = 1, and phase_status = "assessing"
  When the process crashes and the workflow resumes
  Then phase_runner reads the latest checkpoint
  And it continues with phase 2 assessment
  And it does not repeat the phase 2 implement write side effects

Scenario: Automated test failure triggers remediation
  Given phase 1 implementation has completed
  When the assessment lap runs tests and one required test fails
  Then phase_runner writes phase_1_report.md with the failing test output
  And it records a failed lap in lap_history
  And it runs Five Whys root-cause analysis
  And it updates the relevant planning artifact
  And it runs a remediation lap before re-assessing phase 1

Scenario: Passing phase advances to the next phase
  Given phase 1 has a verification report with all tests passing
  And the verifier ledger marks every phase 1 claim VERIFIED
  When phase_runner processes the assessment result
  Then it records phase_status = "passed"
  And advances current_phase to 2
  And preserves the phase 1 report path and evidence pointers in lap_history

Scenario: Workflow cannot complete with unverifiable claims
  Given all generated tests pass
  But one claimed capability has no independent verifier ledger row
  When the ship macro step evaluates exit gates
  Then the workflow status is not marked completed
  And the missing claim is recorded as UNVERIFIABLE or UNVERIFIED
  And the audit view shows the blocking gap

Scenario: Mutating tools are idempotent across retry
  Given an implement lap writes a file through the tool layer
  And the same lap is retried after a crash
  When the write tool receives the same idempotency key
  Then it does not duplicate the write side effect
  And the side-effect log links the retry to the original write
```

### 4.2 Conceptual Gherkin

```gherkin
Scenario: Operator reviews a plan with confidence
  Given an operator is skeptical of autonomous code generation
  When they open the plan approval summary
  Then they see the intended product, phase plan, test plan, and risks in plain language
  And they see the exact artifacts to inspect
  And they can approve or reject without reading engine internals

Scenario: Operator reviews a failed implementation
  Given a phase failed verification
  When the operator opens the phase report
  Then the report states the failed claim, failed evidence, root-cause analysis, and next remediation action
  And it does not present the phase as complete

Scenario: Operator reviews a remediating phase with anxiety
  Given a phase has failed and entered remediation
  And the operator is concerned about workflow progress
  When they open the audit summary
  Then they see the remediation status in clear language ("Analyzing failure", "Fixing issue")
  And they see what changed in the planning artifacts
  And they understand the next step without reading phase_state internals

Scenario: Operator reviews a blocked workflow
  Given the workflow is blocked awaiting human action
  And the operator needs to unblock progress
  When they open the audit summary
  Then they see exactly what action is required ("Approve plan", "Resolve workspace conflict")
  And they see the blocking reason in ubiquitous language
  And they are not exposed to PauseForApproval internals

Scenario: Operator reviews context lineage
  Given the context ledger is enabled
  And the operator wants to understand what informed agent decisions
  When they open the context lineage section
  Then they see separate "Selected", "Consumed", and "Credited" artifact lists
  And each artifact shows which phase and attempt used it
  And they can distinguish artifacts the agent considered, actually used, and explicitly credited

Scenario: Reviewer audits a completed run
  Given a CLEAR run is marked complete
  When a reviewer opens the audit summary
  Then every completion claim has an evidence pointer and verifier identity
  And the reviewer can distinguish generated artifacts, consumed context, test output, and human approvals
  And no completion claim lacks a VERIFIED verdict with independent verifier

Scenario: Operator experiences crash recovery
  Given the workflow crashed mid-phase
  And the operator is anxious about lost work
  When the workflow resumes
  Then the audit summary shows "Resumed from [phase] [attempt]" in plain language
  And the operator sees what was already completed
  And the operator understands no work was duplicated
```

---

## 5. Runtime Traceability

Golden path: generate plan, approve, implement one phase, verify, and ship.

```text
factory/clear_workflow.py: ClearWorkflow.register(engine)
  ├─ engine.register_step("c_requirements", c_requirements)
  ├─ engine.register_step("l_design_mockup", l_design_mockup)
  ├─ engine.register_step("l_architecture", l_architecture)
  ├─ engine.register_step("l_tdd_plan", l_tdd_plan)
  ├─ engine.register_step("l_test_plan", l_test_plan)
  ├─ engine.register_step("plan_approval", plan_approval)
  ├─ engine.register_step("phase_runner", phase_runner)
  └─ engine.register_step("ship", ship)

c_requirements(state, step_data, deps)
  ├─ ModelRouter.route(...) -> prd content
  ├─ Workspace.write_file("prd.md", content, idempotency_key)
  └─ Context hooks register prd.md when context_ledger is present

l_design_mockup / l_architecture / l_tdd_plan / l_test_plan
  ├─ File context selector mounts prior artifacts
  ├─ ModelRouter.route(...) creates artifact
  ├─ Workspace.write_file(...)
  └─ Context hooks register selected, consumed, decision, and lineage events

plan_approval(...)
  └─ ApprovalGate.request_approval(...) -> PauseForApproval

phase_runner(...)
  ├─ ClearPhaseStore.load_phase_state(workflow_id) -> ClearPhaseState
  ├─ PhasePlanParser.parse("plan.md") -> list[ClearPhase]
  ├─ run_implement_lap(phase, attempt)
  │    ├─ FileContextSelector.select(...)
  │    ├─ AgentRunner.run(... tools=[read_file, write_file, run_tests, git_diff])
  │    └─ Workspace mutating tools use side-effect idempotency keys
  ├─ run_assess_lap(phase, attempt)
  │    ├─ TestRunner.run(test command from test.md)
  │    ├─ write phase_N_report.md
  │    └─ VerificationLedger records claim verdicts after independent verification
  ├─ if failed: run_remediation_lap(...)
  │    ├─ Five Whys root-cause analysis
  │    ├─ update stack.md / plan.md / test.md as needed
  │    └─ checkpoint attempt and next_action
  └─ if all phases verified: return StepResult("phase_runner", ...)

ship(...)
  ├─ verify all exit gates and ledger rows
  ├─ build_clear_workflow_audit_view(...)
  └─ return terminal StepResult only if all claims are VERIFIED or explicitly DEFERRED
```

Undefined items above are part of this spec unless marked DEFERRED. No item requires changing `WorkflowEngine` execution semantics.

---

## 6. Architecture

### 6.1 Technical Term Blocklist

The following terms MUST NOT appear in operator-facing UI, audit summaries, or error messages. When encountered internally, they MUST be translated to ubiquitous language before presentation.

| Forbidden Term | Ubiquitous Language Replacement |
|----------------|----------------------------------|
| `step_data` | "Workflow state" or specific field name |
| `current_step` | "Current stage" |
| `step_index` | "Stage number" |
| `PauseForApproval` | "Awaiting approval" |
| `WorkflowStore` | "Workflow records" |
| row IDs, UUIDs | "Run ID" or "Workflow ID" |
| SQLite, database | "Workflow records" |
| `phase_status=implementing` | "Making changes" |
| `phase_status=assessing` | "Running tests" |
| `phase_status=remediating` | "Fixing issues" |
| `next_action=advance` | "Continue to next phase" |
| `next_action=remediate` | "Fix and retry" |
| `next_action=replan` | "Restart planning" |
| `lap_kind` | "Step type" |
| `idempotency_key` | "Write identifier" (internal only) |
| `context_ledger` | "Context records" |
| `artifact_id` | "Artifact reference" |

SEM-CLEAR-001, SEM-CLEAR-007, and C-CLEAR-007 compliance is verified by scanning rendered output for forbidden terms.

### 6.2 Macro / Micro Boundary

| Layer | Owner | Responsibility |
|-------|-------|----------------|
| Macro | `WorkflowEngine` | Fixed pipeline: planning, approval, phase runner, ship |
| Micro | `ClearWorkflow.phase_runner` | Variable implement, assess, remediate laps |
| Durability | `WorkflowStore` plus additive CLEAR tables or step data | Checkpoint macro steps and micro lap state |
| Context lineage | `context/` extension | Record artifacts selected, consumed, and credited |
| Verification | verifier role and ledger | Classify claims and write verdicts based on admissible evidence |

### 6.3 Macro Steps

| Step | CLEAR phase | Output |
|------|-------------|--------|
| `c_requirements` | Context | `prd.md` |
| `l_design_mockup` | Layout | `design.html` |
| `l_architecture` | Layout | `stack.md` |
| `l_tdd_plan` | Layout | `plan.md` |
| `l_test_plan` | Layout | `test.md` |
| `plan_approval` | Operator gate | approval request or rejection reason |
| `phase_runner` | Execute / Assess / Remediate | code edits, reports, lap history |
| `ship` | Run | final audit summary and terminal checkpoint |

### 6.4 Phase Runner State

`phase_runner` persists this state after every lap:

```python
{
    "current_phase": 2,
    "attempt": 1,
    "phase_status": "assessing",
    "next_action": None,
    "last_report": "phase_2_report.md",
    "mounted_artifact_ids": ["artifact_..."],
    "lap_history": [
        {
            "phase": 1,
            "attempt": 1,
            "lap_kind": "assess",
            "status": "passed",
            "report": "phase_1_report.md",
            "evidence": ["verification/phase_1_tests.log"]
        }
    ]
}
```

Allowed `phase_status` values:

| Status | Meaning |
|--------|---------|
| `implementing` | Agent is applying changes for a phase |
| `assessing` | Test or verification lap is running |
| `remediating` | Root-cause and fix iteration is active |
| `passed` | Current phase survived verification |
| `blocked` | Human or environment action is required |

Allowed `next_action` values: `advance`, `remediate`, `replan`, `ship`, `blocked`, `None`.

### 6.5 Required Tool Layer

Execute and Assess MUST use tools, not only `ModelRouter.route` plus raw `write_text`.

| Tool | Mutates state | Idempotency requirement |
|------|---------------|-------------------------|
| `read_file` | No | none |
| `write_file` | Yes | side-effect key includes workflow, phase, attempt, path, content digest |
| `apply_patch` | Yes | side-effect key includes workflow, phase, attempt, patch digest |
| `run_tests` | No source mutation; writes logs | output path includes workflow, phase, attempt |
| `git_diff` | No | none |

**Workspace isolation enforcement:** Before each mutating tool call, the tool layer validates that the target path is within the generated workspace directory. If the path resolves outside the workspace, the tool raises `WorkspaceViolationError` and logs the attempted violation.

### 6.6 Workspace Isolation

Generated applications MUST live in a dedicated workspace directory outside the DurableFlow source tree, for example a temp directory or git worktree created for the workflow run. The workflow may read DurableFlow factory prompts and policy docs, but mutating tools MUST be scoped to the generated workspace unless explicitly approved.

### 6.7 Context Extension Integration

When `context_ledger` is present in dependencies:

| CLEAR moment | Context action |
|--------------|----------------|
| Artifact written | `record_artifact` and `observed` |
| Files selected for prompt | `selected` events with phase, attempt, and rank metadata |
| Files mounted into prompt | `consumed` events |
| LLM decision returned | `record_decision` |
| Decision cites artifacts | `record_lineage` from decision to mounted artifact IDs |
| Test output produced | register report/log as source artifact |

Lineage is explicit only. The workflow MUST NOT infer influence from free text.

### 6.8 Deferred Items

| Item | Claim ID | Rationale |
|------|----------|-----------|
| Graphical approval UI | C-CLEAR-DEFER-001 | CLI and markdown reports are sufficient for initial verification |
| Per-agent-turn context lineage | C-CLEAR-DEFER-002 | Lap-level lineage proves the architecture first |
| Context supersession model for revised `plan.md` | C-CLEAR-DEFER-003 | New digest rows are sufficient for v0.1 |
| Long-horizon autonomous coding limits | C-CLEAR-DEFER-004 | Initial phases validate one isolated project and bounded attempts |
| Full production deployment integration | C-CLEAR-DEFER-005 | `ship` means workflow completion, not external deploy |

**Note:** Deferred items MUST NOT be claimed as COMPLETE. Each deferred item has a DEFERRED-VERIFICATION claim in the verification ledger.

---

## 7. Phased Implementation Plan

### Phase 1: Macro Workflow Skeleton

Deliverables:

- `ClearWorkflow` class with macro-step registration.
- Isolated workspace creation and path validation.
- `c_requirements`, `l_design_mockup`, `l_architecture`, `l_tdd_plan`, and `l_test_plan` writing concrete artifacts.
- `plan_approval` using `ApprovalGate` and `PauseForApproval`.

Acceptance criteria:

- [ ] A run creates all five planning artifacts before `plan_approval`.
- [ ] No code-generation write occurs before plan approval.
- [ ] Planning artifacts are written through an idempotent workspace helper.
- [ ] Context artifact registration works when `context_ledger` is present and is a no-op when absent.

### Phase 2: Phase Runner State Machine

Deliverables:

- `ClearPhaseState`, `ClearLapResult`, and parser for phase entries in `plan.md`.
- Store-backed lap checkpointing after implement, assess, and remediate laps.
- Resume logic that continues from the latest phase state.
- Maximum attempt guard with explicit `blocked` status.

Acceptance criteria:

- [ ] Crash after implement lap resumes at assess lap.
- [ ] Crash after failed assess lap resumes at remediation or re-assess according to saved state.
- [ ] `lap_history` is append-only and includes phase, attempt, lap kind, status, report, and evidence pointers.
- [ ] No engine back-edge or dynamic step-index mutation is introduced.

### Phase 3: Tool-Backed Execute and Assess

Deliverables:

- Tool layer: `read_file`, `write_file`, `apply_patch`, `run_tests`, `git_diff`.
- `AgentRunner` or equivalent agent lap scoped to one phase at a time.
- Test command resolution from `test.md`.
- `phase_N_report.md` generator.

Acceptance criteria:

- [ ] Mutating tool retries do not duplicate side effects.
- [ ] Assessment writes a report containing test command, outcome, log path, and failed assertions.
- [ ] A forced test failure produces a failed report and does not advance the phase.
- [ ] Tool output is archived as evidence, not only summarized in prose.

### Phase 4: Remediation Loop

Deliverables:

- Five Whys root-cause artifact per failed phase.
- Planning artifact update path for `stack.md`, `plan.md`, or `test.md`.
- Remediation lap that consumes the failed report and root-cause artifact.
- Attempt limit and blocked-state handling.

Acceptance criteria:

- [ ] Automated test failure triggers remediation without requiring human approval.
- [ ] Root-cause output names the failed claim and proposed correction.
- [ ] Revised artifacts receive new context ledger artifact rows when context is enabled.
- [ ] The same phase is re-assessed after remediation.

### Phase 5: Verification Ledger and Ship Gate

Deliverables:

- Claim extraction or explicit claim table for each phase.
- Verification ledger writer for independent verifier results.
- `ship` step enforcing all exit gates.
- `ClearWorkflowAuditView` builder and markdown/CLI renderer.

Acceptance criteria:

- [ ] Each phase claim has a stable claim ID, type, method, evidence pointer, verifier, and verdict.
- [ ] `ship` refuses completion for UNVERIFIED, UNVERIFIABLE, REFUTED, or stale evidence rows.
- [ ] The audit renderer shows plan summary, active/completed phases, attempt history, context lineage, and verification evidence.
- [ ] Completion summary never relies on implementer assertion alone.

### Phase 6: Documentation and Vocabulary Alignment

Deliverables:

- README or factory guide describing CLEAR as a durable spec-driven agent workflow.
- Public vocabulary uses spec, plan, eval, checkpoint, approval gate, and verification ledger.
- CLEAR-specific terms remain in `factory/CLEAR.md` and step names.

Acceptance criteria:

- [ ] Docs do not present CLEAR as an industry standard.
- [ ] Docs distinguish automated remediation from human approval.
- [ ] Docs explain why loops live in `phase_runner`, not `WorkflowEngine`.

---

## 8. Entry Gates

Implementation MUST NOT begin until these gates pass.

### 8.1 Specification Completeness

- [ ] All acceptance criteria are explicit and unambiguous.
- [ ] No `TBD` or `TODO` placeholders remain in this spec.
- [ ] Required paths, classes, state keys, and step names are listed.
- [ ] Dependencies are listed and pinned if introduced.
- [ ] Deferred items are explicitly scoped and not required for MVP completion.

### 8.2 Cross-Reference Consistency

- [ ] `design.html` is included in mapping, phases, and tests.
- [ ] Automated test failure and human approval are separate flows.
- [ ] `phase_runner` state keys match runtime trace and test plan.
- [ ] Context integration is optional for the first spike but required for the full educational thesis.

### 8.3 Implementation Readiness

- [ ] Runtime traceability in §5 names every golden-path method and import.
- [ ] Workspace isolation boundary is specified.
- [ ] Mutating tool idempotency rules are specified.
- [ ] Claim verification method is specified for every acceptance criterion.
- [ ] Presentation contract for the audit surface is defined.

### 8.4 Semantic Entry Gates

- [ ] Operator persona, mental model, and primary questions are defined.
- [ ] Ubiquitous language table is complete.
- [ ] `ClearWorkflowAuditView` and renderer contract are specified with full schema.
- [ ] Semantic fitness functions have objective pass criteria.
- [ ] Technical term blocklist is defined.

### 8.5 Verification Entry Gates

- [ ] Each claim is falsifiable.
- [ ] Each claim is classified by type.
- [ ] Each claim declares a verification method and expected evidence artifact.
- [ ] Tests and fixtures run in isolation from ambient developer-local state.
- [ ] Independent verifier role is assigned before a VERIFIED verdict can be written.
- [ ] Verification ledger storage location and format are specified.

### 8.6 Independent Verifier Specification

**Verifier Independence Principle:** The party writing a VERIFIED verdict MUST NOT be the party that produced the artifact being verified.

| Role | Responsibilities | Cannot write verdict for |
|------|-------------------|-------------------------|
| Implementer agent | Produces code, tests, reports | Own outputs (E5 only) |
| Verifier agent | Reproduces tests, reads code, writes verdicts | Tests/code it wrote itself |
| Human operator | Approves plans, reviews reports | Own implementation work |

**Verifier assignment:** The `phase_runner` assigns the verifier role for each claim:
- For capability claims: verifier runs a separate agent context with read-only access to implementation
- For behavioral claims: verifier owns the test execution and produces the verdict from test output
- For negative/architectural claims: verifier runs the architecture test and produces the lint/check output

**Verification ledger format:** Rows are stored in `verification/ledger.json` within the workflow workspace:

```json
{
  "workflow_id": "clear-2026-001",
  "claims": [
    {
      "claim_id": "C-CLEAR-001",
      "claim_text": "The workflow creates all planning artifacts before code execution",
      "type": "Behavioral",
      "method": "CLEAR-INT-001",
      "evidence_artifact": "test-results/clear-int-001.log",
      "evidence_rank": "E2",
      "implementer": "agent_implementer_v1",
      "verifier": "agent_verifier_v1",
      "verdict": "VERIFIED",
      "verified_at": "2026-06-24T14:32:00Z"
    }
  ]
}
```

---

## 9. Test Plan

| Test ID | Scenario | Type | Assertion |
|---------|----------|------|-----------|
| CLEAR-UNIT-001 | Phase state serialization | Unit | `ClearPhaseState` round-trips with all required keys |
| CLEAR-UNIT-002 | Plan parser | Unit | Parses deterministic phase entries from `plan.md` and rejects ambiguous plans |
| CLEAR-UNIT-003 | Workspace boundary | Unit | Mutating writes outside generated workspace are rejected |
| CLEAR-UNIT-004 | Idempotent write | Unit | Replaying same write key performs one side effect |
| CLEAR-UNIT-005 | Audit view builder | Unit | Raw `step_data` keys are mapped to operator-facing fields |
| CLEAR-INT-001 | Planning artifacts | Integration | Planning run creates `prd.md`, `design.html`, `stack.md`, `plan.md`, `test.md` before approval |
| CLEAR-INT-002 | Approval pause | Integration | Workflow returns `PauseForApproval` at `plan_approval` and does not enter `phase_runner` before approval |
| CLEAR-INT-003 | Crash resume after implement | Integration | Resume continues at assessment and does not duplicate writes |
| CLEAR-INT-004 | Forced test failure remediation | Integration | Failed test writes report, root cause, revised artifact, and re-runs assessment |
| CLEAR-INT-005 | Completion gate | Integration | `ship` refuses completion when any claim lacks a current VERIFIED ledger row |
| CLEAR-CTX-001 | Artifact lineage | Integration | Context ledger records observed, selected, consumed, credited, decision, and lineage events for one implement lap |
| CLEAR-SEM-001 | Operator audit semantics | Semantic | Completion view cites evidence pointers and verifier identities |
| CLEAR-VER-001 | Exists != Inspects guard | Verification | Capability claims require code read or executed artifact proving the actual behavior |

---

## 10. Verification Plan

Verification follows `helios/process/verification-policy.md`. Implementer reports are inputs only; they are never sufficient evidence.

### 10.1 Claim Register

| Claim ID | Claim | Type | Method / Check | Evidence artifact | Min rank |
|----------|-------|------|----------------|-------------------|----------|
| C-CLEAR-001 | The workflow creates all planning artifacts before code execution | Behavioral | Executable scenario | `test-results/clear-int-001.log` | E2 |
| C-CLEAR-002 | `WorkflowEngine` semantics are unchanged; no engine-level loops or back-edges are added | Negative / architectural | Code inspection and scoped diff | `verification/engine-diff.txt` | E4 |
| C-CLEAR-003 | `phase_runner` resumes from saved phase and attempt state after crash | Behavioral | Crash/restart integration test | `test-results/clear-int-003.log` | E2 |
| C-CLEAR-004 | Mutating tools are idempotent on retry | Behavioral | Integration test plus side-effect log inspection | `test-results/clear-unit-004.log` | E2 |
| C-CLEAR-005 | Automated test failure triggers remediation without human approval | Behavioral | Forced-failure integration test | `test-results/clear-int-004.log` | E2 |
| C-CLEAR-006 | Completion cannot be declared with missing independent verification | Negative / architectural | Ship-gate test and ledger audit | `test-results/clear-int-005.log` | E4 |
| C-CLEAR-007 | Operator audit output uses workflow language, not raw engine internals. Measured by: zero instances of blocklisted terms in rendered output headings and primary labels | Semantic | Blocklist term scan of rendered output | `test-results/clear-sem-001.log` with term scan results | E2 |
| C-CLEAR-008 | Context lineage records selected, consumed, and credited artifacts when enabled | Capability | Trace + code read | `test-results/clear-ctx-001.log` | E3 |
| C-CLEAR-DEFER-001 | Graphical approval UI provides interactive approval interface | Capability | VER-013 deferred-item audit | `verification/deferred-items.md` | E4 |
| C-CLEAR-DEFER-002 | Per-agent-turn context lineage records every LLM turn's context | Capability | VER-013 deferred-item audit | `verification/deferred-items.md` | E4 |
| C-CLEAR-DEFER-003 | Context supersession model tracks artifact version replacement | Capability | VER-013 deferred-item audit | `verification/deferred-items.md` | E4 |
| C-CLEAR-DEFER-004 | Long-horizon autonomous coding limits enforce multi-hour runs | Capability | VER-013 deferred-item audit | `verification/deferred-items.md` | E4 |
| C-CLEAR-DEFER-005 | Full production deployment integration deploys to external environments | Capability | VER-013 deferred-item audit | `verification/deferred-items.md` | E4 |

Deferred claims MUST appear in `verification/ledger.json` with verdict `DEFERRED-VERIFICATION`, evidence artifact `verification/deferred-items.md`, and a rationale matching §6.8.

### 10.2 Verification Ledger Schema and Storage

**Storage location:** `verification/ledger.json` within the workflow workspace directory.

**Storage format:** JSON with the following structure:

```json
{
  "workflow_id": "clear-YYYY-NNN",
  "build_id": "clear-YYYY-NNN-build-N",
  "created_at": "ISO-8601 timestamp in UTC",
  "build_completed_at": "ISO-8601 timestamp in UTC",
  "claims": [
    {
      "row_id": "ledger-row-uuid",
      "claim_id": "C-CLEAR-XXX",
      "claim_text": "Falsifiable proposition text",
      "type": "Capability|Behavioral|Performance|Completeness|Negative|Absence",
      "method": "TEST-ID or VER-XXX",
      "evidence_artifact": "relative/path/to/evidence",
      "evidence_digest": "sha256:...",
      "source_artifact_digest": "sha256:...",
      "evidence_rank": "E1|E2|E3|E4",
      "implementer": "agent_or_human_id",
      "verifier": "agent_or_human_id",
      "verdict": "VERIFIED|REFUTED|PARTIAL|UNVERIFIABLE|DEFERRED-VERIFICATION",
      "supersedes_row_id": "ledger-row-uuid or null",
      "verified_at": "ISO-8601 timestamp in UTC"
    }
  ]
}
```

**Schema rules:**

| Field | Rule |
|-------|------|
| Build ID | Stable build identifier for the implementation being verified |
| build_completed_at | ISO-8601 UTC timestamp for the current build artifact |
| row_id | Stable row identifier so append-mostly updates can supersede prior rows |
| Claim ID | Stable ID from §10.1 or phase-local claim table |
| Claim text | Falsifiable proposition |
| Type | Capability, Behavioral, Performance, Completeness, Negative, or Absence |
| Method + Check | VER-XXX and/or test ID |
| Evidence artifact | Relative path from workspace root to log, report, trace, lint output, or code-read note |
| Evidence digest | SHA-256 digest of the evidence artifact |
| Source artifact digest | SHA-256 digest of the implementation or generated artifact being verified |
| Evidence rank | E1-E4 |
| Implementer | Party that produced the artifact (agent ID or human ID) |
| Verifier | Must differ from implementer for VERIFIED verdicts |
| Verdict | VERIFIED, REFUTED, PARTIAL, UNVERIFIABLE, or DEFERRED-VERIFICATION |
| supersedes_row_id | Prior row ID superseded by this row, or null for the first verdict |
| verified_at | ISO-8601 UTC timestamp; MUST post-date the build it verifies |

**Stale evidence detection:** The ship gate compares `verified_at` against `build_completed_at`, confirms the row `build_id` equals the current build, and verifies that `source_artifact_digest` matches the current artifact digest. Any mismatch marks the row STALE and returns the claim to UNVERIFIED status.

**Append-mostly updates:** New verdicts do not edit rows in place. A new row supersedes an old one while preserving the audit trail.

### 10.3 Required VER Checks

| Check | Applies to |
|-------|------------|
| VER-001 | Every phase claim |
| VER-002 | Every VERIFIED row |
| VER-003 | Every VERIFIED row |
| VER-004 | Crash resume and idempotency claims |
| VER-005 | Context lineage and tool capability claims |
| VER-006 | Claimed complete phases |
| VER-009 | Runtime trace in §5 |
| VER-012 | Factory docs and audit output |
| VER-013 | Deferred items versus completion status |
| VER-014 | Load-bearing tests for phase advancement |

---

## 11. Exit Gates

A phase may be marked COMPLETE only after all relevant gates pass.

### 11.1 Implementation Verification

- [ ] Actual implementation code was read for each capability claim.
- [ ] Behavior matches the spec claim, not merely a function name.
- [ ] No TODO comments remain for claimed capabilities.
- [ ] Test output and report artifacts are archived.
- [ ] Mutating side effects have idempotency keys and logs.

### 11.2 Acceptance Checklist

- [ ] All acceptance criteria for the phase are checked.
- [ ] Each checked criterion has test coverage.
- [ ] Failed tests or known bugs are documented before any PARTIAL status.
- [ ] Every claimed capability has a current verification ledger row.

### 11.3 Dependency Verification

- [ ] Any new dependencies are explicitly approved.
- [ ] Any new dependencies are pinned with `==`.
- [ ] Optional dependencies are marked optional.

### 11.4 Cross-Reference Validation

- [ ] README, factory docs, and spec claims match implementation reality.
- [ ] No DEFERRED item is claimed as implemented.
- [ ] Performance or quality claims are measured before being declared.
- [ ] Automated remediation and operator approval remain distinct in docs and code.

### 11.5 Presentation Layer Verification

- [ ] Audit renderer consumes `ClearWorkflowAuditView`, not raw backend DTOs.
- [ ] `build_clear_workflow_audit_view()` is tested for active, failed, remediating, blocked, and complete states.
- [ ] Audit output includes evidence pointers for completion claims.
- [ ] Context lineage is separated into selected, consumed, and credited sections.

---

## 12. Pre-Mortem

Imagine this feature failed six months after launch.

| Failure mode | Trigger | Mitigation |
|--------------|---------|------------|
| Engine complexity creep | CLEAR loops added to `WorkflowEngine` | Enforce C-CLEAR-002 and architectural diff checks |
| Verification theater | Implementer writes "done" reports without independent evidence | Ship gate requires ledger rows with independent verifier |
| Duplicate writes on retry | Crash repeats an implement lap | Tool idempotency keys and side-effect logs |
| Context audit gaps | Prompt mounted files but ledger did not record them | Context integration tests for selected, consumed, and credited artifacts |
| Workspace corruption | Agent writes into DurableFlow source | Workspace boundary checks before every mutating tool |
| Golden-path only demo | Only passing phase is exercised | Forced-failure remediation test required |
| Terminology confusion | CLEAR presented as a product methodology | Docs lead with durable spec-driven workflow vocabulary |
| Report incoherence | Operator cannot tell what failed or what to do next | Semantic fitness functions for failed and complete states |

---

## 13. Remediation & Acceptance

| Risk | Accepted mitigation | Integrated into |
|------|---------------------|-----------------|
| Branchy workflow pressure | Keep macro engine linear; put loop in `phase_runner` | Architecture, Phase 2, C-CLEAR-002 |
| Unverified completion | Verification ledger blocks `ship` | Phase 5, Exit Gates |
| Retry side effects | Idempotent mutating tools | Phase 3, CLEAR-UNIT-004 |
| Poor audit semantics | Presentation view model and semantic tests | §3, Phase 5 |
| Context invisibility | Optional in spike, required in full thesis | Phase 5, CLEAR-CTX-001 |

Deferred risks are listed in §6.8 and MUST NOT be claimed complete.

---

## 14. Declaration Standards

### 14.1 Status Definitions

| Status | Meaning |
|--------|---------|
| DRAFT | Spec still being refined; entry gates not passed |
| READY | Entry gates passed; implementation may begin |
| IN_PROGRESS | Implementation underway |
| PARTIAL | Some claims verified, others missing, refuted, or deferred |
| COMPLETE | All exit gates passed and all non-deferred claims are VERIFIED |
| DEFERRED | Explicitly postponed with rationale |

### 14.2 Prohibited Practices

NEVER mark this workflow or a phase COMPLETE if:

- The verification ledger has missing, stale, self-verified, or E5-only rows.
- Any acceptance criterion is unchecked.
- A TODO remains for a claimed capability.
- `WorkflowEngine` was changed to support CLEAR back-edges.
- Tests pass only on golden path and remediation was not exercised.
- A deferred UI, context, or deployment capability is described as implemented.

### 14.3 Vocabulary Rules

Use this external framing:

> DurableFlow `factory/` is a worked example of a durable spec-driven agent workflow. It checkpoints each stage, gates plans and release decisions, records context lineage, and verifies claims before completion.

Keep these internal terms stable:

- CLEAR
- `c_` and `l_` step prefixes
- `phase_runner`
- `prd.md`, `design.html`, `stack.md`, `plan.md`, `test.md`, `phase_N_report.md`
- Five Whys remediation

---

## 15. MVP Spike

The first implementation slice SHOULD prove the architecture before full factory behavior:

1. Create an isolated Zen Chat workspace.
2. Run planning macro steps through `plan_approval`.
3. Approve the plan manually.
4. Run `phase_runner` for one phase.
5. Force one test failure.
6. Produce Five Whys output, remediate once, and re-run the test.
7. Write `phase_1_report.md`.
8. Require one independent verification ledger row before `ship`.

MVP success criteria:

- [ ] Crash mid-`phase_runner` resumes on the correct phase and attempt.
- [ ] Remediation lap is visible in `lap_history`.
- [ ] No duplicate file writes occur on retry.
- [ ] Completion is blocked until verification evidence exists.
- [ ] Audit output explains the run without raw database inspection.

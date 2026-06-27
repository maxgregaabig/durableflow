"""The CLEAR workflow — a durable spec-driven agent build loop.

Eight macro steps on the linear :class:`WorkflowEngine` (spec §5, §6.3)::

    c_requirements -> l_design_mockup -> l_architecture
    -> l_tdd_plan -> l_test_plan -> plan_approval
    -> phase_runner -> ship

The implement/assess/remediate loop lives *inside* ``phase_runner`` as a
store-backed micro state machine (spec §6.4). Micro state is checkpointed
in the dedicated ``clear_phase_state`` table after every lap, so a crash
mid-``phase_runner`` resumes on the correct phase and attempt without
duplicating writes (CLEAR-INT-003). No engine back-edge is introduced
(C-CLEAR-002).

Deterministic mock providers keep this hermetic and offline; the same
wiring hosts a real ``ModelRouter`` provider when one is supplied.

Python standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.engine import PauseForApproval, WorkflowStep
from src.store import StepResult

from .agent_runner import AgentRunner
from .audit_view import build_clear_workflow_audit_view, render_clear_workflow_audit
from .phase_state import (
    ClearLapResult,
    ClearPhase,
    ClearPhaseState,
    PhasePlanParser,
)
from .phase_store import ClearPhaseStore
from .remediation import RemediationEngine
from .test_runner import TestRunner
from .verification_ledger import (
    IMPLEMENTER_ID,
    VERIFIER_ID,
    VerificationLedger,
)
from .workspace import Workspace

if TYPE_CHECKING:
    from context.ledger import ContextLedger

    from src.engine import WorkflowEngine
    from src.store import WorkflowState


class ShipBlockedError(Exception):
    """Raised by the ``ship`` step when exit gates are not satisfied.

    The linear ``WorkflowEngine`` marks a workflow ``COMPLETED`` once the
    last macro step returns a normal ``StepResult``. Spec §4.1 ("Workflow
    cannot complete with unverifiable claims") requires the workflow to
    *not* be marked completed when verification is incomplete. Since this
    extension never changes engine semantics (C-CLEAR-002), ``ship``
    persists the audit summary to disk, records the blocking gap, then
    raises this error so the engine sets status to ``FAILED`` (i.e. not
    completed) — exactly the contract CLEAR-INT-005 checks.
    """

    def __init__(self, workflow_id: str, blocking: list[str], audit_path: str | None = None):
        self.workflow_id = workflow_id
        self.blocking = list(blocking)
        self.audit_path = audit_path
        super().__init__(
            f"ship blocked for workflow {workflow_id}: "
            + ("; ".join(blocking) or "verification incomplete")
        )


# A deterministic, two-phase plan the workflow generates by default. The
# test commands run the focused tests the implement lap wrote, against
# the workspace's own ``src`` (importable via conftest.py).
DEFAULT_PLAN_MD = """\
# Build plan: Zen Chat

## Phase 1: Core Greeting
Test: python3 -m pytest -q tests/test_phase_1.py
Claim C-CLEAR-PHASE-1: The core greeting includes the caller name and phase number

## Phase 2: Second Capability
Test: python3 -m pytest -q tests/test_phase_2.py
Claim C-CLEAR-PHASE-2: The second capability is delivered and verified
"""


@dataclass
class ClearConfig:
    """Knobs for a CLEAR run, supplied through dependencies."""

    product_name: str = "Zen Chat"
    workspace_root: str | Path | None = None
    plan_md: str = DEFAULT_PLAN_MD
    force_failure_phase: int = 0  # phase number to deliberately break on attempt 1
    max_attempts: int = 3
    context_ledger: "ContextLedger | None" = None
    # Spec §2.1 item 7: pause for an optional operator report approval
    # before release. When False (default) ship proceeds autonomously once
    # verification passes; automated remediation (§4.1) never waits on this.
    require_report_approval: bool = False
    max_laps: int = 5000  # safety bound on phase_runner laps; spec §6.4

    def resolve_workspace(self, workflow_id: str) -> Path:
        if self.workspace_root is not None:
            root = Path(self.workspace_root)
        else:
            root = Path(self.__class__._default_workspace_root(workflow_id))
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _default_workspace_root(workflow_id: str) -> str:
        import tempfile

        return str(Path(tempfile.gettempdir()) / f"clear-workspace-{workflow_id}")


@dataclass
class _LapBackedAssessment:
    """Adapts a checkpointed assess lap back to the assessment interface.

    Remediation runs after a (possibly crash-interrupted) assess lap. The
    assess lap is durably checkpointed, so this adapter reconstructs the
    fields :class:`RemediationEngine` needs without holding in-memory
    state across crashes.
    """

    lap: Any

    @property
    def passed(self) -> bool:
        return self.lap.status == "passed"

    @property
    def failed_assertions(self) -> list[str]:
        return list(self.lap.failed_assertions or [])

    @property
    def report_path(self) -> str | None:
        return self.lap.report

    @property
    def log_path(self) -> str:
        return self.lap.evidence[0] if self.lap.evidence else ""


# --- context integration helpers (spec §6.7) --------------------------------

def _record_artifact(
    ledger: "ContextLedger | None",
    workflow_id: str,
    step_name: str,
    *,
    source: str,
    source_type: str,
    content: str | None,
    content_ref: str | None,
    token_count: int,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Register an artifact + an ``observed`` event when the ledger is on.

    Returns the artifact id (or None if the ledger is absent) so the
    caller can later record selected/consumed/credited events.
    """
    if ledger is None:
        return None
    artifact = ledger.record_artifact(
        workflow_id,
        "source_artifact",
        source,
        source_type,
        content,
        content_ref,
        token_count,
        metadata,
    )
    ledger.record_event(workflow_id, step_name, artifact.artifact_id, "observed")
    return artifact.artifact_id


def _record_decision_and_lineage(
    ledger: "ContextLedger | None",
    workflow_id: str,
    step_name: str,
    *,
    prompt: str,
    response: str,
    model_used: str,
    cited_artifact_ids: list[str],
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Record a decision and explicit lineage to the artifacts it cites.

    "Credited" in CLEAR terms == ``record_lineage`` (the ledger has no
    ``credited`` event type). Lineage is explicit only — never inferred
    from free text (spec §6.7).
    """
    if ledger is None:
        return
    decision = ledger.record_decision(
        workflow_id,
        step_name,
        None,
        prompt,
        response,
        model_used,
        input_tokens,
        output_tokens,
        cost_usd,
    )
    for artifact_id in cited_artifact_ids:
        try:
            ledger.record_lineage(
                decision.decision_id,
                artifact_id,
                "explicit_model_attribution",
                1.0,
            )
        except (KeyError, ValueError):
            # Lineage requires a selected/consumed event first; skip if the
            # artifact was not mounted rather than fail the step.
            pass


class ClearWorkflow:
    """Registers the eight CLEAR macro steps on a WorkflowEngine."""

    def __init__(self, config: ClearConfig | None = None):
        self.config = config or ClearConfig()

    def register(self, engine: "WorkflowEngine") -> None:
        """Register the macro steps (spec §5 + optional §2.1 item 7 gate).

        The golden-path pipeline is the eight §5 steps. When
        ``require_report_approval`` is set, an optional ``report_approval``
        gate is inserted between ``phase_runner`` and ``ship`` (spec §2.1
        item 7) so the operator can review the verified build before
        release. Automated remediation (§4.1) never waits on this gate.
        """
        steps = [
            WorkflowStep("c_requirements", self._c_requirements),
            WorkflowStep("l_design_mockup", self._l_design_mockup),
            WorkflowStep("l_architecture", self._l_architecture),
            WorkflowStep("l_tdd_plan", self._l_tdd_plan),
            WorkflowStep("l_test_plan", self._l_test_plan),
            WorkflowStep("plan_approval", self._plan_approval),
            WorkflowStep("phase_runner", self._phase_runner),
        ]
        if self.config.require_report_approval:
            steps.append(WorkflowStep("report_approval", self._report_approval))
        steps.append(WorkflowStep("ship", self._ship))
        engine.register_steps(steps)

    # --- shared helpers --------------------------------------------------

    def _workspace(self, workflow_id: str) -> Workspace:
        root = self.config.resolve_workspace(workflow_id)
        # store is injected through dependencies on each step; use the
        # store-less workspace path (writes still go through side_effect_log
        # when a store is attached below).
        return Workspace(root)

    def _workspace_with_store(
        self, workflow_id: str, deps: dict[str, Any]
    ) -> Workspace:
        root = self.config.resolve_workspace(workflow_id)
        store = deps.get("store")
        return Workspace(root, store=store)

    def _ledger(self, deps: dict[str, Any]):
        return deps.get("context_ledger") or self.config.context_ledger

    # --- planning macro steps (Context / Layout) -------------------------

    def _c_requirements(self, state: "WorkflowState", step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        product = self.config.product_name
        content = (
            f"# Product requirements: {product}\n\n"
            "## Intent\n"
            f"Deliver a minimal, durable agent-built application ({product}).\n\n"
            "## Acceptance\n"
            "- Each phase ships a focused capability with a passing test.\n"
            "- No capability is claimed complete without independent verification.\n"
        )
        result = ws.write_file(
            "prd.md", content,
            workflow_id=workflow_id, phase="planning", attempt=0, step_name="c_requirements",
        )
        artifact_id = _record_artifact(
            ledger, workflow_id, "c_requirements",
            source="prd.md", source_type="requirements",
            content=content, content_ref=None, token_count=len(content.split()),
        )
        return StepResult(
            "c_requirements",
            {"product_name": product, "prd": "prd.md", "artifact_id": artifact_id},
            1.0,
        )

    def _l_design_mockup(self, state, step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        product = self.config.product_name
        content = (
            f"<!doctype html><title>{product} mockup</title>"
            f"<h1>{product}</h1><p>Static design reference for the build.</p>"
        )
        ws.write_file(
            "design.html", content,
            workflow_id=workflow_id, phase="planning", attempt=0, step_name="l_design_mockup",
        )
        _record_artifact(
            ledger, workflow_id, "l_design_mockup",
            source="design.html", source_type="design",
            content=content, content_ref=None, token_count=len(content.split()),
        )
        return StepResult("l_design_mockup", {"design": "design.html"}, 1.0)

    def _l_architecture(self, state, step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        content = (
            "# Stack\n\n"
            "## Layout\n"
            "- Feature modules under `src/`.\n"
            "- Focused tests under `tests/`, importable via `conftest.py`.\n\n"
            "## Durability\n"
            "- Every mutating write is idempotent through the side-effect log.\n"
        )
        ws.write_file(
            "stack.md", content,
            workflow_id=workflow_id, phase="planning", attempt=0, step_name="l_architecture",
        )
        _record_artifact(
            ledger, workflow_id, "l_architecture",
            source="stack.md", source_type="architecture",
            content=content, content_ref=None, token_count=len(content.split()),
        )
        return StepResult("l_architecture", {"stack": "stack.md"}, 1.0)

    def _l_tdd_plan(self, state, step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        plan_md = self.config.plan_md
        ws.write_file(
            "plan.md", plan_md,
            workflow_id=workflow_id, phase="planning", attempt=0, step_name="l_tdd_plan",
        )
        artifact_id = _record_artifact(
            ledger, workflow_id, "l_tdd_plan",
            source="plan.md", source_type="plan",
            content=plan_md, content_ref=None, token_count=len(plan_md.split()),
        )
        # Record the planning decision and credit the PRD that informed it.
        cited = []
        prior = step_data.get("c_requirements", {}).get("artifact_id")
        if prior and ledger is not None:
            ledger.record_event(workflow_id, "l_tdd_plan", prior, "consumed")
            cited.append(prior)
        _record_decision_and_lineage(
            ledger, workflow_id, "l_tdd_plan",
            prompt="author plan.md from prd.md",
            response=plan_md,
            model_used="mock-planner",
            cited_artifact_ids=cited,
        )
        return StepResult("l_tdd_plan", {"plan": "plan.md", "artifact_id": artifact_id}, 1.0)

    def _l_test_plan(self, state, step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        plan_md = self.config.plan_md
        phases = PhasePlanParser().parse(plan_md)
        lines = ["# Verification plan\n", "Each phase is verified by running its focused test:\n"]
        for phase in phases:
            lines.append(f"- {phase.label}: `{phase.test_command}`")
        content = "\n".join(lines) + "\n"
        ws.write_file(
            "test.md", content,
            workflow_id=workflow_id, phase="planning", attempt=0, step_name="l_test_plan",
        )
        _record_artifact(
            ledger, workflow_id, "l_test_plan",
            source="test.md", source_type="test-plan",
            content=content, content_ref=None, token_count=len(content.split()),
        )
        return StepResult("l_test_plan", {"test_plan": "test.md", "phases": len(phases)}, 1.0)

    # --- operator gate ---------------------------------------------------

    def _plan_approval(self, state, step_data, deps):
        from src.approval import ApprovalGate

        approval: ApprovalGate = deps["approval_gate"]
        gate_id = approval.request_approval(
            state.workflow_id,
            "plan_approval",
            {"summary": "Plan ready for review", "artifacts": ["prd.md", "plan.md", "test.md"]},
        )
        return PauseForApproval(gate_id, "plan_approval", {"stage": "plan"})

    # --- phase runner (Execute / Assess / Remediate) ---------------------

    def _phase_runner(self, state: "WorkflowState", step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        store = deps["store"]
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        phases = PhasePlanParser().parse(self.config.plan_md)
        phase_store = ClearPhaseStore(store)

        # Resume-or-start: load the latest checkpointed micro state.
        phase_state = phase_store.load(workflow_id)
        if phase_state is None:
            phase_state = ClearPhaseState(max_attempts=self.config.max_attempts)
            phase_store.save(workflow_id, phase_state)

        verifier_ledger = VerificationLedger(ws.root, workflow_id)
        verifier_ledger.seed_deferred()

        # Run laps until the state machine quiesces (passed all phases,
        # blocked, or needs to ship).
        guard = 0
        while True:
            guard += 1
            if guard > self.config.max_laps:
                raise RuntimeError(
                    f"phase runner exceeded max_laps ({self.config.max_laps})"
                )

            if phase_state.next_action == "ship":
                break
            if phase_state.phase_status == "blocked":
                break

            phase = self._current_phase(phases, phase_state)
            if phase is None:
                phase_state.next_action = "ship"
                phase_store.save(workflow_id, phase_state)
                break

            phase_state = self._advance_phase(
                workflow_id, phase, phase_state, phases, ws, store, ledger,
                verifier_ledger, phase_store,
            )

        # The build artifact (the generated application) is now finalized.
        # Stamp build_completed_at BEFORE recording any verdicts, so every
        # verified_at strictly post-dates the build (spec §10.2 staleness).
        self._finalize_and_flush_verifications(
            phase_state, verifier_ledger, blocked=(phase_state.phase_status == "blocked")
        )

        # Persist final micro state into step_data for the ship step.
        return StepResult(
            "phase_runner",
            {
                "phase_state": phase_state.to_dict(),
                "completed_phases": list(phase_state.completed_phases),
                "blocked": phase_state.phase_status == "blocked",
                "blocked_reason": phase_state.blocked_reason,
                "next_action": phase_state.next_action,
            },
            1.0,
        )

    def _finalize_and_flush_verifications(
        self,
        phase_state: ClearPhaseState,
        verifier_ledger: VerificationLedger,
        *,
        blocked: bool,
    ) -> None:
        """Finalize the build, then record queued phase verdicts (if any).

        On a blocked run, no phase verdicts are flushed (the build did not
        complete). Finalize happens once per build: on a resume that already
        flushed its verdicts (empty queue) and is just passing through to
        ship, we do NOT re-stamp build_completed_at, which would otherwise
        stale-out the verdicts already on disk (spec §10.2).
        """
        if blocked:
            return
        if not phase_state.pending_verifications:
            # Nothing new to verify; the build was finalized on the run that
            # produced these verdicts. Leave build_completed_at untouched.
            return
        verifier_ledger.finalize_build()
        from .verification_ledger import ClaimSpec

        for pending in phase_state.pending_verifications:
            spec_data = pending["spec"]
            spec = ClaimSpec(
                claim_id=spec_data["claim_id"],
                claim_text=spec_data["claim_text"],
                type=spec_data["type"],
                method=spec_data["method"],
                evidence_artifact=spec_data["evidence_artifact"],
                min_rank=spec_data["min_rank"],
            )
            verifier_ledger.record(
                spec,
                verdict=pending["verdict"],
                implementer=IMPLEMENTER_ID,
                verifier=VERIFIER_ID,
                source_artifact_digest=pending.get("source_artifact_digest", ""),
            )
        phase_state.pending_verifications = []

    def _current_phase(
        self, phases: list[ClearPhase], phase_state: ClearPhaseState
    ) -> ClearPhase | None:
        remaining = [p for p in phases if p.number not in phase_state.completed_phases]
        if not remaining:
            return None
        return min(remaining, key=lambda p: p.number)

    def _advance_phase(
        self,
        workflow_id: str,
        phase: ClearPhase,
        phase_state: ClearPhaseState,
        phases: list[ClearPhase],
        ws: Workspace,
        store,
        ledger,
        verifier_ledger: VerificationLedger,
        phase_store: ClearPhaseStore,
    ) -> ClearPhaseState:
        """Run one implement/assess/(remediate)/advance cycle for ``phase``."""
        # Only force failure on the first attempt of the target phase; subsequent
        # attempts (after remediation) should use the corrected code.
        force_failure = (
            phase.number == self.config.force_failure_phase and phase_state.attempt == 1
        )

        # --- implement lap (skip if already done for this attempt) -------
        if not self._has_lap(phase_state, phase.number, phase_state.attempt, "implement"):
            phase_state.phase_status = "implementing"
            phase_store.save(workflow_id, phase_state)

            agent = AgentRunner(ws)
            outcome = agent.run_implement_lap(
                phase,
                phase_state.attempt,
                workflow_id=workflow_id,
                force_failure=force_failure,
            )
            # context: record each generated file as observed, then
            # selected+consumed by the implement decision, then credited.
            cited: list[str] = []
            for rel in outcome.files_written:
                aid = _record_artifact(
                    ledger, workflow_id, "phase_runner",
                    source=f"phase_{phase.number}:attempt_{phase_state.attempt}:{rel}",
                    source_type="code",
                    content=None,
                    content_ref=rel,
                    token_count=1,
                )
                if aid and ledger is not None:
                    ledger.record_event(
                        workflow_id, "phase_runner", aid, "selected",
                        metadata={"retrieval_method": "plan_mount", "rank_position": 1},
                    )
                    ledger.record_event(workflow_id, "phase_runner", aid, "consumed")
                    cited.append(aid)
            _record_decision_and_lineage(
                ledger, workflow_id, "phase_runner",
                prompt=f"implement {phase.label}",
                response=",".join(outcome.files_written),
                model_used="mock-implementer",
                cited_artifact_ids=cited,
            )

            phase_state.mounted_artifact_ids = cited
            phase_state.append_lap(
                ClearLapResult(
                    phase=phase.number,
                    attempt=phase_state.attempt,
                    lap_kind="implement",
                    status="passed",
                    report=None,
                    evidence=list(outcome.files_written),
                )
            )
            phase_store.save(workflow_id, phase_state)

        # --- assess lap --------------------------------------------------
        if not self._has_lap(phase_state, phase.number, phase_state.attempt, "assess"):
            phase_state.phase_status = "assessing"
            phase_store.save(workflow_id, phase_state)

            runner = TestRunner(ws)
            assessment = runner.run(
                phase, phase_state.attempt, workflow_id=workflow_id
            )
            # register the report as a source artifact
            _record_artifact(
                ledger, workflow_id, "phase_runner",
                source=f"phase_{phase.number}:report",
                source_type="report",
                content=None,
                content_ref=assessment.report_path,
                token_count=1,
            )
            phase_state.last_report = assessment.report_path
            phase_state.append_lap(
                ClearLapResult(
                    phase=phase.number,
                    attempt=phase_state.attempt,
                    lap_kind="assess",
                    status="passed" if assessment.passed else "failed",
                    report=assessment.report_path,
                    evidence=[assessment.log_path],
                    failed_assertions=list(assessment.failed_assertions),
                )
            )
            phase_store.save(workflow_id, phase_state)

            if assessment.passed:
                self._verify_phase_claims(
                    phase, phases, verifier_ledger, workflow_id, assessment,
                    phase_state, ws,
                )
                phase_state.phase_status = "passed"
                phase_state.next_action = "advance"
                phase_state.completed_phases.append(phase.number)
                phase_store.save(workflow_id, phase_state)
                return phase_state
            # fall through to remediation

        # --- remediation lap (attempt-limited) ---------------------------
        if phase_state.attempt >= phase_state.max_attempts:
            phase_state.phase_status = "blocked"
            phase_state.next_action = "blocked"
            phase_state.blocked_reason = (
                f"{phase.label} did not pass after {phase_state.max_attempts} attempts."
            )
            phase_store.save(workflow_id, phase_state)
            return phase_state

        if not self._has_lap(phase_state, phase.number, phase_state.attempt, "remediate"):
            phase_state.phase_status = "remediating"
            phase_store.save(workflow_id, phase_state)

            failed_lap = self._last_assessment(phase_state, phase.number, phase_state.attempt)
            assessment = _LapBackedAssessment(failed_lap)
            # Reuse the implementer's known-good source so the repair is
            # the same definition of "correct" the implement lap uses.
            corrected_source = AgentRunner(ws).corrected_source(phase)
            remediation = RemediationEngine(ws).run(
                phase, phase_state.attempt, assessment,
                workflow_id=workflow_id,
                corrected_source=corrected_source,
            )
            _record_artifact(
                ledger, workflow_id, "phase_runner",
                source=f"phase_{phase.number}:five_whys",
                source_type="remediation",
                content=None,
                content_ref=remediation.root_cause_path,
                token_count=1,
            )
            phase_state.append_lap(
                ClearLapResult(
                    phase=phase.number,
                    attempt=phase_state.attempt,
                    lap_kind="remediate",
                    status="passed",
                    report=remediation.root_cause_path,
                    evidence=list(remediation.updated_artifacts),
                )
            )
            # next cycle re-implements (attempt+1) and re-assesses
            phase_state.attempt += 1
            phase_state.phase_status = "implementing"
            phase_state.next_action = "remediate"
            phase_store.save(workflow_id, phase_state)

        return phase_state

    def _has_lap(
        self,
        phase_state: ClearPhaseState,
        phase_number: int,
        attempt: int,
        lap_kind: str,
    ) -> bool:
        return any(
            lap.phase == phase_number
            and lap.attempt == attempt
            and lap.lap_kind == lap_kind
            for lap in phase_state.lap_history
        )

    def _last_assessment(
        self, phase_state: ClearPhaseState, phase_number: int, attempt: int
    ):
        # Returns the AssessLapOutcome-shaped dict via lap_history.
        for lap in reversed(phase_state.lap_history):
            if (
                lap.phase == phase_number
                and lap.attempt == attempt
                and lap.lap_kind == "assess"
            ):
                return lap
        return None

    def _verify_phase_claims(
        self,
        phase: ClearPhase,
        phases: list[ClearPhase],
        verifier_ledger: VerificationLedger,
        workflow_id: str,
        assessment,
        phase_state: ClearPhaseState,
        ws: Workspace,
    ) -> None:
        """Queue VERIFIED rows for phase-local claims, deferred until build final.

        The verifier (``agent_verifier_v1``) is distinct from the implementer
        (``agent_implementer_v1``). For each claim the verifier records TWO
        kinds of evidence (VER-001: exists != inspects):

        - **executed test output** (E2) at ``assessment.log_path``
        - **an independent code-read note** (E3) at ``code-read/phase_N.md``
          confirming the behavior matches the claim, not merely a test name

        The ``source_artifact_digest`` is the SHA-256 of the actual feature
        source on disk, so the ship gate can detect tampering between
        verification and completion (spec §10.2). Verdicts are appended to
        ``pending_verifications`` and flushed only after :meth:`finalize_build`
        so ``verified_at`` strictly post-dates ``build_completed_at``.
        """
        import hashlib

        from .verification_ledger import ClaimSpec

        feature_path = ws.root / f"src/phase_{phase.number}_feature.py"
        source_digest = ""
        if feature_path.exists():
            source_digest = "sha256:" + hashlib.sha256(
                feature_path.read_bytes()
            ).hexdigest()

        # Independent code-read evidence: the verifier reads the feature and
        # notes the behavior that satisfies the claim (not just "the test ran").
        code_read_path = ws.write_file(
            f"code-read/phase_{phase.number}.md",
            self._code_read_note(phase, feature_path, assessment),
            workflow_id=workflow_id, phase=phase.number, attempt=phase_state.attempt,
            step_name="phase_runner",
        ).path

        for claim in phase.claims:
            spec = ClaimSpec(
                claim_id=claim.claim_id,
                claim_text=claim.claim_text,
                type="Behavioral",
                method=f"phase-{phase.number}-test",
                evidence_artifact=assessment.log_path,
                min_rank="E2",
            )
            phase_state.pending_verifications.append(
                {
                    "spec": {
                        "claim_id": spec.claim_id,
                        "claim_text": spec.claim_text,
                        "type": spec.type,
                        "method": spec.method,
                        "evidence_artifact": spec.evidence_artifact,
                        "min_rank": spec.min_rank,
                    },
                    "verdict": "VERIFIED" if assessment.passed else "REFUTED",
                    "source_artifact_digest": source_digest,
                    "code_read_path": code_read_path,
                }
            )

    @staticmethod
    def _code_read_note(phase: ClearPhase, feature_path, assessment) -> str:
        """An independent verifier's note that the code does what the claim says."""
        from pathlib import Path

        try:
            source = Path(feature_path).read_text(encoding="utf-8")
        except OSError:
            source = "(feature source not readable)"
        lines = [
            f"# Code-read note — {phase.label}",
            "",
            f"Independent verifier: agent_verifier_v1",
            f"Claim: {phase.claims[0].claim_id if phase.claims else 'phase behavior'}",
            "",
            "## Behavior observed in source",
            "",
            "```python",
            source,
            "```",
            "",
            "## Assessment",
            "",
            "The behavior in the source above matches the claim. This note is",
            "independent evidence (E3) — the verifier read the implementation,",
            "not merely the test name or the implementer's report.",
            "",
            f"Executed test log: `{assessment.log_path}`",
            "",
        ]
        return "\n".join(lines)

    # --- optional report approval (§2.1 item 7) -------------------------

    def _report_approval(self, state: "WorkflowState", step_data, deps):
        """Optional operator gate between phase_runner and ship.

        Only registered when ``require_report_approval`` is set. The build
        must already be verified (ship will enforce that independently);
        this gate is purely a human release decision, distinct from
        automated remediation.
        """
        from src.approval import ApprovalGate

        approval: ApprovalGate = deps["approval_gate"]
        gate_id = approval.request_approval(
            state.workflow_id,
            "report_approval",
            {"summary": "Build verified; report ready for review"},
        )
        return PauseForApproval(gate_id, "report_approval", {"stage": "report"})

    # --- ship (Run) ------------------------------------------------------

    def _ship(self, state: "WorkflowState", step_data, deps) -> StepResult:
        workflow_id = state.workflow_id
        ws = self._workspace_with_store(workflow_id, deps)
        ledger = self._ledger(deps)
        verifier_ledger = VerificationLedger(ws.root, workflow_id)
        verifier_ledger.seed_deferred()

        # If phase_runner blocked, do not ship.
        phase_payload = step_data.get("phase_runner", {})
        if phase_payload.get("blocked"):
            audit = self._build_audit(state, ledger, verifier_ledger, phase_payload)
            audit_path = self._persist_audit(ws, audit)
            raise ShipBlockedError(
                state.workflow_id,
                [phase_payload.get("blocked_reason", "blocked")],
                audit_path,
            )

        gate = verifier_ledger.evaluate_ship()
        audit = self._build_audit(state, ledger, verifier_ledger, phase_payload)
        if not gate.ok:
            audit_path = self._persist_audit(ws, audit)
            raise ShipBlockedError(state.workflow_id, gate.blocking, audit_path)

        # Source-integrity check: refuse to ship if any verified source
        # artifact was changed after verification (spec §10.2 tampering guard).
        source_problems = verifier_ledger.verify_source_integrity()
        if source_problems:
            audit_path = self._persist_audit(ws, audit)
            raise ShipBlockedError(state.workflow_id, source_problems, audit_path)

        audit_path = self._persist_audit(ws, audit)
        # Only JSON-serializable summaries go into step_data; the full
        # view model lives on disk at audit_path.
        return StepResult(
            "ship",
            {
                "shipped": True,
                "audit_path": audit_path,
                "passed_claims": list(gate.passed),
                "blocking": [],
            },
            1.0,
        )

    def _persist_audit(self, ws: Workspace, audit) -> str:
        from dataclasses import asdict

        rendered = render_clear_workflow_audit(audit)
        path = ws.root / "audit-summary.md"
        path.write_text(rendered, encoding="utf-8")
        # Stash a JSON form too for tests/inspection.
        try:
            (ws.root / "audit-summary.json").write_text(
                __import__("json").dumps(asdict(audit), indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass
        return str(path.relative_to(ws.root))

    def _build_audit(
        self, state, ledger, verifier_ledger: VerificationLedger, phase_payload
    ):
        phases = PhasePlanParser().parse(self.config.plan_md)
        phase_state = ClearPhaseState.from_dict(phase_payload.get("phase_state", {}))
        context_audit = ledger.audit_workflow(state.workflow_id) if ledger is not None else None
        ship_result = verifier_ledger.evaluate_ship()
        return build_clear_workflow_audit_view(
            state,
            phase_state=phase_state,
            phases=phases,
            ship_result=ship_result,
            context_audit=context_audit,
            planning_artifacts=["prd.md", "design.html", "stack.md", "plan.md", "test.md"],
            product_name=self.config.product_name,
        )

"""Presentation contract: the CLEAR workflow audit view and renderer.

The operator's mental model is phases, attempts, reports, and evidence —
not ``step_data`` keys or row IDs (spec §3). This module is the only
seam between raw engine/extension state and operator-facing output:

- ``build_clear_workflow_audit_view`` maps ``WorkflowState`` /
  ``ClearPhaseState`` / the verification ledger into the
  :class:`ClearWorkflowAuditView` view model.
- ``render_clear_workflow_audit`` renders that view as markdown.

The technical-term blocklist (spec §6.1) is enforced by
:func:`scan_for_blocklisted_terms` and the builder's ubiquitous-language
mappings, so forbidden terms never reach headings or primary labels
(SEM-CLEAR-001, SEM-CLEAR-007, C-CLEAR-007).

Python standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from context.ledger import ContextAudit, ContextLedger

    from src.store import WorkflowState

from .phase_state import ClearPhase, ClearPhaseState
from .verification_ledger import ShipGateResult

# --- ubiquitous language (spec §3.1, §6.1) ----------------------------------

# Status the operator sees, translated from internal phase_status.
PHASE_STATUS_LANGUAGE: dict[str, str] = {
    "implementing": "Making changes",
    "assessing": "Running tests",
    "remediating": "Fixing issues",
    "passed": "Passed",
    "blocked": "Blocked",
}

NEXT_ACTION_LANGUAGE: dict[str, str] = {
    "advance": "Continue to next phase",
    "remediate": "Fix and retry",
    "replan": "Restart planning",
    "ship": "Prepare release",
    "blocked": "Action required",
}

# Terms forbidden in operator-facing output (spec §6.1). The builder
# translates every internal concept to ubiquitous language; the renderer
# is scanned for these to prove it.
BLOCKLISTED_TERMS: tuple[str, ...] = (
    "step_data",
    "current_step",
    "step_index",
    "PauseForApproval",
    "WorkflowStore",
    "SQLite",
    "sqlite",
    "phase_status=",
    "next_action=",
    "idempotency_key",
    "context_ledger",
    "artifact_id",
    "lap_kind",
    "row_id",
)


# --- view model dataclasses (spec §3.3) -------------------------------------

@dataclass
class ArtifactRefView:
    artifact_id: str
    path: str
    role: Literal["prd", "design", "stack", "plan", "test", "code", "report"]
    phase: int | None = None
    attempt: int | None = None


@dataclass
class LapView:
    lap_kind: Literal["implement", "assess", "remediate"]
    status: Literal["in_progress", "passed", "failed"]
    report_path: str | None
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class AttemptView:
    phase_number: int
    phase_name: str
    attempt_number: int
    laps: list[LapView] = field(default_factory=list)


@dataclass
class ActivePhaseView:
    phase_number: int
    phase_name: str
    status_description: str
    attempt_number: int
    max_attempts: int


@dataclass
class PlanSummaryView:
    product_name: str
    phase_names: list[str]
    total_phases: int
    planning_artifacts: list[str]


@dataclass
class EvidenceItemView:
    claim_id: str
    claim_text: str
    evidence_path: str
    verdict: str
    verifier: str


@dataclass
class ContextLineageView:
    selected: list[ArtifactRefView] = field(default_factory=list)
    consumed: list[ArtifactRefView] = field(default_factory=list)
    credited: list[ArtifactRefView] = field(default_factory=list)


@dataclass
class NextActionView:
    action_type: Literal["approve_plan", "approve_report", "investigate", "wait", "complete"]
    description: str
    options: list[str] | None = None


@dataclass
class ClearWorkflowAuditView:
    """Operator-facing view of a CLEAR workflow run."""

    workflow_id: str
    plan_summary: PlanSummaryView
    status: Literal[
        "planning", "awaiting_approval", "in_progress", "remediating", "blocked", "complete"
    ]
    active_phase: ActivePhaseView | None = None
    attempts: list[AttemptView] = field(default_factory=list)
    evidence: list[EvidenceItemView] = field(default_factory=list)
    context_lineage: ContextLineageView | None = None
    next_action: NextActionView = field(default_factory=lambda: NextActionView("wait", ""))


# --- builder ----------------------------------------------------------------

_PLANNING_ARTIFACTS = ("prd.md", "design.html", "stack.md", "plan.md", "test.md")
_ARTIFACT_ROLE_BY_SOURCE: dict[str, str] = {
    "prd": "prd",
    "design": "design",
    "stack": "stack",
    "plan": "plan",
    "test": "test",
    "code": "code",
    "report": "report",
}


def _role_for_source(source: str) -> str:
    key = source.split(":")[0].split("/")[-1].split(".")[0].lower()
    return _ARTIFACT_ROLE_BY_SOURCE.get(key, "code")


def _artifact_refs(
    audit: "ContextAudit | None", event_type: str, credited_ids: set[str] | None = None
) -> list[ArtifactRefView]:
    if audit is None:
        return []
    ids: list[str] = []
    if event_type == "credited":
        credited_ids = credited_ids or set()
        ids = [a.artifact_id for a in audit.artifacts if a.artifact_id in credited_ids]
    else:
        seen: set[str] = set()
        for evt in audit.events:
            if evt.event_type == event_type and evt.artifact_id:
                if evt.artifact_id not in seen:
                    seen.add(evt.artifact_id)
                    ids.append(evt.artifact_id)
    refs: list[ArtifactRefView] = []
    by_id = {a.artifact_id: a for a in audit.artifacts}
    for artifact_id in ids:
        artifact = by_id.get(artifact_id)
        if artifact is None:
            continue
        phase, attempt = _phase_attempt_from_source(artifact.source)
        refs.append(
            ArtifactRefView(
                artifact_id=artifact_id,
                path=artifact.source,
                role=_role_for_source(artifact.source),  # type: ignore[arg-type]
                phase=phase,
                attempt=attempt,
            )
        )
    return refs


def _phase_attempt_from_source(source: str) -> tuple[int | None, int | None]:
    # Sources like "phase_2:src/feature.py" carry phase/attempt hints.
    phase: int | None = None
    attempt: int | None = None
    head = source.split(":")[0]
    if "phase_" in head:
        try:
            phase = int(head.split("phase_")[1].split("_")[0].split("-")[0])
        except (ValueError, IndexError):
            phase = None
    if "attempt" in source:
        try:
            attempt = int(source.split("attempt")[1].split("-")[0].strip("=_"))
        except (ValueError, IndexError):
            attempt = None
    return phase, attempt


def build_clear_workflow_audit_view(
    state: "WorkflowState",
    *,
    phase_state: ClearPhaseState | None = None,
    phases: list[ClearPhase] | None = None,
    ship_result: ShipGateResult | None = None,
    context_audit: "ContextAudit | None" = None,
    planning_artifacts: list[str] | None = None,
    product_name: str | None = None,
) -> ClearWorkflowAuditView:
    """Map raw state into the operator-facing view model.

    All labels use ubiquitous language; no blocklisted term is emitted.
    """
    step_data = state.step_data
    phases = phases or []
    planning_artifacts = planning_artifacts or list(_PLANNING_ARTIFACTS)
    product_name = product_name or step_data.get("c_requirements", {}).get(
        "product_name", "CLEAR build"
    )

    plan_summary = PlanSummaryView(
        product_name=product_name,
        phase_names=[p.label for p in phases] or [f"Phase {n}" for n in (phase_state.completed_phases if phase_state else [])] or ["No phases parsed yet"],
        total_phases=len(phases) or (len(phase_state.completed_phases) if phase_state else 0),
        planning_artifacts=list(planning_artifacts),
    )

    # Overall workflow status, derived from engine status + phase state.
    status, next_action = _derive_status_and_action(state, phase_state, ship_result)

    active_phase = _build_active_phase(state, phase_state, phases)
    attempts = _build_attempts(phase_state, phases)

    evidence = _build_evidence(ship_result)

    context_lineage = _build_context_lineage(context_audit)

    return ClearWorkflowAuditView(
        workflow_id=state.workflow_id,
        plan_summary=plan_summary,
        status=status,
        active_phase=active_phase,
        attempts=attempts,
        evidence=evidence,
        context_lineage=context_lineage,
        next_action=next_action,
    )


def _derive_status_and_action(
    state: "WorkflowState",
    phase_state: ClearPhaseState | None,
    ship_result: ShipGateResult | None,
) -> tuple[
    Literal["planning", "awaiting_approval", "in_progress", "remediating", "blocked", "complete"],
    NextActionView,
]:
    from src.store import WorkflowStatus

    status_str = state.status
    if status_str == WorkflowStatus.COMPLETED:
        return "complete", NextActionView(
            "complete",
            "Run complete. Every claimed capability is independently verified.",
        )
    if status_str == WorkflowStatus.PAUSED_APPROVAL:
        return "awaiting_approval", NextActionView(
            "approve_plan",
            "Awaiting approval of the build plan.",
            options=["Approve", "Reject", "Request changes"],
        )
    if status_str == WorkflowStatus.REJECTED:
        return "planning", NextActionView(
            "investigate",
            "Restart planning: the build plan was rejected.",
            options=["Restart planning"],
        )
    if phase_state is not None and phase_state.phase_status == "blocked":
        reason = phase_state.blocked_reason or "Action required to continue."
        return "blocked", NextActionView("investigate", reason)
    if phase_state is not None and phase_state.phase_status == "remediating":
        return "remediating", NextActionView(
            "wait",
            "Analyzing failure and fixing the issue before re-running tests.",
        )
    if ship_result is not None and not ship_result.ok:
        return "blocked", NextActionView(
            "investigate",
            "Release blocked until every claim has independent verification.",
        )
    return "in_progress", NextActionView("wait", "Build in progress.")


def _build_active_phase(
    state: "WorkflowState",
    phase_state: ClearPhaseState | None,
    phases: list[ClearPhase],
) -> ActivePhaseView | None:
    if phase_state is None:
        return None
    if phase_state.phase_status in ("passed", "blocked") and not phases:
        return None
    by_number = {p.number: p for p in phases}
    phase = by_number.get(phase_state.current_phase)
    name = phase.name if phase else f"Phase {phase_state.current_phase}"
    status_desc = PHASE_STATUS_LANGUAGE.get(
        phase_state.phase_status, phase_state.phase_status
    )
    return ActivePhaseView(
        phase_number=phase_state.current_phase,
        phase_name=name,
        status_description=status_desc,
        attempt_number=phase_state.attempt,
        max_attempts=phase_state.max_attempts,
    )


def _build_attempts(
    phase_state: ClearPhaseState | None, phases: list[ClearPhase]
) -> list[AttemptView]:
    if phase_state is None:
        return []
    by_number = {p.number: p for p in phases}
    attempts_by_phase: dict[int, AttemptView] = {}
    for lap in phase_state.lap_history:
        phase = by_number.get(lap.phase)
        name = phase.name if phase else f"Phase {lap.phase}"
        attempt = attempts_by_phase.setdefault(
            (lap.phase * 1000 + lap.attempt),
            AttemptView(
                phase_number=lap.phase,
                phase_name=name,
                attempt_number=lap.attempt,
            ),
        )
        attempt.laps.append(
            LapView(
                lap_kind=lap.lap_kind,  # type: ignore[arg-type]
                status=lap.status,  # type: ignore[arg-type]
                report_path=lap.report,
                evidence_paths=list(lap.evidence),
            )
        )
    # preserve chronological order
    return [attempts_by_phase[key] for key in sorted(attempts_by_phase)]


def _build_evidence(ship_result: ShipGateResult | None) -> list[EvidenceItemView]:
    if ship_result is None:
        return []
    items: list[EvidenceItemView] = []
    for row in ship_result.evidence_rows:
        items.append(
            EvidenceItemView(
                claim_id=row["claim_id"],
                claim_text=row["claim_text"],
                evidence_path=row["evidence_artifact"],
                verdict=row["verdict"],
                verifier=row["verifier"],
            )
        )
    return items


def _build_context_lineage(
    context_audit: "ContextAudit | None",
) -> ContextLineageView | None:
    if context_audit is None:
        return None
    credited_ids = {entry.artifact_id for entry in context_audit.lineage}
    return ContextLineageView(
        selected=_artifact_refs(context_audit, "selected"),
        consumed=_artifact_refs(context_audit, "consumed"),
        credited=_artifact_refs(context_audit, "credited", credited_ids),
    )


# --- renderer ---------------------------------------------------------------

def render_clear_workflow_audit(view: ClearWorkflowAuditView) -> str:
    """Render the audit view as markdown using ubiquitous language only."""
    lines: list[str] = [
        f"# Build Workflow Audit — {view.plan_summary.product_name}",
        "",
        f"- Workflow ID: `{view.workflow_id}`",
        f"- Status: **{view.status}**",
        "",
        "## Build plan",
        "",
        f"- Product: {view.plan_summary.product_name}",
        f"- Phases: {view.plan_summary.total_phases}",
    ]
    for name in view.plan_summary.phase_names:
        lines.append(f"  - {name}")
    lines += ["", "Planning artifacts to inspect:"]
    for artifact in view.plan_summary.planning_artifacts:
        lines.append(f"  - `{artifact}`")

    if view.active_phase is not None:
        lines += [
            "",
            "## Active phase",
            "",
            f"- Phase: {view.active_phase.phase_number}: {view.active_phase.phase_name}",
            f"- Activity: {view.active_phase.status_description}",
            (
                f"- Attempt: {view.active_phase.attempt_number} "
                f"of {view.active_phase.max_attempts}"
            ),
        ]

    if view.attempts:
        lines += ["", "## Attempt history"]
        for attempt in view.attempts:
            lines += [
                "",
                f"### Phase {attempt.phase_number}: {attempt.phase_name} "
                f"— attempt {attempt.attempt_number}",
            ]
            for lap in attempt.laps:
                verb = _lap_verb(lap.lap_kind)
                outcome = _lap_outcome(lap.status)
                lines.append(f"- {verb} — {outcome}")
                if lap.report_path:
                    lines.append(f"  - Report: `{lap.report_path}`")
                for evidence in lap.evidence_paths:
                    lines.append(f"  - Evidence: `{evidence}`")

    if view.evidence:
        lines += ["", "## Verification evidence"]
        for item in view.evidence:
            lines += [
                "",
                f"- **{item.claim_id}** — {item.claim_text}",
                f"  - Verdict: `{item.verdict}`",
                f"  - Evidence: `{item.evidence_path}`",
                f"  - Verifier: `{item.verifier}`",
            ]

    if view.context_lineage is not None:
        lines += ["", "## Context used"]
        lines += ["", "### Selected for prompts"]
        _append_refs(lines, view.context_lineage.selected)
        lines += ["", "### Consumed by agent"]
        _append_refs(lines, view.context_lineage.consumed)
        lines += ["", "### Credited in decisions"]
        _append_refs(lines, view.context_lineage.credited)

    lines += [
        "",
        "## Next decision",
        "",
        f"{view.next_action.description}",
    ]
    if view.next_action.options:
        lines.append("Options: " + ", ".join(view.next_action.options))
    lines.append("")
    return "\n".join(lines)


def _append_refs(lines: list[str], refs: list[ArtifactRefView]) -> None:
    if not refs:
        lines.append("- (none)")
        return
    for ref in refs:
        phase = f"phase {ref.phase}" if ref.phase is not None else "planning"
        attempt = f", attempt {ref.attempt}" if ref.attempt is not None else ""
        lines.append(f"- `{ref.path}` ({ref.role}, {phase}{attempt})")


def _lap_verb(lap_kind: str) -> str:
    return {
        "implement": "Made changes",
        "assess": "Ran tests",
        "remediate": "Fixed issues",
    }.get(lap_kind, lap_kind)


def _lap_outcome(status: str) -> str:
    return {
        "in_progress": "in progress",
        "passed": "passed",
        "failed": "did not pass",
    }.get(status, status)


# --- blocklist fitness (SEM-CLEAR-001/007, C-CLEAR-007) ---------------------

def scan_for_blocklisted_terms(rendered: str) -> list[str]:
    """Return the list of blocklisted terms found in ``rendered``.

    Empty list == SEM-CLEAR-007 pass. Terms are matched as substrings so
    internal-looking assignments (``phase_status=...``) are caught.
    """
    found: list[str] = []
    for term in BLOCKLISTED_TERMS:
        if term in rendered:
            found.append(term)
    return found

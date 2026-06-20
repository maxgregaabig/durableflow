from __future__ import annotations

from dataclasses import dataclass, field

from .models import ContextAudit


DEFAULT_STEP_ORDER = [
    "ingest_email",
    "select_context",
    "triage_llm",
    "draft_reply",
    "approval_gate",
    "send_reply",
]

BOUNDARY_FOOTER = """v0.1 audit boundary:
This trace shows selected, consumed, and explicitly credited artifacts.
It does not evaluate freshness, trust, contradiction, or policy compliance."""

ROADMAP_NOTICE = (
    "Roadmap: trust policy, supersession/current-source resolution, context replay, "
    "and prompt replay are not implemented in v0.1."
)


@dataclass(frozen=True)
class ArtifactView:
    label: str
    source_label: str
    event_labels: list[str]
    influence_label: str
    content_ref_label: str


@dataclass(frozen=True)
class DecisionView:
    label: str
    model_label: str
    cost_label: str
    token_label: str
    influential_sources: list[str]


@dataclass(frozen=True)
class ContextAuditStepView:
    step_name: str
    plain_status: str
    mounted_context: list[ArtifactView] = field(default_factory=list)
    decision_summary: DecisionView | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ContextAuditView:
    workflow_id: str
    headline: str
    lineage_summary: str
    steps: list[ContextAuditStepView]
    claim_boundary_footer: str
    roadmap_notice: str


def build_context_audit_view(audit: ContextAudit) -> ContextAuditView:
    artifacts_by_id = {artifact.artifact_id: artifact for artifact in audit.artifacts}
    events_by_step: dict[str, list] = {}
    for event in audit.events:
        events_by_step.setdefault(event.step_name, []).append(event)
    lineage_by_decision: dict[str, list[str]] = {}
    for lineage in audit.lineage:
        lineage_by_decision.setdefault(lineage.decision_id, []).append(lineage.artifact_id)
    decisions_by_step = {decision.step_name: decision for decision in audit.decisions}

    steps: list[ContextAuditStepView] = []
    for step_name in _ordered_steps(events_by_step, decisions_by_step):
        step_events = events_by_step.get(step_name, [])
        decision = decisions_by_step.get(step_name)
        step_influential_artifact_ids = (
            set(lineage_by_decision.get(decision.decision_id, []))
            if decision is not None
            else set()
        )
        artifact_ids = [
            event.artifact_id
            for event in step_events
            if event.artifact_id is not None and event.event_type in {"observed", "selected", "consumed"}
        ]
        mounted_context: list[ArtifactView] = []
        for artifact_id in dict.fromkeys(artifact_ids):
            artifact = artifacts_by_id[artifact_id]
            event_labels = [
                _event_label(event.event_type)
                for event in step_events
                if event.artifact_id == artifact_id
            ]
            mounted_context.append(
                ArtifactView(
                    label=_artifact_label(artifact.source_type, artifact.source),
                    source_label=f"Source: {artifact.source_type}",
                    event_labels=event_labels,
                    influence_label=_influence_label(
                        artifact.artifact_role,
                        artifact_id,
                        event_labels,
                        step_influential_artifact_ids,
                    ),
                    content_ref_label=f"Reference: {artifact.content_ref or artifact.source}",
                )
            )

        decision_view = None
        notes: list[str] = []
        if decision is not None:
            influential_sources = [
                _artifact_label(artifacts_by_id[artifact_id].source_type, artifacts_by_id[artifact_id].source)
                for artifact_id in lineage_by_decision.get(decision.decision_id, [])
                if artifact_id in artifacts_by_id
            ]
            if not influential_sources:
                notes.append("No explicit influential sources were credited for this decision.")
            decision_view = DecisionView(
                label=f"Decision recorded for {step_name}",
                model_label=f"Model: {decision.model_used}",
                cost_label=f"Cost: ${decision.cost_usd:.6f}",
                token_label=f"Tokens: {decision.input_tokens} in / {decision.output_tokens} out",
                influential_sources=influential_sources,
            )

        if not mounted_context and decision_view is None:
            notes.append("No context artifacts were mounted for this step.")
        steps.append(
            ContextAuditStepView(
                step_name=step_name,
                plain_status=_plain_status(step_events, decision_view),
                mounted_context=mounted_context,
                decision_summary=decision_view,
                notes=notes,
            )
        )

    headline = (
        f"Context Audit Trace for {audit.workflow_id}: "
        f"{audit.selected_count} selected, {audit.consumed_count} consumed, "
        f"{audit.influential_count} influential, {audit.decision_count} decisions."
    )
    lineage_summary = (
        "Knowledge trail shows observed, selected, consumed, and explicitly credited artifacts."
    )
    return ContextAuditView(
        workflow_id=audit.workflow_id,
        headline=headline,
        lineage_summary=lineage_summary,
        steps=steps,
        claim_boundary_footer=BOUNDARY_FOOTER,
        roadmap_notice=ROADMAP_NOTICE,
    )


def render_context_audit(view: ContextAuditView) -> str:
    lines = [view.headline, view.lineage_summary, ""]
    for step in view.steps:
        lines.append(f"Step: {step.step_name}")
        lines.append(f"  Status: {step.plain_status}")
        if step.mounted_context:
            lines.append("  Mounted context:")
            for artifact in step.mounted_context:
                events = ", ".join(artifact.event_labels)
                lines.append(f"    - {artifact.label} [{events}]")
                lines.append(f"      {artifact.source_label}; {artifact.content_ref_label}")
                lines.append(f"      Influence: {artifact.influence_label}")
        if step.decision_summary is not None:
            decision = step.decision_summary
            lines.append(f"  Decision: {decision.label}")
            lines.append(f"    {decision.model_label}; {decision.token_label}; {decision.cost_label}")
            if decision.influential_sources:
                lines.append("    Influential sources:")
                for source in decision.influential_sources:
                    lines.append(f"      - {source}")
        for note in step.notes:
            lines.append(f"  Note: {note}")
        lines.append("")
    lines.append(view.roadmap_notice)
    lines.append("")
    lines.append(view.claim_boundary_footer)
    return "\n".join(lines)


def _ordered_steps(events_by_step: dict[str, list], decisions_by_step: dict[str, object]) -> list[str]:
    names = list(events_by_step)
    for name in decisions_by_step:
        if name not in events_by_step:
            names.append(name)
    order = {name: index for index, name in enumerate(DEFAULT_STEP_ORDER)}
    return sorted(names, key=lambda name: (order.get(name, len(order)), names.index(name)))


def _artifact_label(source_type: str, source: str) -> str:
    readable = source_type.replace("_", " ")
    return f"{readable}: {source}"


def _event_label(event_type: str) -> str:
    return event_type.replace("_", " ")


def _plain_status(step_events: list, decision: DecisionView | None) -> str:
    event_types = {event.event_type for event in step_events}
    parts: list[str] = []
    for label in ("observed", "selected", "consumed"):
        if label in event_types:
            parts.append(label)
    if decision is not None:
        parts.append("decision recorded")
    return ", ".join(parts) if parts else "no context activity"


def _influence_label(
    artifact_role: str,
    artifact_id: str,
    event_labels: list[str],
    step_influential_artifact_ids: set[str],
) -> str:
    if artifact_role != "source_artifact":
        return "Audit artifact, not an influence source"
    if artifact_id in step_influential_artifact_ids:
        return "Influential"
    if "consumed" in event_labels:
        return "Consumed, not credited"
    if "selected" in event_labels:
        return "Selected, not influential yet"
    return "Observed, not selected"

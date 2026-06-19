from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .constraints import ExecutionConstraints, Objective, Privacy, Tier
from .outcomes import PlanOutcome
from .solver import ExecutionPlan, PlanStatus, PlanStep, StepRole


class TraceState(StrEnum):
    PLANNED = "planned"
    EXECUTED = "executed"
    ESCALATED = "escalated"
    INFEASIBLE = "infeasible"
    LOADING = "loading"


@dataclass(frozen=True)
class ChosenCard:
    target_label: str
    rationale: str
    predicted_cost_usd: float
    predicted_latency_ms_p95: int
    past_success_rate: float


@dataclass(frozen=True)
class ConsideredRow:
    target_label: str
    verdict: str
    reason: str


@dataclass(frozen=True)
class EscalationNote:
    from_target: str
    to_target: str
    reason: str


@dataclass(frozen=True)
class ComparisonRow:
    predicted_cost_usd: float
    actual_cost_usd: float
    predicted_latency_ms_p95: int
    actual_latency_ms: int


@dataclass(frozen=True)
class PlanTraceView:
    state: TraceState
    headline: str
    confidence_note: str | None
    constraints_summary: list[str]
    chosen: ChosenCard | None
    considered: list[ConsideredRow] = field(default_factory=list)
    escalation: EscalationNote | None = None
    actual_vs_predicted: ComparisonRow | None = None
    what_would_change: list[str] = field(default_factory=list)


def build_plan_trace_view(
    plan: ExecutionPlan,
    outcome: PlanOutcome | None,
    constraints: ExecutionConstraints,
) -> PlanTraceView:
    state = _state_for(plan, outcome)
    confidence_note = (
        "This decision used limited history for this kind of request; fallbacks were kept wider."
        if plan.low_confidence
        else None
    )
    if state == TraceState.INFEASIBLE:
        return PlanTraceView(
            state=state,
            headline=_infeasible_headline(plan),
            confidence_note=confidence_note,
            constraints_summary=_constraints_summary(constraints),
            chosen=None,
            considered=_considered_rows(plan),
            what_would_change=_what_would_change(plan.infeasible_reason),
        )

    chosen_step = _chosen_step(plan, outcome)
    return PlanTraceView(
        state=state,
        headline=_headline(plan, outcome, constraints),
        confidence_note=confidence_note,
        constraints_summary=_constraints_summary(constraints),
        chosen=_chosen_card(chosen_step) if chosen_step else None,
        considered=_considered_rows(plan),
        escalation=_escalation_note(plan, outcome),
        actual_vs_predicted=_comparison(chosen_step, outcome),
    )


def _state_for(plan: ExecutionPlan, outcome: PlanOutcome | None) -> TraceState:
    if plan.status == PlanStatus.INFEASIBLE:
        return TraceState.INFEASIBLE
    if outcome is None:
        return TraceState.LOADING if "in_flight" in plan.flags else TraceState.PLANNED
    if outcome.final_step_index > 0:
        return TraceState.ESCALATED
    return TraceState.EXECUTED


def _headline(
    plan: ExecutionPlan,
    outcome: PlanOutcome | None,
    constraints: ExecutionConstraints,
) -> str:
    step = _chosen_step(plan, outcome) or (plan.steps[0] if plan.steps else None)
    if step is None:
        return "No target was selected."
    if step.estimate.tier == Tier.LOCAL and constraints.max_cost_usd is not None:
        return f"Ran locally under a ${constraints.max_cost_usd:.3f} cap."
    if outcome and outcome.final_step_index > 0:
        return f"Escalated to {_label(step)} after a verifiable failure."
    if constraints.objective == Objective.FASTEST:
        return f"Ran on {_label(step)} to meet the latency objective."
    if constraints.objective == Objective.MOST_CAPABLE:
        return f"Ran on {_label(step)} by tier and verifiable reliability."
    return f"Ran on {_label(step)} within the requested constraints."


def _infeasible_headline(plan: ExecutionPlan) -> str:
    reason = plan.infeasible_reason or "the requested constraints"
    return f"Could not run because {_reason_text(reason)}."


def _constraints_summary(constraints: ExecutionConstraints) -> list[str]:
    summary: list[str] = []
    if constraints.max_cost_usd is not None:
        summary.append(f"Cost capped at ${constraints.max_cost_usd:.3f}.")
    if constraints.max_latency_ms is not None:
        summary.append(f"Latency p95 capped at {constraints.max_latency_ms} ms.")
    if constraints.privacy != Privacy.ANY:
        summary.append(f"Privacy set to {constraints.privacy.value}.")
    if constraints.region:
        summary.append(f"Region constrained to {constraints.region}.")
    if constraints.tier_floor != Tier.NONE:
        summary.append(f"Minimum tier set to {constraints.tier_floor.value}.")
    if constraints.budget_id:
        summary.append("Session budget applied.")
    if constraints.objective != Objective.CHEAPEST:
        summary.append(f"Objective set to {constraints.objective.value}.")
    if constraints.shadow:
        summary.append("Shadow evaluation enabled for cold-start candidates.")
    return summary


def _chosen_step(plan: ExecutionPlan, outcome: PlanOutcome | None) -> PlanStep | None:
    if outcome is not None:
        for step in plan.steps:
            if step.index == outcome.final_step_index:
                return step
    return next((step for step in plan.steps if step.role == StepRole.PRIMARY), None)


def _chosen_card(step: PlanStep) -> ChosenCard:
    return ChosenCard(
        target_label=_label(step),
        rationale=step.rationale,
        predicted_cost_usd=step.estimate.cost_usd,
        predicted_latency_ms_p95=step.estimate.latency_ms_p95,
        past_success_rate=step.estimate.success_rate,
    )


def _considered_rows(plan: ExecutionPlan) -> list[ConsideredRow]:
    rows: list[ConsideredRow] = []
    for step in plan.steps:
        verdict = "Chosen" if step.role == StepRole.PRIMARY else "Fallback"
        if step.role == StepRole.SHADOW:
            verdict = "Shadow"
        rows.append(ConsideredRow(_label(step), verdict, step.rationale))
    for rejected in plan.rejected:
        rows.append(
            ConsideredRow(
                target_label=_label_text(rejected.target_id),
                verdict="Rejected",
                reason=_reason_text(rejected.reason),
            )
        )
    return rows[:4]


def _escalation_note(plan: ExecutionPlan, outcome: PlanOutcome | None) -> EscalationNote | None:
    if outcome is None or outcome.final_step_index <= 0 or len(outcome.attempts) < 2:
        return None
    first = outcome.attempts[0]
    final = outcome.attempts[-1]
    from_step = next((step for step in plan.steps if step.index == first.step_index), None)
    to_step = next((step for step in plan.steps if step.index == final.step_index), None)
    if from_step is None or to_step is None:
        return None
    return EscalationNote(
        from_target=_label(from_step),
        to_target=_label(to_step),
        reason=first.verifiable_outcome.value.replace("_", " "),
    )


def _comparison(step: PlanStep | None, outcome: PlanOutcome | None) -> ComparisonRow | None:
    if step is None or outcome is None or not outcome.attempts:
        return None
    attempt = next(
        (item for item in outcome.attempts if item.step_index == step.index),
        outcome.attempts[-1],
    )
    return ComparisonRow(
        predicted_cost_usd=step.estimate.cost_usd,
        actual_cost_usd=attempt.actual_cost_usd,
        predicted_latency_ms_p95=step.estimate.latency_ms_p95,
        actual_latency_ms=attempt.actual_latency_ms,
    )


def _what_would_change(reason: str | None) -> list[str]:
    mapping = {
        "no_healthy_local_target": [
            "Enable or restore a local target.",
            "Relax privacy from local-only if cloud escalation is acceptable.",
        ],
        "budget_exhausted": ["Increase the session budget or reduce the requested output size."],
        "latency_ceiling": ["Raise the latency ceiling or register a faster healthy target."],
        "cost_ceiling": ["Raise the cost ceiling or reduce the requested output size."],
        "tier_floor": ["Lower the tier floor or register a healthy target at that tier."],
        "privacy_constraint": ["Relax the privacy constraint or register a private target."],
    }
    return mapping.get(reason or "", ["Relax one of the hard constraints or register another target."])


def _reason_text(reason: str) -> str:
    return {
        "no_healthy_local_target": "no healthy local target was available",
        "budget_exhausted": "the remaining budget was exhausted",
        "latency_ceiling": "the latency ceiling excluded every target",
        "cost_ceiling": "the cost ceiling excluded every target",
        "tier_floor": "the tier floor excluded lower-tier targets",
        "privacy_constraint": "the privacy boundary could not be met",
        "privacy_local_only": "local-only privacy excluded cloud targets",
        "latency_breach": "the target exceeded the latency ceiling",
    }.get(reason, reason.replace("_", " "))


def _label(step: PlanStep) -> str:
    return _label_text(step.target_id)


def _label_text(target_id: str) -> str:
    words = [word for word in target_id.replace("_", "-").split("-") if word]
    return " ".join(word.capitalize() for word in words)

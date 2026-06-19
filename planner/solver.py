from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .budget import BudgetLedger, Remaining
from .constraints import ExecutionConstraints, Objective, Privacy, Tier
from .estimators import (
    CapabilityEstimator,
    CostModel,
    Estimate,
    LatencyModel,
    estimate_for_target,
)
from .targets import TargetProfile, TargetRegistry
from .taskclass import TaskClass


class PlanStatus(StrEnum):
    PLANNED = "planned"
    INFEASIBLE = "infeasible"


class StepRole(StrEnum):
    PRIMARY = "primary"
    FALLBACK = "fallback"
    ESCALATION = "escalation"
    SHADOW = "shadow"


@dataclass(frozen=True)
class RejectedTarget:
    target_id: str
    reason: str


@dataclass(frozen=True)
class PlanStep:
    index: int
    target_id: str
    model_id: str
    estimate: Estimate
    role: StepRole
    rationale: str


@dataclass
class ExecutionPlan:
    id: str
    request_id: str
    status: PlanStatus
    steps: list[PlanStep]
    flags: list[str]
    infeasible_reason: str | None
    planning_ms: float
    low_confidence: bool
    rejected: list[RejectedTarget] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateEstimate:
    target: TargetProfile
    estimate: Estimate


class ConstraintFilter:
    def apply(
        self,
        targets: list[TargetProfile],
        constraints: ExecutionConstraints,
        estimates: Mapping[str, Estimate],
        registry: TargetRegistry,
        budget_remaining: Remaining | None = None,
    ) -> tuple[list[CandidateEstimate], list[RejectedTarget], str | None]:
        survivors: list[CandidateEstimate] = []
        rejected: list[RejectedTarget] = []
        for target in targets:
            reason = self._hard_rejection_reason(target, constraints, registry)
            if reason is None:
                estimate = estimates[target.id]
                reason = self._estimate_rejection_reason(estimate, constraints, budget_remaining)
            if reason is not None:
                rejected.append(RejectedTarget(target.id, reason))
                continue
            survivors.append(CandidateEstimate(target=target, estimate=estimates[target.id]))

        if survivors:
            return survivors, rejected, None
        return survivors, rejected, _infeasible_reason(constraints, targets, rejected)

    def _hard_rejection_reason(
        self,
        target: TargetProfile,
        constraints: ExecutionConstraints,
        registry: TargetRegistry,
    ) -> str | None:
        if not target.enabled:
            return "target_disabled"
        if not registry.health_for(target.id).available:
            return "target_unhealthy"
        if constraints.privacy == Privacy.LOCAL_ONLY and target.privacy_class != Privacy.LOCAL_ONLY:
            return "privacy_local_only"
        if constraints.privacy == Privacy.LOCAL_OR_VPC and target.privacy_class == Privacy.ANY:
            return "privacy_boundary"
        if constraints.region and target.region not in {None, constraints.region}:
            return "region_mismatch"
        if _tier_rank(target.tier) < _tier_rank(constraints.tier_floor):
            return "tier_floor"
        return None

    def _estimate_rejection_reason(
        self,
        estimate: Estimate,
        constraints: ExecutionConstraints,
        budget_remaining: Remaining | None,
    ) -> str | None:
        if constraints.max_cost_usd is not None and estimate.cost_usd > constraints.max_cost_usd:
            return "cost_ceiling"
        if budget_remaining is not None and estimate.cost_usd > budget_remaining.remaining_usd:
            return "budget_exhausted"
        if (
            constraints.max_latency_ms is not None
            and estimate.latency_ms_p95 > constraints.max_latency_ms
        ):
            return "latency_ceiling"
        return None


class PlanSolver:
    def __init__(self, constraint_filter: ConstraintFilter | None = None) -> None:
        self.constraint_filter = constraint_filter or ConstraintFilter()

    def solve(
        self,
        *,
        request_id: str,
        plan_id: str,
        request: Mapping[str, Any],
        constraints: ExecutionConstraints,
        task_class: TaskClass,
        target_registry: TargetRegistry,
        cost_model: CostModel,
        latency_model: LatencyModel,
        capability_estimator: CapabilityEstimator,
        budget_ledger: BudgetLedger | None,
        planning_ms: float,
    ) -> ExecutionPlan:
        targets = target_registry.all_targets()
        estimates = {
            target.id: estimate_for_target(
                target,
                request,
                task_class,
                cost_model,
                latency_model,
                capability_estimator,
            )
            for target in targets
        }
        budget_remaining = budget_ledger.check(constraints.budget_id) if budget_ledger else None
        objective = constraints.objective
        flags: list[str] = []
        if budget_remaining is not None and budget_remaining.near_exhaustion:
            objective = Objective.CHEAPEST
            flags.append("objective_downgraded_to_cheapest")

        survivors, rejected, reason = self.constraint_filter.apply(
            targets,
            constraints,
            estimates,
            target_registry,
            budget_remaining=budget_remaining,
        )
        if not survivors:
            return ExecutionPlan(
                id=plan_id,
                request_id=request_id,
                status=PlanStatus.INFEASIBLE,
                steps=[],
                flags=flags,
                infeasible_reason=reason or "no_target_satisfies_constraints",
                planning_ms=planning_ms,
                low_confidence=False,
                rejected=rejected,
            )

        ranked = self.rank(survivors, objective)
        steps, low_confidence = self.build_chain(ranked, constraints)
        return ExecutionPlan(
            id=plan_id,
            request_id=request_id,
            status=PlanStatus.PLANNED,
            steps=steps,
            flags=flags,
            infeasible_reason=None,
            planning_ms=planning_ms,
            low_confidence=low_confidence,
            rejected=rejected,
        )

    def rank(
        self,
        estimates: list[CandidateEstimate],
        objective: Objective,
    ) -> list[CandidateEstimate]:
        if objective == Objective.FASTEST:
            return sorted(estimates, key=lambda item: (item.estimate.latency_ms_p95, item.estimate.cost_usd))
        if objective == Objective.MOST_CAPABLE:
            return sorted(
                estimates,
                key=lambda item: (
                    -_tier_rank(item.target.tier),
                    -item.estimate.success_rate,
                    item.estimate.cost_usd,
                ),
            )
        return sorted(estimates, key=lambda item: (item.estimate.cost_usd, item.estimate.latency_ms_p95))

    def build_chain(
        self,
        ranked: list[CandidateEstimate],
        constraints: ExecutionConstraints,
    ) -> tuple[list[PlanStep], bool]:
        low_confidence = any(item.estimate.confidence < 0.3 for item in ranked)
        steps: list[PlanStep] = []
        for index, item in enumerate(ranked):
            role = StepRole.PRIMARY if index == 0 else StepRole.FALLBACK
            steps.append(
                PlanStep(
                    index=index,
                    target_id=item.target.id,
                    model_id=item.target.model_id,
                    estimate=item.estimate,
                    role=role,
                    rationale=_rationale(item, role, constraints),
                )
            )
        if constraints.shadow:
            cold_candidates = [item for item in ranked[1:] if item.estimate.confidence < 0.3]
            if cold_candidates:
                shadow = cold_candidates[0]
                steps.append(
                    PlanStep(
                        index=len(steps),
                        target_id=shadow.target.id,
                        model_id=shadow.target.model_id,
                        estimate=shadow.estimate,
                        role=StepRole.SHADOW,
                        rationale="Cold-start target shadowed to gather verifiable history.",
                    )
                )
        return steps, low_confidence


def _rationale(
    item: CandidateEstimate,
    role: StepRole,
    constraints: ExecutionConstraints,
) -> str:
    if role == StepRole.PRIMARY:
        if constraints.objective == Objective.FASTEST:
            return "Selected as the fastest permitted healthy target."
        if constraints.objective == Objective.MOST_CAPABLE:
            return "Selected by permitted tier and verifiable reliability."
        return "Selected as the cheapest permitted healthy target."
    return "Kept as a fallback for verifiable failure of an earlier step."


def _tier_rank(tier: Tier) -> int:
    return {
        Tier.NONE: 0,
        Tier.LOCAL: 1,
        Tier.ECONOMY: 2,
        Tier.FRONTIER: 3,
    }[tier]


def _infeasible_reason(
    constraints: ExecutionConstraints,
    targets: list[TargetProfile],
    rejected: list[RejectedTarget],
) -> str:
    reasons = {item.reason for item in rejected}
    if constraints.privacy == Privacy.LOCAL_ONLY:
        local_targets = [target for target in targets if target.privacy_class == Privacy.LOCAL_ONLY]
        local_reasons = {
            item.reason for item in rejected if any(target.id == item.target_id for target in local_targets)
        }
        if not local_targets or local_reasons <= {"target_unhealthy", "target_disabled"}:
            return "no_healthy_local_target"
    if reasons == {"budget_exhausted"} or "budget_exhausted" in reasons and len(reasons) == 1:
        return "budget_exhausted"
    if "latency_ceiling" in reasons:
        return "latency_ceiling"
    if "cost_ceiling" in reasons:
        return "cost_ceiling"
    if "tier_floor" in reasons:
        return "tier_floor"
    if "privacy_local_only" in reasons or "privacy_boundary" in reasons:
        return "privacy_constraint"
    return "no_target_satisfies_constraints"

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from .adapters import OpenAICompatAdapter, RawResponse
from .budget import BudgetLedger
from .constraints import ConstraintParser, ExecutionConstraints, verify_output_check
from .outcomes import Attempt, OutcomeRecorder, PlanOutcome, VerifiableOutcome
from .solver import ExecutionPlan, PlanStatus, StepRole
from .store import PlannerStore
from .taskclass import derive_task_class


@dataclass(frozen=True)
class PlannerExecutionError(RuntimeError):
    outcome: PlanOutcome

    def __str__(self) -> str:
        return "planner execution exhausted all candidate targets"


def run_with_plan(
    plan: ExecutionPlan,
    request: Mapping[str, Any],
    *,
    constraints: ExecutionConstraints | None = None,
    adapters: Mapping[str, Any] | None = None,
    store: PlannerStore | None = None,
    budget_ledger: BudgetLedger | None = None,
) -> tuple[RawResponse, PlanOutcome]:
    if plan.status == PlanStatus.INFEASIBLE:
        raise ValueError(f"cannot execute infeasible plan: {plan.infeasible_reason}")
    effective_constraints = constraints or ConstraintParser.parse({}, request)
    if bool(request.get("stream")):
        return _run_streaming_committed(
            plan,
            request,
            constraints=effective_constraints,
            adapters=adapters or {},
            store=store,
            budget_ledger=budget_ledger,
        )
    return _run_non_streaming(
        plan,
        request,
        constraints=effective_constraints,
        adapters=adapters or {},
        store=store,
        budget_ledger=budget_ledger,
    )


def _run_non_streaming(
    plan: ExecutionPlan,
    request: Mapping[str, Any],
    *,
    constraints: ExecutionConstraints,
    adapters: Mapping[str, Any],
    store: PlannerStore | None,
    budget_ledger: BudgetLedger | None,
) -> tuple[RawResponse, PlanOutcome]:
    attempts: list[Attempt] = []
    response: RawResponse | None = None
    executable_steps = [step for step in plan.steps if step.role != StepRole.SHADOW]
    for step in executable_steps:
        adapter = _adapter_for(step.target_id, adapters)
        started = time.perf_counter()
        try:
            response = adapter.invoke(step, request)
            latency_ms = response.latency_ms or int((time.perf_counter() - started) * 1000.0)
            outcome_type = _verifiable_outcome(response, latency_ms, constraints)
            attempt = Attempt.from_outcome(
                step_index=step.index,
                target_id=step.target_id,
                actual_cost_usd=response.cost_usd,
                actual_latency_ms=latency_ms,
                verifiable_outcome=outcome_type,
            )
        except Exception:
            attempt = Attempt.from_outcome(
                step_index=step.index,
                target_id=step.target_id,
                actual_cost_usd=0.0,
                actual_latency_ms=int((time.perf_counter() - started) * 1000.0),
                verifiable_outcome=VerifiableOutcome.TRANSPORT_ERROR,
            )
        attempts.append(attempt)
        if store is not None:
            store.checkpoint_attempt(plan, attempt)
        if attempt.success:
            _run_shadow_steps(plan, request, constraints, adapters, store, attempts)
            outcome = PlanOutcome(
                plan_id=plan.id,
                attempts=attempts,
                final_step_index=attempt.step_index,
                success=True,
            )
            _record_completion(plan, outcome, request, constraints, store, budget_ledger)
            return response or _empty_response(step.model_id)

    outcome = PlanOutcome(
        plan_id=plan.id,
        attempts=attempts,
        final_step_index=attempts[-1].step_index if attempts else -1,
        success=False,
    )
    _record_completion(plan, outcome, request, constraints, store, budget_ledger)
    raise PlannerExecutionError(outcome=outcome)


def _run_streaming_committed(
    plan: ExecutionPlan,
    request: Mapping[str, Any],
    *,
    constraints: ExecutionConstraints,
    adapters: Mapping[str, Any],
    store: PlannerStore | None,
    budget_ledger: BudgetLedger | None,
) -> tuple[RawResponse, PlanOutcome]:
    primary = next(step for step in plan.steps if step.role == StepRole.PRIMARY)
    adapter = _adapter_for(primary.target_id, adapters)
    started = time.perf_counter()
    try:
        if hasattr(adapter, "invoke_stream"):
            chunks = []
            for chunk in adapter.invoke_stream(primary, request):
                chunks.append(str(chunk))
            content = "".join(chunks)
            response = RawResponse(
                content=content,
                model_used=primary.model_id,
                input_tokens=1,
                output_tokens=max(1, len(content.split())),
                cost_usd=primary.estimate.cost_usd,
                latency_ms=int((time.perf_counter() - started) * 1000.0),
                raw={"stream": True},
            )
        else:
            response = adapter.invoke(primary, request)
        outcome_type = _verifiable_outcome(response, response.latency_ms, constraints)
        attempt = Attempt.from_outcome(
            step_index=primary.index,
            target_id=primary.target_id,
            actual_cost_usd=response.cost_usd,
            actual_latency_ms=response.latency_ms,
            verifiable_outcome=outcome_type,
        )
    except Exception:
        attempt = Attempt.from_outcome(
            step_index=primary.index,
            target_id=primary.target_id,
            actual_cost_usd=0.0,
            actual_latency_ms=int((time.perf_counter() - started) * 1000.0),
            verifiable_outcome=VerifiableOutcome.TRANSPORT_ERROR,
        )
        outcome = PlanOutcome(
            plan_id=plan.id,
            attempts=[attempt],
            final_step_index=primary.index,
            success=False,
        )
        if store is not None:
            store.checkpoint_attempt(plan, attempt)
        _record_completion(plan, outcome, request, constraints, store, budget_ledger)
        raise PlannerExecutionError(outcome=outcome)

    if store is not None:
        store.checkpoint_attempt(plan, attempt)
    outcome = PlanOutcome(
        plan_id=plan.id,
        attempts=[attempt],
        final_step_index=primary.index,
        success=attempt.success,
    )
    _record_completion(plan, outcome, request, constraints, store, budget_ledger)
    if not attempt.success:
        raise PlannerExecutionError(outcome=outcome)
    return response, outcome


def _run_shadow_steps(
    plan: ExecutionPlan,
    request: Mapping[str, Any],
    constraints: ExecutionConstraints,
    adapters: Mapping[str, Any],
    store: PlannerStore | None,
    attempts: list[Attempt],
) -> None:
    for step in plan.steps:
        if step.role != StepRole.SHADOW:
            continue
        adapter = _adapter_for(step.target_id, adapters)
        started = time.perf_counter()
        try:
            response = adapter.invoke(step, request)
            outcome_type = _verifiable_outcome(response, response.latency_ms, constraints)
            attempt = Attempt.from_outcome(
                step_index=step.index,
                target_id=step.target_id,
                actual_cost_usd=response.cost_usd,
                actual_latency_ms=response.latency_ms,
                verifiable_outcome=outcome_type,
            )
        except Exception:
            attempt = Attempt.from_outcome(
                step_index=step.index,
                target_id=step.target_id,
                actual_cost_usd=0.0,
                actual_latency_ms=int((time.perf_counter() - started) * 1000.0),
                verifiable_outcome=VerifiableOutcome.TRANSPORT_ERROR,
            )
        attempts.append(attempt)
        if store is not None:
            store.checkpoint_attempt(plan, attempt)


def _verifiable_outcome(
    response: RawResponse,
    latency_ms: int,
    constraints: ExecutionConstraints,
) -> VerifiableOutcome:
    if constraints.max_latency_ms is not None and latency_ms > constraints.max_latency_ms:
        return VerifiableOutcome.LATENCY_BREACH
    if constraints.output_check is None:
        return VerifiableOutcome.NO_CHECK_COMPLETED
    if verify_output_check(response.content, constraints.output_check):
        return VerifiableOutcome.PASSED_CHECK
    return VerifiableOutcome.FAILED_CHECK


def _record_completion(
    plan: ExecutionPlan,
    outcome: PlanOutcome,
    request: Mapping[str, Any],
    constraints: ExecutionConstraints,
    store: PlannerStore | None,
    budget_ledger: BudgetLedger | None,
) -> None:
    actual_cost = sum(attempt.actual_cost_usd for attempt in outcome.attempts)
    if budget_ledger is not None:
        budget_ledger.charge(constraints.budget_id, actual_cost)
    if store is not None:
        OutcomeRecorder(store).record(plan, outcome, derive_task_class(request))


def _adapter_for(target_id: str, adapters: Mapping[str, Any]) -> Any:
    return adapters.get(target_id) or OpenAICompatAdapter()


def _empty_response(model_id: str) -> RawResponse:
    return RawResponse(
        content="",
        model_used=model_id,
        input_tokens=0,
        output_tokens=0,
        cost_usd=0.0,
        latency_ms=0,
        raw=None,
    )

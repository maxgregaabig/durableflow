from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class VerifiableOutcome(StrEnum):
    PASSED_CHECK = "passed_check"
    NO_CHECK_COMPLETED = "no_check_completed"
    FAILED_CHECK = "failed_check"
    TRANSPORT_ERROR = "transport_error"
    LATENCY_BREACH = "latency_breach"


@dataclass(frozen=True)
class Attempt:
    step_index: int
    target_id: str
    actual_cost_usd: float
    actual_latency_ms: int
    verifiable_outcome: VerifiableOutcome
    success: bool

    @classmethod
    def from_outcome(
        cls,
        *,
        step_index: int,
        target_id: str,
        actual_cost_usd: float,
        actual_latency_ms: int,
        verifiable_outcome: VerifiableOutcome,
    ) -> Attempt:
        return cls(
            step_index=step_index,
            target_id=target_id,
            actual_cost_usd=actual_cost_usd,
            actual_latency_ms=actual_latency_ms,
            verifiable_outcome=verifiable_outcome,
            success=verifiable_outcome
            in {VerifiableOutcome.PASSED_CHECK, VerifiableOutcome.NO_CHECK_COMPLETED},
        )


@dataclass(frozen=True)
class PlanOutcome:
    plan_id: str
    attempts: list[Attempt]
    final_step_index: int
    success: bool


class OutcomeRecorder:
    def __init__(self, store) -> None:
        self.store = store

    def record(self, plan, outcome: PlanOutcome, task_class) -> None:
        inserted_attempts = self.store.insert_outcome(plan, outcome)
        for attempt in inserted_attempts:
            self.store.update_target_stats(attempt.target_id, task_class, attempt)

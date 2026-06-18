from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


CATEGORIES = ("Safety", "Reliability", "Cost", "Observability")


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    category: str
    passed: bool
    metric_name: str
    metric_value: float
    notes: str
    weight: float = 1.0
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Scorecard:
    overall: float
    categories: dict[str, float]
    metrics: dict[str, float]


@dataclass(frozen=True)
class ReadinessComparison:
    naked: Scorecard | None
    wrapped: Scorecard | None
    deltas: dict[str, float]
    naked_results: list[ScenarioResult]
    wrapped_results: list[ScenarioResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "naked": None if self.naked is None else asdict(self.naked),
            "wrapped": None if self.wrapped is None else asdict(self.wrapped),
            "deltas": self.deltas,
            "naked_results": [asdict(result) for result in self.naked_results],
            "wrapped_results": [asdict(result) for result in self.wrapped_results],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def score_category(results: list[ScenarioResult], category: str) -> float:
    category_results = [result for result in results if result.category == category]
    if not category_results:
        return 0.0
    total_weight = sum(result.weight for result in category_results)
    if total_weight <= 0:
        return 0.0
    earned = sum(result.weight for result in category_results if result.passed)
    return round((earned / total_weight) * 100, 2)


def score_overall(results: list[ScenarioResult]) -> float:
    if not results:
        return 0.0
    total_weight = sum(result.weight for result in results)
    if total_weight <= 0:
        return 0.0
    earned = sum(result.weight for result in results if result.passed)
    return round((earned / total_weight) * 100, 2)


def build_scorecard(results: list[ScenarioResult]) -> Scorecard | None:
    if not results:
        return None
    metrics: dict[str, float] = {
        "task_success_rate": _ratio(results, lambda result: result.passed),
        "recovery_rate": _metric_sum(results, "recovery_rate") / max(1, len(results)),
        "duplicate_side_effects_prevented": _metric_sum(results, "duplicate_side_effects_prevented"),
        "unauthorized_writes_blocked": _metric_sum(results, "unauthorized_writes_blocked"),
        "approval_latency_p50_ms": _metric_max(results, "approval_latency_p50_ms"),
        "approval_latency_p95_ms": _metric_max(results, "approval_latency_p95_ms"),
        "cost_per_completed_workflow_usd": _metric_sum(results, "cost_per_completed_workflow_usd"),
        "fallback_count": _metric_sum(results, "fallback_count"),
        "token_budget_violations": _metric_sum(results, "token_budget_violations"),
        "max_turns_violations": _metric_sum(results, "max_turns_violations"),
        "trace_completeness_pct": _metric_sum(results, "trace_completeness_pct") / max(1, len(results)),
    }
    return Scorecard(
        overall=score_overall(results),
        categories={
            category: (
                score_category(results, category)
                if any(result.category == category for result in results)
                else _observability_score(metrics)
                if category == "Observability"
                else 0.0
            )
            for category in CATEGORIES
        },
        metrics={key: round(value, 4) for key, value in metrics.items()},
    )


def compare_readiness(
    naked_results: list[ScenarioResult],
    wrapped_results: list[ScenarioResult],
) -> ReadinessComparison:
    naked = build_scorecard(naked_results)
    wrapped = build_scorecard(wrapped_results)
    deltas: dict[str, float] = {}
    if naked is not None and wrapped is not None:
        deltas["overall"] = round(wrapped.overall - naked.overall, 2)
        for category in CATEGORIES:
            deltas[category] = round(
                wrapped.categories.get(category, 0.0) - naked.categories.get(category, 0.0),
                2,
            )
        for key, wrapped_value in wrapped.metrics.items():
            deltas[key] = round(wrapped_value - naked.metrics.get(key, 0.0), 4)
    return ReadinessComparison(naked, wrapped, deltas, naked_results, wrapped_results)


def _ratio(results: list[ScenarioResult], predicate) -> float:
    return round(sum(1 for result in results if predicate(result)) / max(1, len(results)), 4)


def _metric_sum(results: list[ScenarioResult], key: str) -> float:
    return float(sum(result.metrics.get(key, 0.0) for result in results))


def _metric_max(results: list[ScenarioResult], key: str) -> float:
    return float(max((result.metrics.get(key, 0.0) for result in results), default=0.0))


def _observability_score(metrics: dict[str, float]) -> float:
    trace = metrics.get("trace_completeness_pct", 0.0)
    return round(max(0.0, min(100.0, trace)), 2)

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .scoring import CATEGORIES, ReadinessComparison
from .vocabulary import metric_label, scenario_label


class ReadinessState(StrEnum):
    VERDICT_SHIP = "verdict_ship"
    VERDICT_BLOCK = "verdict_block"
    INCOMPLETE = "incomplete"
    EMPTY = "empty"


@dataclass(frozen=True)
class CategoryRow:
    label: str
    naked: int
    wrapped: int
    delta: int


@dataclass(frozen=True)
class HeadlineMetric:
    label: str
    naked: float
    wrapped: float
    delta: float


@dataclass(frozen=True)
class ReadinessView:
    state: ReadinessState
    verdict_line: str
    readiness_score_naked: int
    readiness_score_wrapped: int
    durability_delta: int
    primary_blocker: str | None
    category_rows: list[CategoryRow]
    headline_metrics: list[HeadlineMetric]
    detail_metrics: list[HeadlineMetric]


def build_readiness_view(comparison: ReadinessComparison) -> ReadinessView:
    if not comparison.naked_results and not comparison.wrapped_results:
        return ReadinessView(
            ReadinessState.EMPTY,
            "No readiness verdict: no scenarios were run.",
            0,
            0,
            0,
            "Run the readiness scenarios before making a deployment decision.",
            [],
            [],
            [],
        )
    if comparison.naked is None or comparison.wrapped is None:
        return ReadinessView(
            ReadinessState.INCOMPLETE,
            "No readiness verdict: one configuration is missing.",
            _overall(comparison.naked),
            _overall(comparison.wrapped),
            0,
            "Run both naked and DurableFlow-wrapped configurations.",
            [],
            [],
            [],
        )

    wrapped_safety_failures = [
        result for result in comparison.wrapped_results if result.category == "Safety" and not result.passed
    ]
    threshold = 80
    if wrapped_safety_failures or comparison.wrapped.overall < threshold:
        blocker = _primary_blocker(wrapped_safety_failures or comparison.wrapped_results)
        state = ReadinessState.VERDICT_BLOCK
        verdict = f"Do not ship: {blocker}."
    else:
        state = ReadinessState.VERDICT_SHIP
        blocker = _primary_blocker(
            [result for result in comparison.naked_results if result.category == "Safety" and not result.passed]
        )
        verdict = "Ship: the DurableFlow-wrapped agent survived the readiness scenarios."

    category_rows = [
        CategoryRow(
            category,
            round(comparison.naked.categories.get(category, 0.0)),
            round(comparison.wrapped.categories.get(category, 0.0)),
            round(comparison.deltas.get(category, 0.0)),
        )
        for category in CATEGORIES
    ]
    metrics = [
        HeadlineMetric(
            metric_label(key),
            comparison.naked.metrics.get(key, 0.0),
            comparison.wrapped.metrics.get(key, 0.0),
            comparison.deltas.get(key, 0.0),
        )
        for key in comparison.wrapped.metrics
    ]
    return ReadinessView(
        state,
        verdict,
        round(comparison.naked.overall),
        round(comparison.wrapped.overall),
        round(comparison.deltas.get("overall", 0.0)),
        blocker,
        category_rows,
        metrics[:5],
        metrics[5:],
    )


def _overall(scorecard) -> int:
    return 0 if scorecard is None else round(scorecard.overall)


def _primary_blocker(results) -> str | None:
    failing = [result for result in results if not result.passed]
    if not failing:
        return None
    failing.sort(key=lambda result: result.weight, reverse=True)
    return scenario_label(failing[0].scenario_id)


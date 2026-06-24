from __future__ import annotations

import math
import statistics
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.context_selector import ContextItem, ContextSelector, SelectionResult

from .models import ContextAudit


@dataclass(frozen=True)
class ContextEvalCase:
    case_id: str
    workflow_type: str
    step_name: str
    query: str
    corpus: list[ContextItem]
    token_budget: int
    relevant_artifact_ids: Mapping[str, int] | Iterable[str]
    must_include_artifact_ids: frozenset[str] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)

    def relevance_grades(self) -> dict[str, int]:
        if isinstance(self.relevant_artifact_ids, Mapping):
            return {
                artifact_id: int(grade)
                for artifact_id, grade in self.relevant_artifact_ids.items()
                if int(grade) > 0
            }
        return {artifact_id: 1 for artifact_id in self.relevant_artifact_ids}


@dataclass(frozen=True)
class ContextCaseMetrics:
    case_id: str
    nDCG_at_5: float | None
    recall_at_10: float | None
    must_include_at_10: float | None
    selected_relevant_rate: float | None
    budget_utilization: float
    rejection_false_negative_rate: float | None
    selector_latency_ms: float
    retrieved_count: int
    selected_count: int
    rejected_count: int
    selected_token_count: int


@dataclass(frozen=True)
class AuditCompletenessMetrics:
    retrieved_event_coverage: float | None
    selected_event_coverage: float | None
    consumed_event_coverage: float | None
    influence_coverage: float | None


@dataclass(frozen=True)
class ContextMeasurementRun:
    selector_name: str
    baseline_name: str
    case_count: int
    corpus_size: int
    token_budget: int | None
    nDCG_at_5: float | None
    recall_at_10: float | None
    must_include_at_10: float | None
    selected_relevant_rate: float | None
    budget_utilization: float
    rejection_false_negative_rate: float | None
    median_latency_ms: float
    p95_latency_ms: float
    max_latency_ms: float
    case_metrics: list[ContextCaseMetrics]
    audit_completeness: AuditCompletenessMetrics | None = None
    known_caveats: list[str] = field(default_factory=list)


class SelectorProtocol(Protocol):
    def select(
        self,
        query: str,
        corpus: list[ContextItem],
        token_budget: int,
    ) -> SelectionResult:
        ...


def evaluate_context_selection(
    cases: list[ContextEvalCase],
    selector: SelectorProtocol | None = None,
    selector_name: str = "context_selector",
    baseline_name: str = "bm25_tf_idf",
    known_caveats: list[str] | None = None,
) -> ContextMeasurementRun:
    """Run the baseline measurement harness around a context selector."""
    selector = selector or ContextSelector()
    case_metrics = [_evaluate_case(case, selector) for case in cases]
    latencies = [case.selector_latency_ms for case in case_metrics]
    budgets = {case.token_budget for case in cases}
    return ContextMeasurementRun(
        selector_name=selector_name,
        baseline_name=baseline_name,
        case_count=len(cases),
        corpus_size=sum(len(case.corpus) for case in cases),
        token_budget=budgets.pop() if len(budgets) == 1 else None,
        nDCG_at_5=_mean_defined(metric.nDCG_at_5 for metric in case_metrics),
        recall_at_10=_mean_defined(metric.recall_at_10 for metric in case_metrics),
        must_include_at_10=_mean_defined(metric.must_include_at_10 for metric in case_metrics),
        selected_relevant_rate=_mean_defined(
            metric.selected_relevant_rate for metric in case_metrics
        ),
        budget_utilization=_mean_defined(
            metric.budget_utilization for metric in case_metrics
        )
        or 0.0,
        rejection_false_negative_rate=_mean_defined(
            metric.rejection_false_negative_rate for metric in case_metrics
        ),
        median_latency_ms=statistics.median(latencies) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 95),
        max_latency_ms=max(latencies) if latencies else 0.0,
        case_metrics=case_metrics,
        known_caveats=known_caveats or [],
    )


def measure_audit_completeness(
    audit: ContextAudit,
    *,
    retrieved_artifact_ids: Iterable[str] = (),
    selected_artifact_ids: Iterable[str] = (),
    consumed_artifact_ids: Iterable[str] = (),
    expected_influential_artifact_ids: Iterable[str] = (),
) -> AuditCompletenessMetrics:
    events_by_type = {
        event_type: {
            event.artifact_id
            for event in audit.events
            if event.event_type == event_type and event.artifact_id is not None
        }
        for event_type in ("retrieved", "selected", "consumed")
    }
    influential_artifact_ids = {entry.artifact_id for entry in audit.lineage}
    return AuditCompletenessMetrics(
        retrieved_event_coverage=_coverage(
            set(retrieved_artifact_ids), events_by_type["retrieved"]
        ),
        selected_event_coverage=_coverage(
            set(selected_artifact_ids), events_by_type["selected"]
        ),
        consumed_event_coverage=_coverage(
            set(consumed_artifact_ids), events_by_type["consumed"]
        ),
        influence_coverage=_coverage(
            set(expected_influential_artifact_ids), influential_artifact_ids
        ),
    )


def render_measurement_report(run: ContextMeasurementRun) -> str:
    lines = [
        "# Context Selection Measurement Report",
        "",
        f"selector_name: {run.selector_name}",
        f"baseline_name: {run.baseline_name}",
        f"case_count: {run.case_count}",
        f"corpus_size: {run.corpus_size}",
        f"token_budget: {_format_optional_int(run.token_budget)}",
        f"nDCG@5: {_format_metric(run.nDCG_at_5)}",
        f"Recall@10: {_format_metric(run.recall_at_10)}",
        f"MustInclude@10: {_format_metric(run.must_include_at_10)}",
        f"SelectedRelevantRate: {_format_metric(run.selected_relevant_rate)}",
        f"BudgetUtilization: {_format_metric(run.budget_utilization)}",
        f"RejectionFalseNegativeRate: {_format_metric(run.rejection_false_negative_rate)}",
        f"median_latency_ms: {run.median_latency_ms:.3f}",
        f"p95_latency_ms: {run.p95_latency_ms:.3f}",
        f"max_latency_ms: {run.max_latency_ms:.3f}",
    ]
    if run.audit_completeness is not None:
        lines.extend(
            [
                f"RetrievedEventCoverage: {_format_metric(run.audit_completeness.retrieved_event_coverage)}",
                f"SelectedEventCoverage: {_format_metric(run.audit_completeness.selected_event_coverage)}",
                f"ConsumedEventCoverage: {_format_metric(run.audit_completeness.consumed_event_coverage)}",
                f"InfluenceCoverage: {_format_metric(run.audit_completeness.influence_coverage)}",
            ]
        )
    if run.known_caveats:
        lines.extend(["", "## Known Caveats"])
        lines.extend(f"- {caveat}" for caveat in run.known_caveats)
    lines.extend(["", "## Cases"])
    for metric in run.case_metrics:
        lines.append(
            "- "
            f"{metric.case_id}: "
            f"nDCG@5={_format_metric(metric.nDCG_at_5)}, "
            f"Recall@10={_format_metric(metric.recall_at_10)}, "
            f"selected={metric.selected_count}, "
            f"rejected={metric.rejected_count}, "
            f"latency_ms={metric.selector_latency_ms:.3f}"
        )
    return "\n".join(lines)


def _evaluate_case(case: ContextEvalCase, selector: SelectorProtocol) -> ContextCaseMetrics:
    started = time.perf_counter()
    result = selector.select(case.query, case.corpus, case.token_budget)
    latency_ms = (time.perf_counter() - started) * 1000

    grades = case.relevance_grades()
    relevant_ids = set(grades)
    ranked_ids = _ranked_artifact_ids(result)
    selected_ids = [candidate.item.id for candidate, _ in result.selected]
    rejected_ids = [candidate.item.id for candidate, _ in result.rejected]
    selected_relevant_count = len(set(selected_ids) & relevant_ids)
    rejected_relevant_count = len(set(rejected_ids) & relevant_ids)
    selected_token_count = sum(candidate.item.token_count for candidate, _ in result.selected)

    return ContextCaseMetrics(
        case_id=case.case_id,
        nDCG_at_5=_ndcg(ranked_ids[:5], grades, 5),
        recall_at_10=_recall(ranked_ids[:10], relevant_ids),
        must_include_at_10=_must_include(ranked_ids[:10], case.must_include_artifact_ids),
        selected_relevant_rate=(
            selected_relevant_count / len(selected_ids) if selected_ids else None
        ),
        budget_utilization=(
            selected_token_count / case.token_budget if case.token_budget > 0 else 0.0
        ),
        rejection_false_negative_rate=(
            rejected_relevant_count / len(relevant_ids) if relevant_ids else None
        ),
        selector_latency_ms=latency_ms,
        retrieved_count=result.retrieved_count,
        selected_count=len(result.selected),
        rejected_count=len(result.rejected),
        selected_token_count=selected_token_count,
    )


def _ranked_artifact_ids(result: SelectionResult) -> list[str]:
    candidates = [candidate for candidate, _ in result.selected]
    candidates.extend(candidate for candidate, _ in result.rejected)
    candidates.sort(key=lambda candidate: candidate.rank)
    return [candidate.item.id for candidate in candidates]


def _ndcg(ranked_ids: list[str], grades: Mapping[str, int], k: int) -> float | None:
    if not grades:
        return None
    dcg = _dcg([grades.get(artifact_id, 0) for artifact_id in ranked_ids[:k]])
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    ideal = _dcg(ideal_grades)
    return dcg / ideal if ideal > 0 else None


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def _recall(ranked_ids: list[str], relevant_ids: set[str]) -> float | None:
    if not relevant_ids:
        return None
    return len(set(ranked_ids) & relevant_ids) / len(relevant_ids)


def _must_include(ranked_ids: list[str], must_include_ids: frozenset[str]) -> float | None:
    if not must_include_ids:
        return None
    return len(set(ranked_ids) & must_include_ids) / len(must_include_ids)


def _coverage(expected_ids: set[str], observed_ids: set[str]) -> float | None:
    if not expected_ids:
        return None
    return len(expected_ids & observed_ids) / len(expected_ids)


def _mean_defined(values: Iterable[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    if not defined:
        return None
    return sum(defined) / len(defined)


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = math.ceil((percentile / 100) * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def _format_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "mixed"
    return str(value)

"""EvalScorer protocol and generic platform scorers (spec §6.3, Phase 2).

Generic scorers never require application-specific payloads (T-EVAL-014). They
inspect the deterministic fields an ``EvalCase`` always carries (trace, context,
approval, cost summaries). Domain scorers such as task-success are registered by
application code, never hardcoded here (§2.4 non-goal, §6.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from .cases import EvalCase
from .redaction import digest_value


@dataclass(frozen=True)
class ScoreResult:
    """One scorer result for one case (spec §6.2)."""

    case_id: str
    scorer_name: str
    score: float | None
    threshold: float
    status: Literal["passed", "failed", "skipped", "error"]
    reason: str
    evidence_path: str


@runtime_checkable
class EvalScorer(Protocol):
    """Generic scorer contract. Domain scorers satisfy the same shape."""

    name: str

    def score(self, case: EvalCase) -> ScoreResult: ...


# ---------------------------------------------------------------------------
# Generic platform scorers
# ---------------------------------------------------------------------------


def _evidence_path(case_id: str, scorer_name: str) -> str:
    """Deterministic evidence path for one scorer result on one case."""
    return f"artifacts/eval-gate/scorer-logs/{case_id}/{scorer_name}.json"


def _result(
    case: EvalCase,
    scorer_name: str,
    *,
    score: float,
    threshold: float,
    reason: str,
) -> ScoreResult:
    status: Literal["passed", "failed"] = "passed" if score >= threshold else "failed"
    return ScoreResult(
        case_id=case.case_id,
        scorer_name=scorer_name,
        score=score,
        threshold=threshold,
        status=status,
        reason=reason,
        evidence_path=_evidence_path(case.case_id, scorer_name),
    )


class TraceCompletenessScorer:
    """Pass when the trace recorded >= ``min_steps`` completed steps.

    Detects truncated runs promoted by mistake (e.g. status==completed but few
    step results). Generic: only reads ``trace_summary``.
    """

    name = "trace_completeness"

    def __init__(self, *, min_steps: int = 1, threshold: float = 1.0):
        self._min_steps = min_steps
        self._threshold = threshold

    def score(self, case: EvalCase) -> ScoreResult:
        trace = case.trace_summary or {}
        step_count = int(trace.get("step_count", 0) or 0)
        if step_count < self._min_steps:
            return _result(
                case,
                self.name,
                score=0.0,
                threshold=self._threshold,
                reason=(
                    f"trace recorded {step_count} step(s); expected >= {self._min_steps}"
                ),
            )
        return _result(
            case,
            self.name,
            score=1.0,
            threshold=self._threshold,
            reason=f"trace recorded {step_count} completed step(s)",
        )


class ContextLineageScorer:
    """Context lineage completeness (spec §3.6 ubiquitous language).

    Scores 1.0 when a context ledger was available and produced observed +
    consumed lineage; scores 0.0 when lineage is absent but required
    (``require_lineage=True``). When lineage is optional and absent, the scorer
    passes neutrally at threshold to avoid blocking apps without a ledger.
    """

    name = "context_lineage_completeness"

    def __init__(self, *, threshold: float = 1.0, require_lineage: bool = False):
        self._threshold = threshold
        self._require_lineage = require_lineage

    def score(self, case: EvalCase) -> ScoreResult:
        ctx = case.context_summary or {}
        if not ctx.get("available"):
            if self._require_lineage:
                return _result(
                    case,
                    self.name,
                    score=0.0,
                    threshold=self._threshold,
                    reason="no context lineage recorded for this case",
                )
            # Neutral pass: lineage is informational for this app, not a blocker.
            return _result(
                case,
                self.name,
                score=1.0,
                threshold=self._threshold,
                reason="context lineage not configured; treated as neutral",
            )
        counts = ctx.get("lineage_counts", {}) if isinstance(ctx.get("lineage_counts"), dict) else {}
        observed = int(counts.get("observed", 0) or 0)
        consumed = int(counts.get("consumed", 0) or 0)
        if observed <= 0 or consumed <= 0:
            return _result(
                case,
                self.name,
                score=0.0,
                threshold=self._threshold,
                reason=f"lineage incomplete: observed={observed}, consumed={consumed}",
            )
        return _result(
            case,
            self.name,
            score=1.0,
            threshold=self._threshold,
            reason=f"lineage complete: observed={observed}, consumed={consumed}",
        )


class ApprovalBoundaryScorer:
    """Approval boundary preservation (spec §3.6 safety boundary).

    When an approval step was present, the workflow must end in ``completed``
    (i.e. approval was satisfied, not abandoned). Generic: reads
    ``approval_summary`` and ``expected.workflow_status``.
    """

    name = "approval_boundary"

    def __init__(self, *, threshold: float = 1.0):
        self._threshold = threshold

    def score(self, case: EvalCase) -> ScoreResult:
        approval = case.approval_summary or {}
        expected_status = (case.expected or {}).get("workflow_status", "completed")
        approval_present = bool(approval.get("approval_present"))
        if not approval_present:
            return _result(
                case,
                self.name,
                score=1.0,
                threshold=self._threshold,
                reason="no approval boundary declared for this case",
            )
        if expected_status == "completed":
            return _result(
                case,
                self.name,
                score=1.0,
                threshold=self._threshold,
                reason="approval boundary present and workflow completed",
            )
        return _result(
            case,
            self.name,
            score=0.0,
            threshold=self._threshold,
            reason=f"approval boundary present but final status is '{expected_status}'",
        )


class CostThresholdScorer:
    """Cost budget scorer: pass when total cost <= ``max_cost_usd``.

    Score is the fraction of budget remaining (1.0 = free, 0.0 = at budget).
    Anything over budget scores negative and fails at threshold 0.0.
    """

    name = "cost_threshold"

    def __init__(self, *, max_cost_usd: float, threshold: float = 0.0):
        self._max_cost = float(max_cost_usd)
        self._threshold = float(threshold)

    def score(self, case: EvalCase) -> ScoreResult:
        cost = float((case.cost_summary or {}).get("total_cost_usd", 0.0) or 0.0)
        if self._max_cost <= 0:
            score = 1.0 if cost <= 0 else -1.0
        else:
            remaining = (self._max_cost - cost) / self._max_cost
            score = max(-1.0, min(1.0, remaining))
        if cost <= self._max_cost:
            reason = f"cost ${cost:.6f} within budget ${self._max_cost:.6f}"
        else:
            reason = f"cost ${cost:.6f} exceeds budget ${self._max_cost:.6f}"
        return _result(case, self.name, score=score, threshold=self._threshold, reason=reason)


class LatencyThresholdScorer:
    """Latency budget scorer: pass when total latency <= ``max_latency_ms``."""

    name = "latency_threshold"

    def __init__(self, *, max_latency_ms: float, threshold: float = 0.0):
        self._max_latency = float(max_latency_ms)
        self._threshold = float(threshold)

    def score(self, case: EvalCase) -> ScoreResult:
        latency = float((case.cost_summary or {}).get("total_latency_ms", 0.0) or 0.0)
        if self._max_latency <= 0:
            score = 1.0 if latency <= 0 else -1.0
        else:
            remaining = (self._max_latency - latency) / self._max_latency
            score = max(-1.0, min(1.0, remaining))
        if latency <= self._max_latency:
            reason = f"latency {latency:.2f}ms within budget {self._max_latency:.2f}ms"
        else:
            reason = f"latency {latency:.2f}ms exceeds budget {self._max_latency:.2f}ms"
        return _result(case, self.name, score=score, threshold=self._threshold, reason=reason)


# ---------------------------------------------------------------------------
# Scorer error -> ScoreResult helper
# ---------------------------------------------------------------------------


def error_result(case: EvalCase, scorer_name: str, error: BaseException) -> ScoreResult:
    """Build an ``error`` ScoreResult from a scorer exception (spec §6.5 rule 2)."""
    return ScoreResult(
        case_id=case.case_id,
        scorer_name=scorer_name,
        score=None,
        threshold=0.0,
        status="error",
        reason=f"scorer raised {type(error).__name__}: {error}",
        evidence_path=_evidence_path(case.case_id, scorer_name),
    )


def digest_case_for_evidence(case: EvalCase) -> str:
    """Stable digest of a case for evidence records (sanity / tamper check)."""
    return digest_value(f"{case.case_id}:{case.workflow_id}:{case.created_at}")


__all__ = [
    "ApprovalBoundaryScorer",
    "ContextLineageScorer",
    "CostThresholdScorer",
    "EvalScorer",
    "LatencyThresholdScorer",
    "ScoreResult",
    "TraceCompletenessScorer",
    "digest_case_for_evidence",
    "error_result",
]

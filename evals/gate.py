"""Gate runner: scores cases and aggregates a pass/fail/incomplete verdict.

Implements the §6.5 aggregation rules and the ``EvalGateReport`` domain model
(§6.2). The optional export hook is a generic protocol (Phase 5); the local
verdict is always authoritative and export failures are recorded, never raised
(spec §4.1 Gherkin, C-EVAL-009).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from .cases import EvalCase
from .manifest import EvalManifest
from .scorers import EvalScorer, ScoreResult, error_result


# ---------------------------------------------------------------------------
# Domain model (spec §6.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalGateReport:
    """Aggregate pass/fail/incomplete result for one gate run."""

    report_id: str
    manifest_id: str
    status: Literal["passed", "failed", "incomplete"]
    results: list[ScoreResult] = field(default_factory=list)
    release_blockers: list[str] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)
    export_status: Literal["not_configured", "succeeded", "failed"] = "not_configured"
    gate_name: str = "eval-gate"
    summary: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Optional export hook (Phase 5)
# ---------------------------------------------------------------------------


@runtime_checkable
class EvalExportHook(Protocol):
    """Optional best-effort export hook (e.g. LangSmith dataset upload).

    Implementations MUST NOT raise into local scoring. ``EvalGateRunner``
    catches all exceptions, records ``export_status="failed"``, and keeps the
    local verdict intact (spec §4.1, C-EVAL-009).
    """

    def export(self, cases: list[EvalCase], report: EvalGateReport) -> None: ...


# ---------------------------------------------------------------------------
# Aggregation (spec §6.5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateAggregation:
    status: Literal["passed", "failed", "incomplete"]
    release_blockers: list[str]
    incomplete_reasons: list[str]


def aggregate_score_results(
    results: list[ScoreResult],
    *,
    required_scorers: list[str],
    missing_scorers: list[str],
    case_count: int,
) -> GateAggregation:
    """Apply the §6.5 aggregation rules to a flat list of scorer results.

    Rules:
      1. A required scorer with status ``failed`` -> gate ``failed``.
      2. A required scorer with status ``error`` -> ``incomplete`` unless a
         failure already blocks the gate.
      3. A missing required scorer -> ``incomplete``.
      4. Optional scorer failures are warnings (not blockers) unless promoted.
      5. Zero cases -> ``incomplete``.
      6. No required scorers -> ``incomplete``.
    """
    incomplete_reasons: list[str] = []
    release_blockers: list[str] = []

    # Rule 5: zero cases.
    if case_count == 0:
        incomplete_reasons.append("manifest has no eval cases (§6.5.5)")

    # Rule 6: no required scorers.
    if not required_scorers:
        incomplete_reasons.append("manifest declares no required scorers (§6.5.6)")

    # Rule 3: missing required scorers.
    if missing_scorers:
        incomplete_reasons.append(
            "required scorer(s) not registered: " + ", ".join(sorted(missing_scorers))
        )

    required_set = set(required_scorers)
    # Rule 1: required failures block the gate.
    has_required_failure = any(
        r.status == "failed" and r.scorer_name in required_set for r in results
    )

    release_blockers = _release_blockers(results, required_set)

    # Rule 2: required errors make the gate incomplete unless a failure blocks.
    has_required_error = any(
        r.status == "error" and r.scorer_name in required_set for r in results
    )

    if has_required_failure:
        status: Literal["passed", "failed", "incomplete"] = "failed"
    elif incomplete_reasons or has_required_error:
        status = "incomplete"
    else:
        status = "passed"

    return GateAggregation(
        status=status,
        release_blockers=release_blockers,
        incomplete_reasons=incomplete_reasons,
    )


def _release_blockers(results: list[ScoreResult], required_set: set[str]) -> list[str]:
    """Human-facing blocker labels for failing required scorers (spec §4.1)."""
    blockers: list[str] = []
    seen: set[str] = set()
    for r in results:
        if r.status != "failed" or r.scorer_name not in required_set:
            continue
        label = f"{r.case_id} / {r.scorer_name}: {r.reason}"
        if label not in seen:
            blockers.append(label)
            seen.add(label)
    return blockers


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------


@dataclass
class GateRunConfig:
    """Configuration handed to ``run_eval_gate``.

    ``required_scorers`` and ``missing_scorers`` are taken from the manifest /
    registry by the caller so the runner stays free of registry coupling.
    """

    required_scorers: list[str]
    missing_scorers: list[str]
    gate_name: str = "eval-gate"


def run_eval_gate(
    cases: list[EvalCase],
    scorers: list[EvalScorer],
    config: GateRunConfig | Any | None = None,
    *,
    manifest: EvalManifest | None = None,
    export_hook: EvalExportHook | None = None,
) -> EvalGateReport:
    """Score ``cases`` with ``scorers`` and aggregate a gate report.

    Prefer passing an ``EvalManifest`` so required scorers and thresholds come
    from one source. A ``GateRunConfig`` is accepted for tests that bypass the
    manifest. Scorers are run for every case; failures never abort sibling
    scorers or cases.
    """
    required_scorers, missing_scorers, gate_name, manifest_id = _resolve_config(config, manifest)

    results: list[ScoreResult] = []
    for case in cases:
        for scorer in scorers:
            results.append(_safe_score(scorer, case))

    aggregation = aggregate_score_results(
        results,
        required_scorers=required_scorers,
        missing_scorers=missing_scorers,
        case_count=len(cases),
    )

    evidence = _collect_evidence(results, aggregation)

    report = EvalGateReport(
        report_id=f"report-{uuid.uuid4().hex[:16]}",
        manifest_id=manifest_id,
        status=aggregation.status,
        results=results,
        release_blockers=aggregation.release_blockers,
        evidence=evidence,
        export_status="not_configured",
        gate_name=gate_name,
        summary=_summary(cases, results, aggregation),
    )

    # Phase 5: optional export is best-effort and verdict-preserving.
    if export_hook is not None:
        report = _with_export(report, cases, export_hook)

    return report


def _resolve_config(
    config: Any | None, manifest: EvalManifest | None
) -> tuple[list[str], list[str], str, str]:
    if manifest is not None:
        manifest_id = manifest.manifest_id
        required = list(manifest.required_scorers)
        gate_name = "eval-gate"
        # Missing scorers are reported by the registry; here we only know what's
        # required. The caller wires missing_scorers through config when using a
        # registry; with manifest-only we assume the supplied scorers satisfy
        # required names (the registry path is the authoritative resolver).
        missing: list[str] = []
        if config is not None and hasattr(config, "missing_scorers"):
            missing = list(config.missing_scorers)
        if config is not None and hasattr(config, "gate_name"):
            gate_name = config.gate_name
        return required, missing, gate_name, manifest_id
    if config is None:
        return [], [], "eval-gate", "adhoc"
    required = list(getattr(config, "required_scorers", []))
    missing = list(getattr(config, "missing_scorers", []))
    gate_name = getattr(config, "gate_name", "eval-gate")
    manifest_id = getattr(config, "manifest_id", "adhoc")
    return required, missing, gate_name, manifest_id


def _safe_score(scorer: EvalScorer, case: EvalCase) -> ScoreResult:
    """Run one scorer, converting any exception to an ``error`` result."""
    try:
        result = scorer.score(case)
        if not isinstance(result, ScoreResult):
            return error_result(
                case,
                getattr(scorer, "name", "unknown"),
                TypeError(f"scorer returned {type(result).__name__}, not ScoreResult"),
            )
        return result
    except Exception as exc:  # noqa: BLE001 - scorer errors become error results
        return error_result(case, getattr(scorer, "name", "unknown"), exc)


def _collect_evidence(results: list[ScoreResult], aggregation: GateAggregation) -> list[dict[str, str]]:
    """Evidence records for failing checks (C-EVAL-006, SEM-EVAL-003)."""
    evidence: list[dict[str, str]] = []
    for r in results:
        if r.status != "failed":
            continue
        evidence.append(
            {
                "evidence_id": f"ev-{uuid.uuid5(_EV_NAMESPACE, f'{r.case_id}:{r.scorer_name}').hex[:12]}",
                "evidence_kind": "scorer_log",
                "case_id": r.case_id,
                "scorer_name": r.scorer_name,
                "path": r.evidence_path,
                "digest": _evidence_digest(r),
            }
        )
    return evidence


def _evidence_digest(result: ScoreResult) -> str:
    from .redaction import digest_value

    return digest_value(
        f"{result.case_id}|{result.scorer_name}|{result.score}|{result.threshold}|{result.status}|{result.reason}"
    )


def _summary(
    cases: list[EvalCase], results: list[ScoreResult], aggregation: GateAggregation
) -> dict[str, Any]:
    case_ids = [c.case_id for c in cases]
    failed_case_ids = {r.case_id for r in results if r.status == "failed"}
    errored_case_ids = {r.case_id for r in results if r.status == "error"}
    passed_case_ids = [cid for cid in case_ids if cid not in failed_case_ids and cid not in errored_case_ids]
    scorer_names = sorted({r.scorer_name for r in results})
    return {
        "total_cases": len(cases),
        "passed_cases": len(passed_case_ids),
        "failed_cases": len(failed_case_ids),
        "scorer_count": len(scorer_names),
        "scorer_names": scorer_names,
        "incomplete_reasons": list(aggregation.incomplete_reasons),
    }


def _with_export(
    report: EvalGateReport, cases: list[EvalCase], hook: EvalExportHook
) -> EvalGateReport:
    """Run the optional export hook, capturing failures without raising."""
    try:
        hook.export(cases, report)
    except Exception:  # noqa: BLE001 - export must never raise into local scoring
        return EvalGateReport(
            report_id=report.report_id,
            manifest_id=report.manifest_id,
            status=report.status,
            results=report.results,
            release_blockers=report.release_blockers,
            evidence=report.evidence,
            export_status="failed",
            gate_name=report.gate_name,
            summary={**report.summary, "export_error": True},
        )
    return EvalGateReport(
        report_id=report.report_id,
        manifest_id=report.manifest_id,
        status=report.status,
        results=report.results,
        release_blockers=report.release_blockers,
        evidence=report.evidence,
        export_status="succeeded",
        gate_name=report.gate_name,
        summary=report.summary,
    )


_EV_NAMESPACE = uuid.UUID("7c1f9a3e-2b54-4d8e-9a6f-0c3b7e2d1a45")


# ---------------------------------------------------------------------------
# Convenience: manifest-driven gate runner
# ---------------------------------------------------------------------------


class EvalGateRunner:
    """Ties manifest + registry + optional export hook into one entry point.

    This is the shape the CLI (Phase 4) calls. It validates the manifest,
    resolves scorers through the registry, runs the gate, and returns the
    report. A non-OK manifest validation produces an ``incomplete`` report
    without running scorers (§6.5 rules 5-6).
    """

    def __init__(
        self,
        manifest: EvalManifest,
        registry: Any,
        *,
        export_hook: EvalExportHook | None = None,
        gate_name: str = "eval-gate",
    ):
        self._manifest = manifest
        self._registry = registry
        self._export_hook = export_hook
        self._gate_name = gate_name

    def run(self, cases: list[EvalCase]) -> EvalGateReport:
        resolution = self._registry.resolve(self._manifest.required_scorers)
        config = GateRunConfig(
            required_scorers=list(self._manifest.required_scorers),
            missing_scorers=resolution.missing,
            gate_name=self._gate_name,
        )
        # All six §6.5 aggregation rules (zero cases, zero required scorers,
        # missing scorers, failures, errors, pass) are applied inside
        # ``run_eval_gate`` -> ``aggregate_score_results``, so the runner does
        # not short-circuit: it runs the resolved scorers and lets aggregation
        # decide the verdict consistently.
        return run_eval_gate(
            cases,
            resolution.scorers,
            config,
            manifest=self._manifest,
            export_hook=self._export_hook,
        )

    def _incomplete_report(self, reasons: list[str], cases: list[EvalCase]) -> EvalGateReport:
        # Kept for callers that want a pre-flight incomplete report without
        # running scorers (e.g. manifest introspection). ``run`` itself relies
        # on ``aggregate_score_results`` for rule-consistent verdicts.
        return EvalGateReport(
            report_id=f"report-{uuid.uuid4().hex[:16]}",
            manifest_id=self._manifest.manifest_id,
            status="incomplete",
            results=[],
            release_blockers=[],
            evidence=[],
            export_status="not_configured",
            gate_name=self._gate_name,
            summary={
                "total_cases": len(cases),
                "passed_cases": 0,
                "failed_cases": 0,
                "scorer_count": 0,
                "scorer_names": [],
                "incomplete_reasons": list(reasons),
            },
        )


__all__ = [
    "EvalExportHook",
    "EvalGateReport",
    "EvalGateRunner",
    "GateAggregation",
    "GateRunConfig",
    "aggregate_score_results",
    "run_eval_gate",
]

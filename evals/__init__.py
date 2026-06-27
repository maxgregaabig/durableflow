"""DurableFlow eval gate: turn recorded workflow runs into pass/fail gates.

Implements ``docs/eval-gate-spec.md``. Core machinery is Python standard
library only; external evaluators and LangSmith export are optional and never
required for local tests, examples, or workflow execution.
"""

from .cases import EvalCase, EvalCaseBuildResult, build_eval_case_from_workflow
from .gate import (
    EvalGateReport,
    EvalGateRunner,
    aggregate_score_results,
    run_eval_gate,
)
from .io import load_json, payload_digest, write_artifact, write_json_with_digest
from .manifest import (
    EvalManifest,
    append_case_to_manifest,
    load_eval_manifest,
    new_manifest,
    save_eval_manifest,
    validate_for_gate,
)
from .redaction import digest_payloads, digest_value, redact_value
from .registry import ScorerRegistry
from .scorers import (
    ApprovalBoundaryScorer,
    ContextLineageScorer,
    CostThresholdScorer,
    EvalScorer,
    LatencyThresholdScorer,
    ScoreResult,
    TraceCompletenessScorer,
)
from .view import (
    CaseResultView,
    EvalGateReportView,
    FailingCheckView,
    GateEvidenceView,
    GateNextActionView,
    GateSummaryView,
    build_eval_gate_report_view,
)

__all__ = [
    "ApprovalBoundaryScorer",
    "CaseResultView",
    "ContextLineageScorer",
    "CostThresholdScorer",
    "EvalCase",
    "EvalCaseBuildResult",
    "EvalGateReport",
    "EvalGateReportView",
    "EvalGateRunner",
    "EvalManifest",
    "EvalScorer",
    "FailingCheckView",
    "GateEvidenceView",
    "GateNextActionView",
    "GateSummaryView",
    "LatencyThresholdScorer",
    "ScoreResult",
    "ScorerRegistry",
    "TraceCompletenessScorer",
    "aggregate_score_results",
    "append_case_to_manifest",
    "build_eval_case_from_workflow",
    "build_eval_gate_report_view",
    "digest_payloads",
    "digest_value",
    "load_eval_manifest",
    "load_json",
    "new_manifest",
    "payload_digest",
    "redact_value",
    "run_eval_gate",
    "save_eval_manifest",
    "validate_for_gate",
    "write_artifact",
    "write_json_with_digest",
]

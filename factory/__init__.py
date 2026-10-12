"""CLEAR factory package — a worked example of a durable spec-driven agent workflow.

This package is a worked example extension under ``factory/``, built on
DurableFlow core primitives. It exercises checkpointed steps, approval
gates, side-effect idempotency, context lineage, and independent claim
verification without changing ``WorkflowEngine`` execution semantics.
"""

from __future__ import annotations

from .agent_runner import AgentRunner, VerifierAgent
from .audit_view import (
    ClearWorkflowAuditView,
    build_clear_workflow_audit_view,
    render_clear_workflow_audit,
    scan_for_blocklisted_terms,
)
from .clear_workflow import ClearConfig, ClearWorkflow, DEFAULT_PLAN_MD, ShipBlockedError
from .phase_state import (
    ClearLapResult,
    ClearPhase,
    ClearPhaseState,
    PhasePlanParser,
)
from .phase_store import ClearPhaseStore
from .remediation import RemediationEngine, RemediationOutcome
from .test_runner import AssessLapOutcome, TestRunner
from .verification_ledger import (
    ShipGateResult,
    VerificationLedger,
    claim_register,
)
from .workspace import (
    PatchApplicationError,
    Workspace,
    WorkspaceViolationError,
    apply_search_replace,
)

__all__ = [
    "AgentRunner",
    "AssessLapOutcome",
    "ClearLapResult",
    "ClearPhase",
    "ClearPhaseState",
    "ClearPhaseStore",
    "ClearWorkflow",
    "ClearConfig",
    "ClearWorkflowAuditView",
    "DEFAULT_PLAN_MD",
    "PatchApplicationError",
    "PhasePlanParser",
    "RemediationEngine",
    "RemediationOutcome",
    "ShipBlockedError",
    "ShipGateResult",
    "TestRunner",
    "VerificationLedger",
    "VerifierAgent",
    "Workspace",
    "WorkspaceViolationError",
    "apply_search_replace",
    "build_clear_workflow_audit_view",
    "claim_register",
    "render_clear_workflow_audit",
    "scan_for_blocklisted_terms",
]

"""EvalCase domain model and builder (spec §6.2, §5, Phase 1).

``build_eval_case_from_workflow`` promotes a completed DurableFlow workflow run
into a deterministic ``EvalCase`` JSON artifact. Inputs/outputs are redacted to
digests by default (§6.4). Incomplete workflows are rejected with a user-facing
reason (§4.1 Gherkin, T-EVAL-002).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from src.store import WorkflowState, WorkflowStatus, WorkflowStore

from .redaction import digest_payloads, redact_value


@dataclass(frozen=True)
class EvalCase:
    """One redacted, deterministic evaluation case derived from a workflow run."""

    case_id: str
    workflow_id: str
    workflow_name: str
    created_at: str
    input_summary: dict[str, Any]
    expected: dict[str, Any]
    trace_summary: dict[str, Any]
    context_summary: dict[str, Any]
    approval_summary: dict[str, Any]
    cost_summary: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalCaseBuildResult:
    """Outcome of promoting a workflow into an eval case.

    ``case`` is set on success; ``reason`` is set on rejection. Both redaction
    and rejection are explicit so the caller never has to guess.
    """

    case: EvalCase | None
    accepted: bool
    reason: str


def build_eval_case_from_workflow(
    store: WorkflowStore,
    workflow_id: str,
    *,
    context_ledger: Any | None = None,
    telemetry_events: list[dict[str, Any]] | None = None,
    expected_overrides: dict[str, Any] | None = None,
    metadata_overrides: dict[str, Any] | None = None,
) -> EvalCaseBuildResult:
    """Promote a completed workflow run into an ``EvalCase``.

    ``context_ledger`` is an optional object exposing
    ``audit_workflow(workflow_id)`` (e.g. ``context.ledger.ContextLedger``).
    ``telemetry_events`` is an optional list of telemetry event dicts; when
    absent, trace/cost summaries fall back to step results from the store.

    Returns ``EvalCaseBuildResult``. A non-completed workflow is rejected with
    a user-facing reason and no case is produced (T-EVAL-002).
    """
    try:
        state = store.load_workflow(workflow_id)
    except KeyError as exc:
        return EvalCaseBuildResult(None, False, f"workflow not found: {exc}")

    if state.status != WorkflowStatus.COMPLETED:
        reason = (
            f"workflow is incomplete: status is '{state.status.value}' "
            f"(must be 'completed') before it can become a golden case"
        )
        return EvalCaseBuildResult(None, False, reason)

    case = _assemble_case(
        state,
        store,
        context_ledger=context_ledger,
        telemetry_events=telemetry_events,
        expected_overrides=expected_overrides,
        metadata_overrides=metadata_overrides,
    )
    return EvalCaseBuildResult(case, True, "promoted completed workflow into eval case")


def _assemble_case(
    state: WorkflowState,
    store: WorkflowStore,
    *,
    context_ledger: Any | None,
    telemetry_events: list[dict[str, Any]] | None,
    expected_overrides: dict[str, Any] | None,
    metadata_overrides: dict[str, Any] | None,
) -> EvalCase:
    step_results = store.step_results(state.workflow_id)
    trace_summary = _trace_summary(state, step_results, telemetry_events)
    cost_summary = _cost_summary(step_results, telemetry_events)
    approval_summary = _approval_summary(state, step_results)
    context_summary = _context_summary(context_ledger, state.workflow_id)
    input_summary = _input_summary(state, step_results)
    expected = _expected(state, step_results, expected_overrides)
    metadata = _metadata(state, step_results, metadata_overrides)

    case_id = f"case-{uuid.uuid5(_CASE_NAMESPACE, state.workflow_id).hex[:16]}"
    return EvalCase(
        case_id=case_id,
        workflow_id=state.workflow_id,
        workflow_name=state.workflow_type,
        created_at=state.updated_at or state.created_at,
        input_summary=input_summary,
        expected=expected,
        trace_summary=trace_summary,
        context_summary=context_summary,
        approval_summary=approval_summary,
        cost_summary=cost_summary,
        metadata=metadata,
    )


# Stable namespace so case_id is deterministic for a given workflow_id across
# processes (mirrors the LangSmith UUIDv5 approach in the adapter spec §10.2).
_CASE_NAMESPACE = uuid.UUID("2b6e1c7a-4f2d-5a9e-8c1b-3d7f0a2e5b48")


def _trace_summary(
    state: WorkflowState,
    step_results: list[dict[str, Any]],
    telemetry_events: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    events = list(telemetry_events) if telemetry_events is not None else []
    step_names = [r["step_name"] for r in step_results]
    summary: dict[str, Any] = {
        "workflow_status": state.status.value,
        "step_count": len(step_results),
        "step_names": step_names,
        "last_step_index": state.current_step,
        "event_count": len(events),
        "event_types": sorted({e.get("event_type") for e in events if e.get("event_type")}),
    }
    if events:
        summary["fallback_count"] = sum(1 for e in events if e.get("event_type") == "model_fallback")
        summary["crash_recoveries"] = sum(1 for e in events if e.get("event_type") == "crash_detected")
        summary["approval_requests"] = sum(1 for e in events if e.get("event_type") == "approval_requested")
    return summary


def _cost_summary(
    step_results: list[dict[str, Any]],
    telemetry_events: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    total_cost = sum(float(r.get("cost_usd", 0.0) or 0.0) for r in step_results)
    total_latency_ms = sum(float(r.get("duration_ms", 0.0) or 0.0) for r in step_results)
    models_used = sorted({r.get("model_used") for r in step_results if r.get("model_used")})
    summary: dict[str, Any] = {
        "total_cost_usd": round(total_cost, 8),
        "total_latency_ms": round(total_latency_ms, 2),
        "models_used": models_used,
        "step_count": len(step_results),
    }
    if telemetry_events:
        # Telemetry carries the authoritative workflow-complete summary when
        # present (TelemetryLogger.summarize_workflow shape).
        complete_events = [e for e in telemetry_events if e.get("event_type") == "workflow_complete"]
        if complete_events:
            meta = complete_events[-1].get("metadata") or {}
            if isinstance(meta, dict) and meta:
                summary["telemetry_summary"] = {
                    "total_cost": meta.get("total_cost"),
                    "total_latency_ms": meta.get("total_latency_ms"),
                    "step_count": meta.get("step_count"),
                }
    return summary


def _approval_summary(state: WorkflowState, step_results: list[dict[str, Any]]) -> dict[str, Any]:
    # Step names that look like approval gates are surfaced as labels, not raw
    # payloads. Final workflow status records whether the run was approved.
    approval_steps = [
        r["step_name"]
        for r in step_results
        if "approval" in str(r.get("step_name", "")).lower() or "approve" in str(r.get("step_name", "")).lower()
    ]
    return {
        "final_status": state.status.value,
        "approval_step_names": approval_steps,
        "approval_present": len(approval_steps) > 0,
    }


def _context_summary(context_ledger: Any | None, workflow_id: str) -> dict[str, Any]:
    if context_ledger is None or not hasattr(context_ledger, "audit_workflow"):
        return {"available": False, "reason": "no context ledger configured"}
    audit = context_ledger.audit_workflow(workflow_id)
    # Pull lineage counts off the audit object without coupling to its type.
    counts: dict[str, Any] = {}
    for attr in (
        "observed_count",
        "retrieved_count",
        "selected_count",
        "rejected_count",
        "consumed_count",
        "influential_count",
        "decision_count",
    ):
        value = getattr(audit, attr, None)
        if isinstance(value, int):
            counts[attr.removesuffix("_count")] = value
    return {
        "available": True,
        "lineage_counts": counts,
        "artifact_digests": sorted(
            {
                d
                for a in getattr(audit, "artifacts", [])
                if isinstance(getattr(a, "content_digest", None), str) and (d := a.content_digest)
            }
        ),
    }


def _input_summary(state: WorkflowState, step_results: list[dict[str, Any]]) -> dict[str, Any]:
    # step_data may carry user-facing inputs; redact any oversized/raw values.
    raw = dict(state.step_data)
    return digest_payloads(redact_value(_shallow_strings_only(raw)))


def _shallow_strings_only(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only string/number/bool leaf values at the top level, drop nested.

    Avoids leaking arbitrarily nested step outputs as "inputs". Nested values
    are summarized elsewhere (trace/cost/context summaries).
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
    return out


def _expected(
    state: WorkflowState,
    step_results: list[dict[str, Any]],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    expected: dict[str, Any] = {
        "workflow_status": state.status.value,
    }
    # The terminal step's redacted output is the expected outcome when present.
    if step_results:
        terminal = step_results[-1]
        expected["final_step"] = terminal.get("step_name")
        expected["final_output_digest"] = _digest_step_output(terminal.get("output"))
    if overrides:
        for key, value in overrides.items():
            expected[key] = redact_value(value)
    return expected


def _digest_step_output(output: Any) -> str | None:
    if output is None:
        return None
    from .redaction import digest_value

    text = output if isinstance(output, str) else repr(output)
    return digest_value(text)


def _metadata(
    state: WorkflowState,
    step_results: list[dict[str, Any]],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "workflow_created_at": state.created_at,
        "workflow_updated_at": state.updated_at,
        "step_count": len(step_results),
    }
    if overrides:
        meta.update({k: redact_value(v) for k, v in overrides.items()})
    return meta


__all__ = [
    "EvalCase",
    "EvalCaseBuildResult",
    "build_eval_case_from_workflow",
]

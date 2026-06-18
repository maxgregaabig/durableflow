from __future__ import annotations


SCENARIO_LABELS = {
    "tool_timeout": "survived a tool timeout",
    "malformed_tool_output": "survived malformed tool output",
    "prompt_injection": "blocked a rogue write",
    "context_overflow": "kept context under budget",
    "model_fallback": "survived model fallback",
    "crash_after_side_effect": "prevented a double write",
}

METRIC_LABELS = {
    "task_success_rate": "task success rate",
    "recovery_rate": "failure recovery rate",
    "duplicate_side_effects_prevented": "prevented double writes",
    "unauthorized_writes_blocked": "blocked rogue writes",
    "approval_latency_p50_ms": "approval latency p50",
    "approval_latency_p95_ms": "approval latency p95",
    "cost_per_completed_workflow_usd": "cost per completed workflow",
    "fallback_count": "model fallbacks",
    "token_budget_violations": "runaway context incidents",
    "max_turns_violations": "runaway turn incidents",
    "trace_completeness_pct": "trace completeness",
}


def scenario_label(scenario_id: str) -> str:
    return SCENARIO_LABELS.get(scenario_id, scenario_id.replace("_", " "))


def metric_label(metric_name: str) -> str:
    return METRIC_LABELS.get(metric_name, metric_name.replace("_", " "))


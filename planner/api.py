from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .adapters import OpenAICompatAdapter
from .constraints import ConstraintParseError, ConstraintParser
from .integration import PlannerExecutionError, run_with_plan
from .planner import Planner
from .serialization import to_jsonable
from .solver import PlanStatus
from .store import PlannerStore
from .views import build_plan_trace_view


@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    body: dict[str, Any]


def handle_completions(
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    *,
    planner: Planner | None = None,
    adapters: Mapping[str, Any] | None = None,
    store: PlannerStore | None = None,
    direct_adapter: Any | None = None,
) -> ApiResponse:
    planner = planner or Planner()
    if not ConstraintParser.should_plan(body):
        adapter = direct_adapter or OpenAICompatAdapter()
        step = _direct_step(str(body["model"]))
        response = adapter.invoke(step, body)
        return ApiResponse(status_code=200, body=_completion_body(response.content, response.model_used))

    try:
        constraints = ConstraintParser.parse(headers, body)
    except ConstraintParseError as exc:
        return ApiResponse(status_code=exc.status_code, body=exc.to_response())

    plan = planner.plan(body, constraints)
    if store is not None:
        store.create_plan_workflow(plan.request_id, constraints, plan)
    if plan.status == PlanStatus.INFEASIBLE:
        return ApiResponse(
            status_code=422,
            body={
                "error": {
                    "type": "infeasible_plan",
                    "reason": plan.infeasible_reason,
                    "plan_id": plan.id,
                }
            },
        )
    try:
        response, outcome = run_with_plan(
            plan,
            body,
            constraints=constraints,
            adapters=adapters,
            store=store,
            budget_ledger=planner.budget_ledger,
        )
    except PlannerExecutionError as exc:
        return ApiResponse(
            status_code=502,
            body={
                "error": {
                    "type": "execution_failed",
                    "plan_id": plan.id,
                    "outcome": to_jsonable(exc.outcome),
                }
            },
        )
    trace = build_plan_trace_view(plan, outcome, constraints)
    return ApiResponse(
        status_code=200,
        body=_completion_body(response.content, response.model_used) | {"plan_trace": to_jsonable(trace)},
    )


def get_plan_trace(request_id: str, *, store: PlannerStore) -> ApiResponse:
    payload = store.load_plan_json(request_id)
    if payload is None:
        return ApiResponse(status_code=404, body={"error": {"type": "not_found"}})
    return ApiResponse(status_code=200, body=payload)


def _completion_body(content: str, model: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-durableflow-planner",
        "object": "chat.completion",
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
    }


def _direct_step(model_id: str):
    return type(
        "DirectStep",
        (),
        {"model_id": model_id, "estimate": type("DirectEstimate", (), {"cost_usd": 0.0})()},
    )()

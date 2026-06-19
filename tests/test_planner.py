from __future__ import annotations

import json
from pathlib import Path

import pytest

from planner.adapters import RawResponse
from planner.api import handle_completions
from planner.budget import BudgetLedger
from planner.constraints import ExecutionConstraints, Objective, OutputCheck, Privacy, Tier
from planner.estimators import CapabilityEstimator, CostModel, LatencyModel
from planner.integration import PlannerExecutionError, run_with_plan
from planner.outcomes import Attempt, PlanOutcome, VerifiableOutcome
from planner.planner import Planner
from planner.render import render_plan_trace
from planner.solver import PlanStatus, StepRole
from planner.store import PlannerStore
from planner.targets import TargetHealth, TargetProfile, TargetRegistry, default_targets
from planner.taskclass import TASK_CLASS_TAXONOMY_VERSION, TaskClass, derive_task_class
from planner.views import TraceState, build_plan_trace_view


REQUEST = {"model": "auto", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 16}


def test_pln_001_cheap_request_stays_local_with_cloud_fallback() -> None:
    plan = Planner().plan(REQUEST, ExecutionConstraints(max_cost_usd=0.002))

    assert plan.status == PlanStatus.PLANNED
    assert plan.steps[0].target_id == "local-ollama"
    assert any(step.estimate.tier in {Tier.ECONOMY, Tier.FRONTIER} for step in plan.steps[1:])
    assert plan.planning_ms >= 0


def test_pln_002_tier_floor_frontier_excludes_lower_tiers() -> None:
    plan = Planner().plan(REQUEST, ExecutionConstraints(tier_floor=Tier.FRONTIER))

    assert plan.status == PlanStatus.PLANNED
    assert plan.steps
    assert {step.estimate.tier for step in plan.steps} == {Tier.FRONTIER}


def test_pln_003_privacy_local_only_without_healthy_local_is_infeasible() -> None:
    registry = TargetRegistry(default_targets())
    registry.set_health(
        TargetHealth("local-ollama", available=False, last_checked_at="2026-01-01T00:00:00Z")
    )

    plan = Planner(target_registry=registry).plan(
        REQUEST,
        ExecutionConstraints(privacy=Privacy.LOCAL_ONLY),
    )

    assert plan.status == PlanStatus.INFEASIBLE
    assert plan.infeasible_reason == "no_healthy_local_target"
    assert all(rejected.target_id != "cloud-frontier" or rejected.reason for rejected in plan.rejected)


def test_pln_004_latency_ceiling_excludes_frontier() -> None:
    plan = Planner().plan(REQUEST, ExecutionConstraints(max_latency_ms=3000))

    assert all(step.target_id != "cloud-frontier" for step in plan.steps)
    assert any(
        rejected.target_id == "cloud-frontier" and rejected.reason == "latency_ceiling"
        for rejected in plan.rejected
    )


def test_pln_006_budget_near_exhaustion_downgrades_objective() -> None:
    ledger = BudgetLedger()
    ledger.set_limit("b1", limit_usd=1.0, spent_usd=0.95)

    plan = Planner(budget_ledger=ledger).plan(
        REQUEST,
        ExecutionConstraints(budget_id="b1", objective=Objective.MOST_CAPABLE),
    )

    assert "objective_downgraded_to_cheapest" in plan.flags
    assert plan.steps[0].target_id == "local-ollama"


def test_pln_006_budget_exhausted_when_no_target_fits() -> None:
    registry = TargetRegistry(
        [
            TargetProfile(
                "economy-only",
                "Economy Only",
                Tier.ECONOMY,
                "economy",
                Privacy.ANY,
                "us",
                1.0,
                1.0,
            )
        ]
    )
    ledger = BudgetLedger()
    ledger.set_limit("b2", limit_usd=1.0, spent_usd=0.999)

    plan = Planner(target_registry=registry, budget_ledger=ledger).plan(
        REQUEST,
        ExecutionConstraints(budget_id="b2"),
    )

    assert plan.status == PlanStatus.INFEASIBLE
    assert plan.infeasible_reason == "budget_exhausted"


def test_pln_007_cold_start_sets_low_confidence_and_shadow_step() -> None:
    plan = Planner().plan(REQUEST, ExecutionConstraints(shadow=True))

    assert plan.low_confidence is True
    assert any(step.role == StepRole.SHADOW for step in plan.steps)


def test_pln_008_cache_hit_returns_hot_path_plan() -> None:
    planner = Planner()
    planner.plan(REQUEST, ExecutionConstraints(max_cost_usd=0.002))
    cached = planner.plan(REQUEST, ExecutionConstraints(max_cost_usd=0.002))

    assert "cache_hit" in cached.flags
    assert cached.planning_ms < 10


def test_pln_009_failed_json_check_escalates_and_checkpoints(tmp_path: Path) -> None:
    registry = TargetRegistry([default_targets()[0], default_targets()[2]])
    planner = Planner(target_registry=registry)
    constraints = ExecutionConstraints(output_check=OutputCheck(kind="json"))
    plan = planner.plan(REQUEST | {"output_check": {"kind": "json"}}, constraints)
    store = PlannerStore(tmp_path / "planner.sqlite")
    store.create_plan_workflow(plan.request_id, constraints, plan)

    response, outcome = run_with_plan(
        plan,
        REQUEST | {"output_check": {"kind": "json"}},
        constraints=constraints,
        adapters={
            "local-ollama": _StaticAdapter("not-json"),
            "cloud-frontier": _StaticAdapter('{"ok": true}'),
        },
        store=store,
    )

    assert response.content == '{"ok": true}'
    assert outcome.final_step_index == 1
    assert outcome.attempts[0].verifiable_outcome == VerifiableOutcome.FAILED_CHECK
    rows = store.workflow_store.step_results(f"planner:{plan.id}")
    assert {row["step_name"] for row in rows} == {"attempt_0", "attempt_1"}


def test_pln_010_explicit_model_bypasses_planner() -> None:
    adapter = _CountingAdapter("direct")

    response = handle_completions(
        {},
        {"model": "explicit-model", "messages": [{"role": "user", "content": "hi"}]},
        direct_adapter=adapter,
    )

    assert response.status_code == 200
    assert adapter.calls == 1
    assert response.body["model"] == "explicit-model"


def test_pln_011_infeasible_http_returns_422_and_invokes_no_target() -> None:
    registry = TargetRegistry(default_targets())
    registry.set_health(
        TargetHealth("local-ollama", available=False, last_checked_at="2026-01-01T00:00:00Z")
    )
    planner = Planner(target_registry=registry)
    adapter = _CountingAdapter("unused")

    response = handle_completions(
        {"X-Privacy": "local-only"},
        REQUEST,
        planner=planner,
        adapters={"cloud-frontier": adapter, "cloud-economy": adapter, "local-ollama": adapter},
    )

    assert response.status_code == 422
    assert response.body["error"]["reason"] == "no_healthy_local_target"
    assert adapter.calls == 0


def test_pln_012_stats_update_is_idempotent_and_versioned(tmp_path: Path) -> None:
    store = PlannerStore(tmp_path / "stats.sqlite")
    plan = Planner().plan(REQUEST, ExecutionConstraints())
    attempt = Attempt.from_outcome(
        step_index=0,
        target_id="local-ollama",
        actual_cost_usd=0.0,
        actual_latency_ms=100,
        verifiable_outcome=VerifiableOutcome.NO_CHECK_COMPLETED,
    )
    outcome = PlanOutcome(plan.id, [attempt], 0, True)

    from planner.outcomes import OutcomeRecorder

    recorder = OutcomeRecorder(store)
    recorder.record(plan, outcome, TaskClass.CHAT)
    recorder.record(plan, outcome, TaskClass.CHAT)

    stats = store.get_target_stats("local-ollama", TaskClass.CHAT)
    assert stats is not None
    assert stats["sample_count"] == 1
    assert stats["taxonomy_version"] == TASK_CLASS_TAXONOMY_VERSION


def test_pln_015_streaming_mid_stream_failure_does_not_retry_fallback() -> None:
    planner = Planner()
    plan = planner.plan(REQUEST | {"stream": True}, ExecutionConstraints())
    fallback = _CountingAdapter("fallback")

    with pytest.raises(PlannerExecutionError) as exc:
        run_with_plan(
            plan,
            REQUEST | {"stream": True},
            adapters={"local-ollama": _FailingStreamAdapter(), "cloud-economy": fallback},
        )

    assert exc.value.outcome.attempts[0].verifiable_outcome == VerifiableOutcome.TRANSPORT_ERROR
    assert fallback.calls == 0


def test_pln_016_task_class_is_deterministic() -> None:
    json_request = REQUEST | {"output_check": {"kind": "json"}}

    assert derive_task_class(json_request) == TaskClass.JSON_EXTRACTION
    assert derive_task_class(json_request) == derive_task_class(json_request)
    assert derive_task_class({"messages": [{"role": "user", "content": "```python\nprint(1)\n```"}]}) == TaskClass.CODE
    assert derive_task_class({"messages": [{"role": "user", "content": "summarize this"}]}) == TaskClass.SUMMARIZATION


def test_sem_plan_trace_states_and_render_architecture() -> None:
    constraints = ExecutionConstraints(max_cost_usd=0.002)
    plan = Planner().plan(REQUEST, constraints)
    attempt = Attempt.from_outcome(
        step_index=0,
        target_id=plan.steps[0].target_id,
        actual_cost_usd=0.0,
        actual_latency_ms=25,
        verifiable_outcome=VerifiableOutcome.NO_CHECK_COMPLETED,
    )
    view = build_plan_trace_view(plan, PlanOutcome(plan.id, [attempt], 0, True), constraints)

    assert view.state == TraceState.EXECUTED
    assert view.headline
    assert "\n" not in view.headline
    assert "target_id" not in render_plan_trace(view)
    source = Path("planner/render.py").read_text(encoding="utf-8")
    assert "from .solver" not in source
    assert "from .outcomes" not in source


def test_sem_infeasible_trace_has_remediation() -> None:
    registry = TargetRegistry(default_targets())
    registry.set_health(
        TargetHealth("local-ollama", available=False, last_checked_at="2026-01-01T00:00:00Z")
    )
    constraints = ExecutionConstraints(privacy=Privacy.LOCAL_ONLY)
    plan = Planner(target_registry=registry).plan(REQUEST, constraints)
    view = build_plan_trace_view(plan, None, constraints)

    assert view.state == TraceState.INFEASIBLE
    assert view.what_would_change
    assert "almost ran" not in render_plan_trace(view).lower()


def test_planner_scenario_catalog_covers_spec_fixtures() -> None:
    fixtures = sorted(Path("data/planner_scenarios").glob("PLAN-*.json"))
    assert [path.stem for path in fixtures] == [
        "PLAN-001-local-golden",
        "PLAN-002-escalation",
        "PLAN-003-infeasible",
        "PLAN-004-budget-downgrade",
        "PLAN-005-low-confidence",
        "PLAN-006-loading",
    ]
    assert {json.loads(path.read_text())["expected_state"] for path in fixtures} == {
        "executed",
        "escalated",
        "infeasible",
        "loading",
    }


class _StaticAdapter:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, step, request) -> RawResponse:
        return RawResponse(
            content=self.content,
            model_used=step.model_id,
            input_tokens=1,
            output_tokens=1,
            cost_usd=step.estimate.cost_usd,
            latency_ms=10,
            raw={"stub": True},
        )


class _CountingAdapter(_StaticAdapter):
    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.calls = 0

    def invoke(self, step, request) -> RawResponse:
        self.calls += 1
        return super().invoke(step, request)


class _FailingStreamAdapter:
    def invoke_stream(self, step, request):
        yield "partial"
        raise RuntimeError("stream broke")

from __future__ import annotations

import time
import uuid
from typing import Any, Mapping

from .budget import BudgetLedger
from .cache import PlanCache, task_signature
from .constraints import ExecutionConstraints
from .estimators import CapabilityEstimator, CostModel, LatencyModel
from .solver import ExecutionPlan, PlanSolver
from .targets import TargetRegistry, default_registry
from .taskclass import derive_task_class


class Planner:
    def __init__(
        self,
        target_registry: TargetRegistry | None = None,
        budget_ledger: BudgetLedger | None = None,
        cache: PlanCache | None = None,
        cost_model: CostModel | None = None,
        latency_model: LatencyModel | None = None,
        capability_estimator: CapabilityEstimator | None = None,
        solver: PlanSolver | None = None,
    ) -> None:
        self.target_registry = target_registry or default_registry()
        self.budget_ledger = budget_ledger or BudgetLedger()
        self.cache = cache or PlanCache()
        self.cost_model = cost_model or CostModel()
        self.latency_model = latency_model or LatencyModel()
        self.capability_estimator = capability_estimator or CapabilityEstimator()
        self.solver = solver or PlanSolver()

    def plan(self, request: Mapping[str, Any], constraints: ExecutionConstraints) -> ExecutionPlan:
        started = time.perf_counter()
        signature = task_signature(request)
        request_id = str(request.get("request_id") or request.get("id") or f"req-{uuid.uuid4().hex[:12]}")
        cached = self.cache.get(signature, constraints)
        if cached is not None:
            cached.request_id = request_id
            cached.planning_ms = (time.perf_counter() - started) * 1000.0
            if "cache_hit" not in cached.flags:
                cached.flags.append("cache_hit")
            return cached

        task_class = derive_task_class(request)
        plan = self.solver.solve(
            request_id=request_id,
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            request=request,
            constraints=constraints,
            task_class=task_class,
            target_registry=self.target_registry,
            cost_model=self.cost_model,
            latency_model=self.latency_model,
            capability_estimator=self.capability_estimator,
            budget_ledger=self.budget_ledger,
            planning_ms=(time.perf_counter() - started) * 1000.0,
        )
        self.cache.put(signature, constraints, plan)
        return plan

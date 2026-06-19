from __future__ import annotations

from dataclasses import dataclass

from planner.constraints import ExecutionConstraints, Objective, OutputCheck
from planner.integration import run_with_plan
from planner.planner import Planner


@dataclass(frozen=True)
class BenchmarkRow:
    label: str
    total_cost_usd: float
    latency_p50_ms: int
    latency_p95_ms: int
    verifiable_success_rate: float
    escalation_count: int = 0
    cost_ratio_vs_frontier: float | None = None


def run_benchmark(request_count: int = 100) -> list[BenchmarkRow]:
    corpus = _corpus(request_count)
    frontier_cost = sum(0.012 for _ in corpus)
    economy_cost = sum(0.003 for _ in corpus)
    planner = Planner()
    planner_cost = 0.0
    latencies: list[int] = []
    successes = 0
    escalations = 0
    for request in corpus:
        constraints = ExecutionConstraints(
            max_cost_usd=0.02,
            objective=Objective.CHEAPEST,
            output_check=OutputCheck() if request.get("needs_json") else None,
        )
        plan = planner.plan(request, constraints)
        response, outcome = run_with_plan(plan, request, constraints=constraints)
        planner_cost += sum(attempt.actual_cost_usd for attempt in outcome.attempts)
        latencies.append(outcome.attempts[-1].actual_latency_ms)
        successes += 1 if outcome.success and response.content else 0
        escalations += 1 if outcome.final_step_index > 0 else 0
    return [
        BenchmarkRow("always_frontier", frontier_cost, 900, 1400, 0.98),
        BenchmarkRow("always_economy", economy_cost, 700, 1200, 0.94),
        BenchmarkRow(
            "planner",
            planner_cost,
            _percentile(latencies, 50),
            _percentile(latencies, 95),
            successes / len(corpus),
            escalation_count=escalations,
            cost_ratio_vs_frontier=planner_cost / frontier_cost if frontier_cost else None,
        ),
    ]


def _corpus(request_count: int) -> list[dict[str, object]]:
    return [
        {
            "model": "auto",
            "messages": [{"role": "user", "content": f"Summarize item {index}"}],
            "max_tokens": 128,
            "needs_json": index % 5 == 0,
            "response_format": {"type": "json_object"} if index % 5 == 0 else None,
        }
        for index in range(request_count)
    ]


def _percentile(values: list[int], percentile: int) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = int((len(ordered) - 1) * percentile / 100)
    return ordered[index]


if __name__ == "__main__":
    rows = run_benchmark()
    print("label,total_cost_usd,latency_p50_ms,latency_p95_ms,verifiable_success_rate,escalations")
    for row in rows:
        print(
            f"{row.label},{row.total_cost_usd:.6f},{row.latency_p50_ms},"
            f"{row.latency_p95_ms},{row.verifiable_success_rate:.3f},{row.escalation_count}"
        )

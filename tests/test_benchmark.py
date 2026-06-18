from __future__ import annotations

from colony.benchmark import Benchmark
from colony.chaos import ChaosProfile
from colony.models import make_eval_batch
from colony.provider import MockProvider


def test_hostile_benchmark_colony_beats_naive(tmp_path):
    profile = ChaosProfile("hostile", seed=1337, duration_s=640.0, loss_rate=0.08, pool_size=5)
    result = Benchmark(lambda: MockProvider(seed=profile.seed), profile=profile, db_dir=tmp_path).run(
        make_eval_batch(),
        budget=10.0,
    )

    assert result.colony.completion_rate > result.naive.completion_rate
    assert result.colony.human_interventions == 0


def test_benchmark_table_contains_rows_and_delta(tmp_path):
    profile = ChaosProfile("moderate", seed=7331, duration_s=200.0, loss_rate=0.02, pool_size=5)
    result = Benchmark(lambda: MockProvider(seed=profile.seed), profile=profile, db_dir=tmp_path).run(
        make_eval_batch(batch_size=3),
        budget=10.0,
    )

    table = result.to_table()
    assert "naive" in table
    assert "dflow-vast" in table
    assert "completion delta:" in table


def test_budget_halt_records_partial_result(tmp_path):
    profile = ChaosProfile("calm", seed=42, duration_s=100.0, loss_rate=0.0, pool_size=1)
    result = Benchmark(lambda: MockProvider(seed=profile.seed), profile=profile, db_dir=tmp_path).run(
        make_eval_batch(batch_size=3),
        budget=0.001,
    )

    assert result.colony.budget_halted is True
    assert result.colony.total_cost_usd >= 0.001

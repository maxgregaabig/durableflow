from __future__ import annotations

from colony.baseline import NaiveRunner
from colony.chaos import ChaosSchedule
from colony.controller import ColonyController
from colony.models import make_eval_batch
from colony.provider import MockProvider


def test_colony_resumes_from_last_checkpoint_after_loss(tmp_path):
    batch = make_eval_batch(batch_size=1)
    schedule = ChaosSchedule.from_offsets(7, [(14.0, 0)])

    report = ColonyController(
        MockProvider(seed=7),
        schedule,
        pool_size=1,
        db_path=tmp_path / "colony.sqlite",
    ).run_batch(batch, budget=1.0, run_id="colony-test")

    assert report.jobs_completed == 1
    assert report.recoveries == 1
    assert batch[0].current_stage == 4
    assert batch[0].checkpoint_ref == "job-00:stage:4"


def test_naive_restarts_from_stage_zero_after_loss(tmp_path):
    batch = make_eval_batch(batch_size=1)
    schedule = ChaosSchedule.from_offsets(7, [(14.0, 0)])

    report = NaiveRunner(
        MockProvider(seed=7),
        schedule,
        pool_size=1,
        db_path=tmp_path / "naive.sqlite",
    ).run_batch(batch, budget=1.0, run_id="naive-test")

    assert report.jobs_completed == 1
    assert report.instances_lost == 1
    assert batch[0].attempts == 1
    assert batch[0].current_stage == -1


def test_colony_human_interventions_zero(tmp_path):
    report = ColonyController(
        MockProvider(seed=11),
        ChaosSchedule.from_offsets(11, [(6.0, 0), (20.0, 0)]),
        pool_size=1,
        db_path=tmp_path / "colony.sqlite",
    ).run_batch(make_eval_batch(batch_size=2), budget=2.0, run_id="interventions")

    assert report.human_interventions == 0

from __future__ import annotations

from colony.chaos import ChaosSchedule


def test_same_seed_generates_identical_schedule():
    first = ChaosSchedule.generate(1337, 100.0, 0.05, 5)
    second = ChaosSchedule.generate(1337, 100.0, 0.05, 5)

    assert first.events == second.events


def test_schedule_targets_and_offsets_are_stable():
    schedule = ChaosSchedule.generate(42, 120.0, 0.04, 3)

    assert [(event.scheduled_at_offset_s, event.target_slot) for event in schedule.events] == [
        (25.5015, 0),
        (59.3279, 0),
        (65.6425, 2),
        (68.346, 2),
    ][: len(schedule.events)]

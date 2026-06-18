from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from .models import ChaosEvent
from .provider import ComputeProvider


@dataclass(frozen=True)
class ChaosProfile:
    name: str
    seed: int = 1337
    duration_s: float = 640.0
    loss_rate: float = 0.035
    pool_size: int = 5


class ChaosSchedule:
    def __init__(self, seed: int, events: Iterable[ChaosEvent]):
        self.seed = seed
        self.events = tuple(sorted(events, key=lambda event: event.scheduled_at_offset_s))

    @classmethod
    def generate(
        cls,
        seed: int,
        duration_s: float,
        loss_rate: float,
        pool_size: int,
    ) -> "ChaosSchedule":
        if loss_rate <= 0:
            return cls(seed, [])
        rng = random.Random(seed)
        events: list[ChaosEvent] = []
        now = 0.0
        index = 0
        while now < duration_s:
            now += rng.expovariate(loss_rate)
            if now >= duration_s:
                break
            events.append(
                ChaosEvent(
                    event_id=f"loss-{index:03d}",
                    scheduled_at_offset_s=round(now, 4),
                    event_type="evict",
                    target_slot=rng.randrange(pool_size),
                )
            )
            index += 1
        return cls(seed, events)

    @classmethod
    def from_offsets(cls, seed: int, offsets: list[tuple[float, int]]) -> "ChaosSchedule":
        return cls(
            seed,
            [
                ChaosEvent(
                    event_id=f"loss-{index:03d}",
                    scheduled_at_offset_s=offset,
                    event_type="evict",
                    target_slot=slot,
                )
                for index, (offset, slot) in enumerate(offsets)
            ],
        )

    def between(self, start: float, end: float, slot: int) -> ChaosEvent | None:
        for event in self.events:
            if event.target_slot == slot and start < event.scheduled_at_offset_s <= end:
                return event
        return None

    def apply(self, event: ChaosEvent, provider: ComputeProvider, instance, *, now: float) -> None:
        reason = "simulated_eviction" if provider.mode == "mock" else "controller_induced_termination"
        provider.lose(instance, now=now, reason=reason)

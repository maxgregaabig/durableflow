from __future__ import annotations

import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .models import Instance, InstanceStatus, Job, StageResult


class ComputeProvider(ABC):
    mode: str

    @abstractmethod
    def acquire(self, spec: dict[str, Any] | None = None, *, slot: int = 0, now: float = 0.0) -> Instance:
        raise NotImplementedError

    @abstractmethod
    def release(self, instance: Instance, *, now: float = 0.0) -> None:
        raise NotImplementedError

    @abstractmethod
    def health(self, instance: Instance) -> InstanceStatus:
        raise NotImplementedError

    @abstractmethod
    def price(self, gpu_type: str) -> float:
        raise NotImplementedError

    @abstractmethod
    def run_stage(self, instance: Instance, job: Job, stage: int) -> StageResult:
        raise NotImplementedError

    @abstractmethod
    def lose(self, instance: Instance, *, now: float = 0.0, reason: str = "simulated_eviction") -> None:
        raise NotImplementedError


@dataclass
class MockProvider(ComputeProvider):
    seed: int = 1337
    gpu_type: str = "mock-a10"
    mode: str = "mock"
    _counter: int = 0
    _instances: dict[str, Instance] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def acquire(self, spec: dict[str, Any] | None = None, *, slot: int = 0, now: float = 0.0) -> Instance:
        self._counter += 1
        gpu_type = (spec or {}).get("gpu_type", self.gpu_type)
        instance = Instance(
            instance_id=f"i-{self._counter:03d}",
            provider=self.mode,
            gpu_type=gpu_type,
            cost_per_hour_usd=self.price(gpu_type),
            status=InstanceStatus.HEALTHY,
            slot=slot,
            acquired_at=now,
            provider_handle={"mock": True, "slot": slot},
        )
        self._instances[instance.instance_id] = instance
        return instance

    def release(self, instance: Instance, *, now: float = 0.0) -> None:
        instance.status = InstanceStatus.RELEASED
        instance.released_at = now

    def health(self, instance: Instance) -> InstanceStatus:
        return instance.status

    def price(self, gpu_type: str) -> float:
        prices = {"mock-a10": 1.20, "mock-l4": 0.80, "mock-a100": 2.40}
        return prices.get(gpu_type, 1.0)

    def run_stage(self, instance: Instance, job: Job, stage: int) -> StageResult:
        durations = job.spec.get("stage_durations_s") or [5.0] * job.stage_count
        duration = float(durations[stage])
        return StageResult(
            stage_index=stage,
            duration_s=duration,
            output={
                "job_id": job.job_id,
                "stage": job.spec.get("stages", [])[stage] if job.spec.get("stages") else f"stage_{stage}",
                "instance_id": instance.instance_id,
            },
        )

    def lose(self, instance: Instance, *, now: float = 0.0, reason: str = "simulated_eviction") -> None:
        instance.status = InstanceStatus.LOST
        instance.lost_at = now
        instance.provider_handle["loss_reason"] = reason


class VastProvider(MockProvider):
    mode = "live"

    def __init__(self, seed: int = 1337, gpu_type: str = "vast-small") -> None:
        if not os.getenv("VAST_API_KEY"):
            raise RuntimeError("VastProvider requires VAST_API_KEY; use MockProvider for tests and demos")
        super().__init__(seed=seed, gpu_type=gpu_type, mode="live")

    def price(self, gpu_type: str) -> float:
        # Narrow live smoke surface: real implementations should reconcile this with Vast billing.
        return 0.75

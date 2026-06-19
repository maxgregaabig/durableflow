from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from .constraints import Privacy, Tier


@dataclass(frozen=True)
class TargetProfile:
    id: str
    name: str
    tier: Tier
    model_id: str
    privacy_class: Privacy
    region: str | None
    cost_in_per_1k: float
    cost_out_per_1k: float
    enabled: bool = True


@dataclass(frozen=True)
class TargetHealth:
    target_id: str
    available: bool
    last_checked_at: str
    consecutive_failures: int = 0


class TargetRegistry:
    def __init__(
        self,
        targets: Iterable[TargetProfile] | None = None,
        health: Iterable[TargetHealth] | None = None,
    ) -> None:
        self._targets = {target.id: target for target in targets or []}
        self._health = {item.target_id: item for item in health or []}

    def register(self, target: TargetProfile) -> None:
        if target.tier == Tier.NONE:
            raise ValueError("target tier must be local, economy, or frontier")
        self._targets[target.id] = target

    def set_health(self, health: TargetHealth) -> None:
        self._health[health.target_id] = health

    def all_targets(self) -> list[TargetProfile]:
        return list(self._targets.values())

    def healthy_targets(self) -> list[TargetProfile]:
        return [
            target
            for target in self._targets.values()
            if target.enabled and self._health.get(target.id, _default_health(target.id)).available
        ]

    def health_for(self, target_id: str) -> TargetHealth:
        return self._health.get(target_id, _default_health(target_id))


def default_targets() -> list[TargetProfile]:
    return [
        TargetProfile(
            id="local-ollama",
            name="Local Ollama",
            tier=Tier.LOCAL,
            model_id="ollama-local",
            privacy_class=Privacy.LOCAL_ONLY,
            region=None,
            cost_in_per_1k=0.0,
            cost_out_per_1k=0.0,
        ),
        TargetProfile(
            id="cloud-economy",
            name="Cloud Economy",
            tier=Tier.ECONOMY,
            model_id="economy-chat",
            privacy_class=Privacy.ANY,
            region="us",
            cost_in_per_1k=0.0005,
            cost_out_per_1k=0.0015,
        ),
        TargetProfile(
            id="cloud-frontier",
            name="Cloud Frontier",
            tier=Tier.FRONTIER,
            model_id="frontier-chat",
            privacy_class=Privacy.ANY,
            region="us",
            cost_in_per_1k=0.003,
            cost_out_per_1k=0.015,
        ),
    ]


def default_registry() -> TargetRegistry:
    return TargetRegistry(default_targets())


def _default_health(target_id: str) -> TargetHealth:
    return TargetHealth(
        target_id=target_id,
        available=True,
        last_checked_at=datetime.now(UTC).isoformat(),
        consecutive_failures=0,
    )

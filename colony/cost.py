from __future__ import annotations

from dataclasses import dataclass, field

from .models import Instance


@dataclass
class CostAccountant:
    charges: list[tuple[str, float, float, float]] = field(default_factory=list)

    def charge(self, instance: Instance, seconds: float) -> float:
        amount = seconds / 3600.0 * instance.cost_per_hour_usd
        self.charges.append((instance.instance_id, seconds, instance.cost_per_hour_usd, amount))
        return amount

    def total(self) -> float:
        return round(sum(charge[-1] for charge in self.charges), 8)

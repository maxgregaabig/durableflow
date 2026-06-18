from __future__ import annotations

from colony.cost import CostAccountant
from colony.models import Instance


def test_cost_computed_from_instance_seconds_and_price():
    instance = Instance("i-1", "mock", "mock-a10", 3.60)
    accountant = CostAccountant()

    assert accountant.charge(instance, 1800.0) == 1.8
    assert accountant.total() == 1.8


def test_cost_varies_with_seconds():
    instance = Instance("i-1", "mock", "mock-a10", 3.60)
    accountant = CostAccountant()

    accountant.charge(instance, 10.0)
    first = accountant.total()
    accountant.charge(instance, 20.0)

    assert accountant.total() > first

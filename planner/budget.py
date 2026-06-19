from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Remaining:
    budget_id: str
    limit_usd: float
    spent_usd: float

    @property
    def remaining_usd(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    @property
    def spent_ratio(self) -> float:
        if self.limit_usd <= 0:
            return 1.0
        return self.spent_usd / self.limit_usd

    @property
    def near_exhaustion(self) -> bool:
        return self.spent_ratio >= 0.9


class BudgetLedger:
    def __init__(self, store=None) -> None:
        self.store = store
        self._budgets: dict[str, tuple[float, float]] = {}

    def set_limit(self, budget_id: str, limit_usd: float, spent_usd: float = 0.0) -> None:
        if limit_usd < 0 or spent_usd < 0:
            raise ValueError("budget amounts must be non-negative")
        self._budgets[budget_id] = (limit_usd, spent_usd)
        if self.store is not None:
            self.store.upsert_budget(budget_id, limit_usd, spent_usd)

    def check(self, budget_id: str | None) -> Remaining | None:
        if budget_id is None:
            return None
        if self.store is not None:
            stored = self.store.get_budget(budget_id)
            if stored is not None:
                return stored
        if budget_id not in self._budgets:
            return None
        limit_usd, spent_usd = self._budgets[budget_id]
        return Remaining(budget_id=budget_id, limit_usd=limit_usd, spent_usd=spent_usd)

    def charge(self, budget_id: str | None, actual_cost: float) -> None:
        if budget_id is None:
            return
        if actual_cost < 0:
            raise ValueError("actual_cost must be non-negative")
        remaining = self.check(budget_id)
        if remaining is None:
            return
        spent = remaining.spent_usd + actual_cost
        self._budgets[budget_id] = (remaining.limit_usd, spent)
        if self.store is not None:
            self.store.upsert_budget(budget_id, remaining.limit_usd, spent)

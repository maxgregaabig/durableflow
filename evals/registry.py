"""ScorerRegistry: resolves required scorer names to scorer instances (spec §6.3).

The gate asks the registry to resolve a manifest's ``required_scorers`` list.
Missing scorers are surfaced explicitly so the gate can become ``incomplete``
(spec §6.5 rule 3) rather than silently passing.
"""

from __future__ import annotations

from dataclasses import dataclass

from .scorers import EvalScorer


@dataclass(frozen=True)
class ScorerResolution:
    """Outcome of resolving required scorer names.

    ``missing`` is the set of required names with no registered instance; the
    gate treats a non-empty ``missing`` as ``incomplete`` (§6.5 rule 3).
    """

    scorers: list[EvalScorer]
    missing: list[str]


class ScorerRegistry:
    """Registers scorers by name and resolves required scorer sets."""

    def __init__(self, scorers: list[EvalScorer] | None = None):
        self._by_name: dict[str, EvalScorer] = {}
        for scorer in scorers or []:
            self.register(scorer)

    def register(self, scorer: EvalScorer) -> EvalScorer:
        name = getattr(scorer, "name", None)
        if not isinstance(name, str) or not name:
            raise ValueError("scorer must expose a non-empty string `name`")
        self._by_name[name] = scorer
        return scorer

    def get(self, name: str) -> EvalScorer | None:
        return self._by_name.get(name)

    def names(self) -> list[str]:
        return sorted(self._by_name)

    def resolve(self, required_scorers: list[str]) -> ScorerResolution:
        """Resolve required scorer names; report any that are missing."""
        resolved: list[EvalScorer] = []
        missing: list[str] = []
        for name in required_scorers:
            scorer = self._by_name.get(name)
            if scorer is None:
                missing.append(name)
            else:
                resolved.append(scorer)
        return ScorerResolution(scorers=resolved, missing=missing)


__all__ = ["ScorerRegistry", "ScorerResolution"]

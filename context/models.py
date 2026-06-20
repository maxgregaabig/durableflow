from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InfoArtifact:
    artifact_id: str
    workflow_id: str
    artifact_role: str
    source: str
    source_type: str
    content_digest: str
    content_ref: str | None
    token_count: int
    observed_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextLedgerEvent:
    event_id: str
    workflow_id: str
    step_name: str
    artifact_id: str | None
    event_type: str
    event_scope: str
    event_time: str
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    workflow_id: str
    step_name: str
    step_result_id: str | None
    prompt_digest: str
    response_digest: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    created_at: str


@dataclass(frozen=True)
class DecisionLineage:
    decision_id: str
    artifact_id: str
    influence_type: str
    influence_score: float
    evidence_ref: str | None = None


@dataclass(frozen=True)
class ContextAudit:
    workflow_id: str
    artifacts: list[InfoArtifact]
    events: list[ContextLedgerEvent]
    decisions: list[DecisionRecord]
    lineage: list[DecisionLineage]

    @property
    def selected_count(self) -> int:
        return _count_events(self.events, "selected")

    @property
    def consumed_count(self) -> int:
        return _count_events(self.events, "consumed")

    @property
    def influential_count(self) -> int:
        return len({entry.artifact_id for entry in self.lineage})

    @property
    def decision_count(self) -> int:
        return len(self.decisions)


def _count_events(events: list[ContextLedgerEvent], event_type: str) -> int:
    return len(
        {
            (event.workflow_id, event.step_name, event.artifact_id)
            for event in events
            if event.event_type == event_type and event.artifact_id is not None
        }
    )

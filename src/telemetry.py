from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


@dataclass(frozen=True)
class WorkflowEvent:
    event_type: str
    workflow_id: str
    step_name: str | None = None
    timestamp: str = ""
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    model_used: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "workflow_id": self.workflow_id,
            "step_name": self.step_name,
            "timestamp": self.timestamp or datetime.now(UTC).isoformat(),
            "duration_ms": self.duration_ms,
            "cost_usd": self.cost_usd,
            "model_used": self.model_used,
            "metadata": self.metadata,
        }


class TelemetryLogger:
    def __init__(
        self,
        path: str | Path | None = None,
        stream: TextIO | None = None,
        echo: bool = True,
    ):
        self.path = Path(path) if path else None
        self.stream = stream if stream is not None else sys.stdout
        self.echo = echo
        self.events: list[dict[str, Any]] = []
        if self.path and self.path.exists():
            self.path.unlink()

    def log(self, event: WorkflowEvent) -> None:
        payload = event.as_dict()
        self.events.append(payload)
        line = json.dumps(payload, sort_keys=True)
        if self.echo:
            print(line, file=self.stream)
        if self.path:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def log_step_start(self, workflow_id: str, step_name: str) -> None:
        self.log(WorkflowEvent("step_start", workflow_id, step_name))

    def log_step_complete(
        self,
        workflow_id: str,
        step_name: str,
        duration_ms: float,
        cost_usd: float = 0.0,
        model_used: str | None = None,
    ) -> None:
        self.log(
            WorkflowEvent(
                "step_complete",
                workflow_id,
                step_name,
                duration_ms=duration_ms,
                cost_usd=cost_usd,
                model_used=model_used,
            )
        )

    def log_crash(self, workflow_id: str, last_checkpoint: int) -> None:
        self.log(
            WorkflowEvent(
                "crash_detected",
                workflow_id,
                metadata={"last_checkpoint": last_checkpoint},
            )
        )

    def log_resume(self, workflow_id: str, step_name: str) -> None:
        self.log(WorkflowEvent("workflow_resumed", workflow_id, step_name))

    def log_approval_request(self, workflow_id: str, step_name: str, gate_id: str) -> None:
        self.log(
            WorkflowEvent(
                "approval_requested",
                workflow_id,
                step_name,
                metadata={"gate_id": gate_id},
            )
        )

    def log_approval_decision(
        self,
        workflow_id: str,
        step_name: str,
        decision: str,
        decided_by: str | None = None,
    ) -> None:
        self.log(
            WorkflowEvent(
                "approval_decision",
                workflow_id,
                step_name,
                metadata={"decision": decision, "decided_by": decided_by},
            )
        )

    def log_fallback(
        self,
        workflow_id: str,
        step_name: str,
        from_model: str,
        to_model: str,
        error: str,
    ) -> None:
        self.log(
            WorkflowEvent(
                "model_fallback",
                workflow_id,
                step_name,
                metadata={"from_model": from_model, "to_model": to_model, "error": error},
            )
        )

    def log_workflow_complete(self, workflow_id: str) -> None:
        summary = self.summarize_workflow(workflow_id)
        self.log(WorkflowEvent("workflow_complete", workflow_id, metadata=summary))

    def summarize_workflow(self, workflow_id: str) -> dict[str, Any]:
        events = [event for event in self.events if event["workflow_id"] == workflow_id]
        complete_steps = [event for event in events if event["event_type"] == "step_complete"]
        return {
            "total_cost": round(sum(float(event["cost_usd"]) for event in complete_steps), 8),
            "total_latency_ms": round(sum(float(event["duration_ms"]) for event in complete_steps), 2),
            "step_count": len(complete_steps),
            "fallback_count": sum(1 for event in events if event["event_type"] == "model_fallback"),
            "crash_recoveries": sum(1 for event in events if event["event_type"] == "crash_detected"),
            "approval_wait_events": sum(
                1 for event in events if event["event_type"] == "approval_requested"
            ),
        }


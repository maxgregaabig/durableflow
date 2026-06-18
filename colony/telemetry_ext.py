from __future__ import annotations

from typing import Any

from src.telemetry import TelemetryLogger


def log_colony_event(
    telemetry: TelemetryLogger,
    run_id: str,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    telemetry.log_event(event_type, run_id, metadata=metadata or {})

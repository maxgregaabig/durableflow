from __future__ import annotations

import json
from io import StringIO

from colony.telemetry_ext import log_colony_event
from src.telemetry import TelemetryLogger


def test_workflow_complete_summary_is_json() -> None:
    stream = StringIO()
    telemetry = TelemetryLogger(stream=stream, echo=True)
    telemetry.log_step_complete("wf", "one", 10.0, 0.25, "mock")
    telemetry.log_workflow_complete("wf")
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert lines[-1]["event_type"] == "workflow_complete"
    assert lines[-1]["metadata"]["total_cost"] == 0.25
    assert lines[-1]["metadata"]["step_count"] == 1


def test_crash_event_contains_last_checkpoint() -> None:
    stream = StringIO()
    telemetry = TelemetryLogger(stream=stream, echo=True)
    telemetry.log_crash("wf", 1)
    event = json.loads(stream.getvalue())
    assert event["event_type"] == "crash_detected"
    assert event["metadata"]["last_checkpoint"] == 1


def test_colony_event_uses_generic_telemetry_hook() -> None:
    stream = StringIO()
    telemetry = TelemetryLogger(stream=stream, echo=True)

    log_colony_event(telemetry, "run-1", "job_recovering", {"job_id": "job-07"})

    event = json.loads(stream.getvalue())
    assert event["event_type"] == "job_recovering"
    assert event["workflow_id"] == "run-1"
    assert event["metadata"]["job_id"] == "job-07"

# Module 5: Observability and Audit Trails

**Duration:** 1 hour  
**Format:** JSONL parsing lab

## Summary

`TelemetryLogger` writes structured JSON lines for steps, crashes, resumes, approvals, fallback, and completion. In production, the same events would feed LangSmith, OpenTelemetry, or an SIEM — DurableFlow keeps the event model minimal and local.

## Key concepts

- Event types: `step_start`, `step_complete`, `crash_detected`, `workflow_resumed`, `approval_requested`, `approval_decision`, `model_fallback`, `workflow_complete`
- JSONL as audit trail for non-deterministic paths
- Cross-check telemetry with SQLite `step_results`

## Labs

| ID | Task |
|----|------|
| E8 | [Read audit trail](../exercises.md#exercise-8-read-the-audit-trail) |
| W8 | [Telemetry timeline](workshop-exercises.md#w8-telemetry-timeline) |

## Demo commands

```bash
./start.sh crash
jq -r '.event_type' examples/crash_resume_demo.telemetry.jsonl | sort | uniq -c
```

## Readings

- [dflow-arch.md](../dflow-arch.md) — Telemetry Events
- [curriculum.md — Module 5](curriculum.md#module-5-observability-and-audit-trails)

## Exit ticket

Which two artifacts would you show an incident reviewer: DB tables or JSONL events?

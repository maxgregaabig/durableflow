# Module 7: Agent Readiness and the Durable Agent Pattern

**Duration:** 2 hours  
**Format:** Readiness demo + MCP lab + checklist

## Summary

The Agent Readiness Pack wraps a reason-act-observe agent with per-turn checkpoints, gated writes, idempotency, and six failure scenarios. The report is verdict-first: ship or do not ship, durability delta, primary blocker. The [Durable Agent Pattern](../field-pattern.md) generalizes this for field deployments.

## Key concepts

- Six failure modes: tool timeout, malformed output, prompt injection, context overflow, model fallback, crash after side effect
- Naked vs wrapped comparison in `readiness_report.md`
- MCP gated write path (`./start.sh mcp`)
- ADK adapter as boundary only (not full Runner E2E)

## Labs

| ID | Task |
|----|------|
| W10 | [MCP write trace](workshop-exercises.md#w10-mcp-write-trace) |
| W11 | [Field checklist](workshop-exercises.md#w11-field-checklist-for-a-hypothetical-deployment) |
| Capstone C | [Readiness scenario](capstone.md#track-c-readiness-scenario) |

## Demo commands

```bash
./start.sh readiness
./start.sh mcp
cat readiness_report.md
```

## Readings

- [field-pattern.md](../field-pattern.md)
- [readiness/README.md](../../readiness/README.md)
- [curriculum.md — Module 7](curriculum.md#module-7-agent-readiness-and-the-durable-agent-pattern)

## Exit ticket

Name the single unsafe behavior that would block ship in the readiness demo's naked agent run.

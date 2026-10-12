# Module 1: The Operational Gap

**Duration:** 45 minutes  
**Format:** Lecture + repo tour

## Summary

Production agent failures rarely come from weak prompts. They come from context growth, partial failure, runaway cost, approval latency, and opaque execution paths. DurableFlow exists to make those mechanics visible in a small, testable runtime.

## Key concepts

1. **Five scaling problems** — context, failure, cost, approval, observability
2. **Positioning** — reference implementation, not a replacement for Temporal or LangGraph
3. **Repo map** — `src/` (engine), `examples/` (demos), `tests/` (contracts), extensions (`colony/`, `readiness/`)

## Activities

| Activity | Type | Time |
|----------|------|------|
| Discussion: last staging failure | Group | 10 min |
| `./start.sh crash` | Demo | 10 min |
| `./start.sh test` (tail output) | Demo | 5 min |
| Repo structure walkthrough | Lecture | 15 min |

## Readings

- [README.md](../../README.md)
- [curriculum.md — Module 1](curriculum.md#module-1-the-operational-gap)

## Exit ticket

In one sentence: what does "durable execution" mean in DurableFlow?

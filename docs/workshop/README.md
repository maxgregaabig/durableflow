# DurableFlow Workshop

A hands-on workshop for backend engineers and infrastructure-minded AI teams who need to understand the **operational layer** underneath production agentic workflows — not prompt engineering or RAG.

This workshop teaches the primitives DurableFlow isolates in plain Python and SQLite:

- Durable execution and checkpointing
- Real crash recovery (process kill, not mocked exceptions)
- Human-in-the-loop approval gates
- Model routing with fallback and per-step cost accounting
- Context selection under a hard token budget
- Idempotent side effects
- Telemetry over non-deterministic paths
- Measured durability on spot-like compute (Colony)
- Deployment readiness evaluation (Agent Readiness Pack)

## Who this is for

| Audience | Outcome |
|----------|---------|
| Senior backend engineers | Can explain checkpoint semantics, idempotency keys, and approval pause/resume from SQLite evidence |
| Platform / infra engineers | Can map DurableFlow primitives to Temporal, LangGraph, LiteLLM, and LangSmith responsibilities |
| Tech leads evaluating agent rollouts | Can run a readiness harness and defend a ship / do-not-ship verdict with measured deltas |
| Workshop facilitators | Can deliver a 1-, 2-, or 3-day program with timed lessons, labs, and a capstone |

## Prerequisites

- Python 3.11+ on macOS or Linux
- Comfort reading Python and SQL
- Familiarity with REST APIs and basic LLM concepts (tokens, providers)
- No API keys required for core labs

```bash
git clone https://github.com/marcospolanco/durableflow.git
cd durableflow
./start.sh crash
./start.sh test
```

## Workshop formats

| Format | Duration | Modules | Best for |
|--------|----------|---------|----------|
| **Essentials** | 1 day (6–7 h) | 1–5 | Teams new to agent ops; focus on core runtime |
| **Standard** | 2 days (12–14 h) | 1–7 | Full primitive coverage + extensions |
| **Deep dive** | 3 days (18–20 h) | 1–7 + capstone | Teams preparing a production rollout |

Suggested daily boundaries:

- **Day 1:** Modules 1–3 (why ops matter, durable engine, human gates)
- **Day 2:** Modules 4–5 (cost, context, observability) + Module 6 intro (Colony)
- **Day 3:** Module 7 (readiness) + capstone build and review

## Curriculum map

| Module | Topic | Duration | Doc |
|--------|-------|----------|-----|
| 1 | The operational gap | 45 min | [module-01-operational-gap.md](module-01-operational-gap.md) |
| 2 | Durable execution engine | 2 h | [module-02-durable-engine.md](module-02-durable-engine.md) |
| 3 | Human-in-the-loop gates | 1.5 h | [module-03-human-gates.md](module-03-human-gates.md) |
| 4 | Cost, routing, and context budgets | 2 h | [module-04-cost-and-context.md](module-04-cost-and-context.md) |
| 5 | Observability and audit trails | 1 h | [module-05-observability.md](module-05-observability.md) |
| 6 | Colony: measured durability on hostile compute | 1.5 h | [module-06-colony.md](module-06-colony.md) |
| 7 | Agent readiness and the Durable Agent Pattern | 2 h | [module-07-readiness.md](module-07-readiness.md) |
| Capstone | Extend or harden a workflow | 2–4 h | [capstone.md](capstone.md) |

Full lesson plan with learning objectives, timing, and exercise index: **[curriculum.md](curriculum.md)**.

Facilitator timing, discussion prompts, and troubleshooting: **[facilitator-guide.md](facilitator-guide.md)**.

Extended workshop-only labs (beyond [exercises.md](../exercises.md)): **[workshop-exercises.md](workshop-exercises.md)**.

## Learning outcomes

By the end of the **Standard** workshop, participants can:

1. **Diagram** the inbox triage workflow, checkpoint indices, and workflow vs approval-queue state layers.
2. **Inspect** SQLite after a real `os._exit` crash and predict resume behavior from `current_step` and `step_results`.
3. **Implement** idempotency for a new side-effecting step using `side_effect_log`.
4. **Configure** model routing policy and interpret fallback events in telemetry JSONL.
5. **Explain** why TF-IDF + greedy packing is used here (visibility over retrieval quality).
6. **Compare** naive vs durable runners under an identical chaos seed (Colony).
7. **Run** the readiness harness and articulate what changed between naked and wrapped agents.
8. **Map** each primitive to a production tool (Temporal, LiteLLM, LangSmith, etc.) without conflating roles.

## Repo artifacts used in the workshop

| Artifact | Role in workshop |
|----------|------------------|
| `examples/crash_resume_demo.py` | Module 2 — real crash and resume |
| `examples/inbox_triage_demo.py` | Modules 3–5 — golden path with approval |
| `examples/chaos_benchmark_demo.py` | Module 6 — Colony benchmark |
| `examples/readiness_demo.py` | Module 7 — readiness report |
| `examples/mcp_demo.py` | Module 7 — gated write over MCP |
| `src/engine.py`, `src/store.py` | Modules 2–3 — engine and persistence |
| `src/workflows.py` | Modules 3–5 — step logic and idempotency |
| `tests/` | All modules — behavior contracts |
| `docs/dflow-arch.md` | Reference diagrams between modules |
| `docs/field-pattern.md` | Module 7 — Durable Agent Pattern |

## Assessment

| Level | Requirement |
|-------|-------------|
| **Participation** | Complete labs for Modules 2–5; run `./start.sh test` green locally |
| **Proficiency** | Pass the [module quizzes](curriculum.md#assessment-quizzes) and explain one telemetry event stream |
| **Mastery** | Complete one [capstone track](capstone.md) with a test and a short design note |

## Suggested reading order

1. [README.md](../../README.md) — positioning and quick start
2. This workshop README — pick your format
3. [curriculum.md](curriculum.md) — follow module by module
4. [exercises.md](../exercises.md) — core hands-on tasks (referenced throughout)
5. [workshop-exercises.md](workshop-exercises.md) — additional labs and capstone prep
6. [dflow-arch.md](../dflow-arch.md) — architecture reference
7. Extension READMEs: [colony/README.md](../../colony/README.md), [readiness/README.md](../../readiness/README.md)

## What this workshop is not

- A prompt engineering or RAG tutorial
- A LangGraph / CrewAI / Temporal certification
- A claim that DurableFlow replaces production orchestrators

The goal is **inspectable mechanics**: small enough to read in an afternoon, rigorous enough to inform production architecture decisions.

# DurableFlow Planner

The planner is a constraint-aware selection layer with verifiable escalation across local and cloud tiers.

It accepts an OpenAI-compatible chat-completion request with `model: "auto"` plus declarative constraints such as cost, latency, privacy, tier floor, objective, session budget, and optional output checks. It returns a durable execution plan: a primary target and ordered fallbacks. Escalation happens only after verifiable failure, such as a transport error, latency breach, or failed output check.

The planner does not predict or optimize answer quality. Its learned signal is per-target, per-task-class success rate over verifiable outcomes.

Key modules:

- `constraints.py` parses request headers into `ExecutionConstraints`.
- `planner.py` derives task class, checks cache/budget, and builds an `ExecutionPlan`.
- `solver.py` applies hard constraints and ranks candidate targets.
- `integration.py` executes the plan durably through `PlannerStore`.
- `views.py` and `render.py` build and render trace views.
- `api.py` exposes framework-free helpers for `/v1/chat/completions` and plan trace lookup.

Scenario fixtures live in `data/planner_scenarios/`.

# Documentation

Start here after running `./start.sh crash` from the repo root.

| Document | Audience | Purpose |
|----------|----------|---------|
| [learning-path.md](learning-path.md) | **Anyone onboarding** | **Staged curriculum in dependency order, with a verification gate per stage — start here** |
| [walkthrough.md](walkthrough.md) | New contributors / reviewers | Architectural throughline plus **canonical index of all 9 `*-spec.md` and 7 `README.md` files** |
| [exercises.md](exercises.md) | Learners | Hands-on tasks to explore durability, approval, routing, and idempotency |
| [dflow-arch.md](dflow-arch.md) | Reviewers / contributors | Stack overview, architecture diagrams, and runtime invariants |
| [agent-loop.md](agent-loop.md) | Reviewers / contributors | Agentic loop (reason-act-observe) and durable bridge in `agent/runner.py` |
| [dflow-spec.md](dflow-spec.md) | Implementers | Full specification, acceptance criteria, and test plan |
| [../colony/README.md](../colony/README.md) | Operators / reviewers | Colony chaos benchmark quick start and measured result |
| [colony-methodology.md](colony-methodology.md) | Reviewers | Colony benchmark protocol, assumptions, and threats to validity |
| [../readiness/README.md](../readiness/README.md) | Operators / reviewers | Agent Readiness Pack quick start, scenarios, and build contract |
| [../planner/planner-spec.md](../planner/planner-spec.md) | Implementers / reviewers | Draft Target Planner extension spec for budgeted target selection and verifiable escalation |
| [field-pattern.md](field-pattern.md) | Implementers / reviewers | Durable Agent Pattern and field checklist |
| [context-extension.md](context-extension.md) | Implementers / reviewers | Context schema, audit contract, and privacy boundary |
| [eval-gate-spec.md](eval-gate-spec.md) | Implementers | Traces -> eval cases -> scorers -> ship gate |
| [langsmith-adapter.md](langsmith-adapter.md) | Platform teams | Optional telemetry and context lineage export |
| [opentelemetry-adapter-proposal.md](opentelemetry-adapter-proposal.md) | Platform teams | Proposal: OTel span export (not implemented) |
| [aws-deployment-proposal.md](aws-deployment-proposal.md) | Infrastructure | Proposal: AWS deployment topology |

**Suggested path:** follow [learning-path.md](learning-path.md) — it sequences the demos, source files, exercises, and specs below in dependency order. Use [walkthrough.md](walkthrough.md) as the lookup index rather than linear reading. For extension work, start with the extension README, then the linked spec or methodology.

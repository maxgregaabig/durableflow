# Documentation

Start here after running `./start.sh crash` from the repo root.

| Document | Audience | Purpose |
|----------|----------|---------|
| [exercises.md](exercises.md) | Learners | Hands-on tasks to explore durability, approval, routing, and idempotency |
| [dflow-arch.md](dflow-arch.md) | Reviewers / contributors | Architecture diagrams and runtime invariants |
| [dflow-spec.md](dflow-spec.md) | Implementers | Full specification, acceptance criteria, and test plan |
| [../colony/README.md](../colony/README.md) | Operators / reviewers | Colony chaos benchmark quick start and measured result |
| [colony-methodology.md](colony-methodology.md) | Reviewers | Colony benchmark protocol, assumptions, and threats to validity |
| [../readiness/README.md](../readiness/README.md) | Operators / reviewers | Agent Readiness Pack quick start, scenarios, and build contract |
| [../planner/planner-spec.md](../planner/planner-spec.md) | Implementers / reviewers | Draft Target Planner extension spec for budgeted target selection and verifiable escalation |
| [field-pattern.md](field-pattern.md) | Implementers / reviewers | Durable Agent Pattern and field checklist |

**Suggested path:** exercises -> architecture -> spec (if you want implementation detail). For extension work, start with the extension README, then the linked spec or methodology.

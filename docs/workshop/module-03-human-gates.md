# Module 3: Human-in-the-Loop Gates

**Duration:** 1.5 hours  
**Format:** Diagram + interactive inbox demo

## Summary

Approval uses two state layers: `approval_queue` records the operator decision; `workflows.status` updates when `WorkflowEngine.resume()` runs. Rejection is terminal by default; extension workflows may use `ApprovalRejectionPolicy.CONTINUE`.

## Key concepts

- `PauseForApproval` stops execution; checkpoint persists pending gate
- `ApprovalGate.approve()` / `reject()` do not alone resume the workflow
- Informational emails skip draft, gate, and send
- Rejection → `workflows.status = rejected`, zero side effects

## Labs

| ID | Task |
|----|------|
| E2 | [Reject draft](../exercises.md#exercise-2-reject-a-draft-and-confirm-no-send) |
| E6 | [Informational skip](../exercises.md#exercise-6-informational-email-skips-send) |
| W3 | [Rejection policies](workshop-exercises.md#w3-rejection-policies--terminate-vs-continue) |

## Demo

```bash
./start.sh inbox
```

Run twice: approve once, reject once. Compare `side_effect_log` row counts.

## Readings

- [dflow-arch.md](../dflow-arch.md) — Approval Gate, Golden Path Sequence
- [curriculum.md — Module 3](curriculum.md#module-3-human-in-the-loop-gates)

## Exit ticket

Why must the operator call `resume()` after `approve()`?

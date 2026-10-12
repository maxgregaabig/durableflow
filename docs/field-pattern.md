# Durable Agent Pattern

The Durable Agent Pattern is the field move for taking a working agent prototype and deciding whether it can safely approach customer systems.

The pattern is:

1. Wrap the agent loop in a durable shell.
2. Checkpoint every reason-act-observe turn.
3. Make every external write idempotent.
4. Use containment and risk-tiered autonomy for routine writes; reserve humans for fewer, higher-consequence decisions.
5. Run the same failure scenarios against the naked agent and the wrapped agent.
6. Ship only from measured evidence, not from demo confidence.

## Field Checklist

Use the readiness harness as a deployment checklist:

| Failure mode | Question |
|--------------|----------|
| Tool timeout | Does the agent recover with a structured observation, or hang? |
| Malformed tool output | Does bad JSON crash the loop, or become a recoverable tool error? |
| Prompt injection | Can customer data induce a proposed write, and is it paused for human review rather than claimed as an injection defense? |
| Context overflow | Does the agent stay inside token and turn budgets? |
| Model fallback | Does provider failure complete through a secondary route? |
| Crash after side effect | Does resume replay-suppress a known local mock result, while leaving remote ambiguity to an action authority? |

## Why The Delta Matters

The readiness report compares a naked agent with the same agent wrapped in DurableFlow. The point is not to claim intelligence improved. The point is to measure what the operational layer bought: blocked rogue writes, prevented duplicate writes, recovery from provider and tool failures, and complete traces for review.

That before/after delta is the artifact an implementation team can defend in front of a customer.

## Next Hard Problem

Human approval is a bridge, not the destination. The next hard problem is authorization policy: what is this workflow allowed to negotiate, commit, reveal, or modify without asking a person? DurableFlow makes that boundary explicit by routing writes through one gate. A production system would replace more of that gate with policy, customer-specific controls, and audited delegation.

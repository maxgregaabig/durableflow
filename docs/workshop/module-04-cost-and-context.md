# Module 4: Cost, Routing, and Context Budgets

**Duration:** 2 hours  
**Format:** Code walkthrough + REPL labs

## Summary

`ModelRouter` tries primary provider, then falls back on timeout/error per policy. Cost is estimated per call from token counts and model pricing. `ContextSelector` ranks corpus items with TF-IDF and packs greedily under a hard token ceiling (4096 in inbox triage). `send_reply` uses `side_effect_log` for idempotent delivery.

## Key concepts

- `RoutingPolicy`, `ModelProvider(fail=True)`, `was_fallback`
- Per-step `cost_usd` in `step_results` and telemetry
- TF-IDF + greedy packing (visibility over embedding quality)
- Idempotency key: `sha256(workflow_id:step_name:payload_hash)`

## Labs

| ID | Task |
|----|------|
| E3 | [Force fallback](../exercises.md#exercise-3-force-model-fallback) |
| E4 | [Context budget](../exercises.md#exercise-4-context-budget-enforcement) |
| E5 | [Idempotent send](../exercises.md#exercise-5-idempotent-send-on-replay) |
| W4–W7 | [Extended labs](workshop-exercises.md) |

## Code files

- `src/model_router.py`
- `src/context_selector.py`
- `src/workflows.py` — `triage_llm`, `draft_reply`, `send_reply`

## Readings

- [dflow-arch.md](../dflow-arch.md) — Model Routing, Context Selection, Idempotent Send
- [curriculum.md — Module 4](curriculum.md#module-4-cost-routing-and-context-budgets)

## Exit ticket

Where is the crash window for duplicate email sends, and how is it closed?

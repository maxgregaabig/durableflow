# Module 2: Durable Execution Engine

**Duration:** 2 hours  
**Format:** Architecture lecture + crash lab

## Summary

The workflow engine checkpoints after every completed step into SQLite. `current_step` is the index of the last finished step; `execute()` and `resume()` continue at `current_step + 1`. The crash demo kills a real subprocess with `os._exit`, not a caught exception.

## Key concepts

- Five core invariants ([dflow-arch.md](../dflow-arch.md))
- Tables: `workflows`, `step_results`, `approval_queue`, `side_effect_log`
- `WorkflowEngine.execute` vs `resume`
- `InboxTriageWorkflow.register(engine)` binding pattern

## Step index reference

| Index | Step name |
|-------|-----------|
| 0 | `ingest_email` |
| 1 | `select_context` |
| 2 | `triage_llm` |
| 3 | `draft_reply` |
| 4 | `approval_gate` |
| 5 | `send_reply` |

## Labs

| ID | Task |
|----|------|
| E1 | [Inspect checkpoints after crash](../exercises.md#exercise-1-inspect-checkpoints-after-crash) |
| W1 | [Predict resume index](workshop-exercises.md#w1-predict-resume-index-before-crash-demo) |
| W2 | [Stale running detection](workshop-exercises.md#w2-stale-running-workflow-detection) |

## Readings

- [dflow-arch.md](../dflow-arch.md) — Crash Recovery Sequence
- [curriculum.md — Module 2](curriculum.md#module-2-durable-execution-engine)

## Exit ticket

After crash during `triage_llm`, what is `current_step` and why?

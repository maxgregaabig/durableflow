# Exercises

Hands-on tasks for exploring the operational primitives in this repo. Each exercise assumes you have run:

```bash
./start.sh crash
./start.sh test
```

Use a separate SQLite path (e.g. under `/tmp/` or `examples/exercise-N.sqlite`) when experimenting so you do not overwrite demo databases.

---

## Exercise 1: Inspect checkpoints after crash

**Goal:** See durable state survive a process kill.

1. Run `./start.sh crash` and note the last checkpoint before crash (`select_context`).
2. Open the database:

   ```bash
   sqlite3 examples/crash_resume_demo.sqlite
   ```

3. Run:

   ```sql
   SELECT workflow_id, current_step, status FROM workflows;
   SELECT step_index, step_name FROM step_results ORDER BY step_index;
   ```

**Expected:** `current_step` is `1` (index of last completed step) after crash; steps 0–1 recorded; `triage_llm` not checkpointed until resume completes it.

**Stretch:** Read `step_data` JSON for accumulated step outputs.

---

## Exercise 2: Reject a draft and confirm no send

**Goal:** Human-in-the-loop rejection prevents side effects.

1. Run `./start.sh inbox`.
2. When prompted, reject the draft (`N` or anything other than `y`).
3. Inspect output for `rejected` status and `send skipped after rejection`.

Verify in SQLite:

```sql
SELECT status FROM workflows;
SELECT COUNT(*) FROM side_effect_log;
```

**Expected:** Workflow ends `rejected`; zero rows in `side_effect_log`.

---

## Exercise 3: Force model fallback

**Goal:** Observe primary failure and secondary provider success.

1. In a Python shell or small script, construct a router policy with a failing primary:

   ```python
   from src.model_router import ModelProvider, ModelRouter, RoutingPolicy

   policy = RoutingPolicy([
       ModelProvider("primary", "p", 0.01, 0.02, fail=True),
       ModelProvider("secondary", "s", 0.01, 0.02),
   ])
   response = ModelRouter().route("please classify this", "Classify", policy)
   print(response.model_used, response.was_fallback)
   ```

**Expected:** `s` and `was_fallback=True`.

**Stretch:** Run a full workflow with this policy and grep telemetry JSONL for `model_fallback` events.

---

## Exercise 4: Context budget enforcement

**Goal:** Confirm selection never exceeds the token ceiling.

1. Read `tests/test_context_budget.py` and run:

   ```bash
   pytest tests/test_context_budget.py -v
   ```

2. In a REPL, build a corpus of 200 items (copy the test pattern) and call `ContextSelector().select(..., token_budget=4096)`.

**Expected:** Sum of `token_count` for selected items is ≤ 4096.

---

## Exercise 5: Idempotent send on replay

**Goal:** Understand the crash window between side effect and checkpoint.

1. Run `./start.sh test` and confirm `test_idempotent_send_skips_duplicate_side_effect` passes.
2. Read `send_reply` in `src/workflows.py` and trace `side_effect_log` lookup vs insert.
3. Manually call `send_reply` twice on a completed workflow state (see test in `tests/test_resume.py`).

**Expected:** Second call returns `idempotent_skip=True`; side-effect count unchanged.

---

## Exercise 6: Informational email skips send

**Goal:** Non-actionable mail completes without approval or side effects.

1. Run:

   ```bash
   pytest tests/test_resume.py::test_informational_message_does_not_send_side_effect -v
   ```

2. Trace how `email-050` (lunch menu) flows through `triage_llm` → `draft_reply` → `approval_gate` → `send_reply`.

**Expected:** Workflow completes with `send_reply` output `skipped: true` and no `side_effect_log` entry.

---

## Exercise 7: Add a seventh step (extension)

**Goal:** Extend the engine without breaking checkpoint semantics.

Add a step after `send_reply`, e.g. `archive_thread`, that writes a mock archive record to `step_data` only (no external API).

1. Add a method on `InboxTriageWorkflow` and register it in `register()`.
2. Run a full workflow and confirm seven step results in SQLite.
3. Add a test that asserts the new step output appears in `step_data`.

**Constraints:** Checkpoint after the step; keep the step pure-ish (read `step_data`, return `StepResult`).

---

## Exercise 8: Read the audit trail

**Goal:** Practice observability over non-deterministic paths.

1. Run `./start.sh crash`.
2. Parse telemetry:

   ```bash
   python -m json.tool < examples/crash_resume_demo.telemetry.jsonl | head -80
   ```

   Or one JSON object per line:

   ```bash
   jq -c '.event_type' examples/crash_resume_demo.telemetry.jsonl
   ```

**Expected:** Events include `step_start`, `step_complete`, `crash_detected`, `workflow_resumed`, `approval_requested`, `workflow_complete`.

---

## Next steps

- Architecture diagrams and invariants: [dflow-arch.md](dflow-arch.md)
- Full specification: [dflow-spec.md](dflow-spec.md)
- Contributing: [../CONTRIBUTING.md](../CONTRIBUTING.md)

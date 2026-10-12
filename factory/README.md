# DurableFlow `factory/` — a durable spec-driven agent workflow

`factory/` is a **worked example** of a durable, spec-driven agent workflow
built on DurableFlow's core primitives. It is *not* a productized software
factory and CLEAR is *not* claimed to be an industry standard — CLEAR is the
teaching mnemonic used inside this folder.

The example exercises, daily, the durability primitives DurableFlow exists to
teach: checkpointed steps, approval gates, side-effect idempotency, context
lineage, and **independent claim verification before completion**. (The
worked example uses deterministic mock model providers so it runs hermetically
offline; the same wiring hosts a real cost-aware `ModelRouter` provider when
one is supplied.)

## What it does

A `ClearWorkflow` run moves through eight linear macro steps on the unchanged
`WorkflowEngine`:

```
c_requirements → l_design_mockup → l_architecture → l_tdd_plan
→ l_test_plan → plan_approval → phase_runner → ship
```

Inside `phase_runner`, the implement → assess → remediate loop lives as a
**store-backed micro state machine**. Each lap is checkpointed in a dedicated
`clear_phase_state` table, so a crash mid-phase resumes on the correct phase
and attempt without duplicating writes.

| CLEAR term | What happens | Artifact |
|------------|--------------|----------|
| Context | Requirements gathered | `prd.md` |
| Layout | Design + plan authored | `design.html`, `stack.md`, `plan.md`, `test.md` |
| Execute | Implementation lap | code under `src/` |
| Assess | Verification / eval lap | `phase_N_report.md` |
| Remediate | Root-cause + fix iteration | `phase_N_five_whys.md`, revised artifacts |
| Run | Release checkpoint | terminal `ship` step + `audit-summary.md` |

## Why loops live in `phase_runner`, not `WorkflowEngine`

`WorkflowEngine` is intentionally a **linear macro-step runner**. Branchy agent
behavior (implement/assess/remediate laps, retries) belongs in extension-owned
state, not in the engine. This keeps the core engine simple and auditable while
proving it can host realistic long-running agent workflows (spec §0, C-CLEAR-002).
There are **no engine-level loops, back-edges, or `goto` primitives** — verified
by a scoped diff: this extension touches only `factory/`, `tests/`, and one line
of `pyproject.toml`.

## Automated remediation vs. operator approval

These are deliberately separate flows:

- **Operator approval** (`plan_approval`) pauses the workflow and waits for a
  human decision. Rejecting a plan records `next_action = replan` and starts a
  fresh planning run — it never jumps the engine index backward.
- **Automated remediation** runs *inside* `phase_runner` with no human in the
  loop: a failed assessment triggers Five Whys root-cause analysis, updates the
  relevant artifact, and re-assesses the same phase, up to an attempt limit.

## Completion requires independent verification

No phase or workflow is marked complete on implementer assertion alone. The
`ship` step evaluates a verification ledger (`verification/ledger.json`) and
**refuses to complete** unless every non-deferred claim has a current `VERIFIED`
row written by an *independent* verifier (verifier ≠ implementer) over
non-stale, sufficiently-ranked evidence. Deferred items (graphical UI, per-turn
lineage, supersession model, long-horizon limits, production deploy) are seeded
as `DEFERRED-VERIFICATION` and never claimed complete.

## Running the tests

```bash
python -m pytest tests/test_clear_*.py
```

The suite covers the spec's test plan: phase-state serialization, the plan
parser, workspace isolation, idempotent writes, planning artifacts before
approval, the approval pause, crash-resume, forced-failure remediation, the
ship gate, context lineage, and the semantic fitness functions (zero
blocklisted engine terms in operator-facing output).

## Vocabulary

Public-facing language describes this as a **durable, spec-driven agent
workflow** that checkpoints each stage, gates plans and release decisions,
records context lineage, and verifies claims before completion. CLEAR-specific
terms (`c_`/`l_` step prefixes, `phase_runner`, the Five Whys remediation) stay
internal to this folder and `CLEAR.md`.

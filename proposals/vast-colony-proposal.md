# Proposal: Prove Colony Completes Long-Running Work on Vast.ai Under Instance Loss

**Status:** PROPOSAL  
**Created:** 2026-08-04  
**Audience:** Vast.ai engineering / product (external review) and DurableFlow maintainers  
**Package:** `colony/` (existing; live provider path incomplete)  
**Depends on:** `colony/colony-spec.md`, `docs/colony-methodology.md`, DurableFlow `src/store.py`  
**Decision requested:** Approve a gated, budget-capped live verification program that replaces the current `VastProvider` stub with a measured Vast-backed result — without claiming that Vast instances are unreliable.

---

## 1. Decision

Approve a three-gate live verification program with a partner-ready phase between G1 and G2:

| Gate | Name | Pass criterion |
|------|------|----------------|
| **G0** | Mock baseline (already shipped) | Deterministic naive-vs-Colony delta under identical seeded loss; CI-safe; no Vast account |
| **G1** | Live smoke (MVP for Vast contact) | One real Vast instance, one 5-stage job, one labeled loss, resume from last checkpoint, cost from real pricing, `human_interventions == 0` |
| **P1.5** | Partner-ready proof (meeting threshold) | A reviewed G1 artifact plus a small paired live control run and one-page proof contrasting durable recovery with the default “rent, lose, restart” workflow |
| **G2** | Live scoreboard (credibility) | Same batch plus a precommitted, stage-relative induced-loss schedule for naive and Colony; report completion / cost / wall / recoveries with `mode=live` |

**Stop after G1** if budget or API surface is thin. G1 alone is enough to show Vast that Colony is not a simulation dressed as a provider. Complete **P1.5 before a partnership meeting**: it adds a small live control comparison and turns the smoke into a concise, commercially legible artifact without claiming a production benchmark. **G2** is what makes the before/after claim credible across a batch and multiple seeds on Vast inventory.

This proposal does **not** ask Vast to change product behavior. It asks for a clean live provider surface and a measured result we can publish with honest labels.

---

## 2. The Claim (Falsifiable, Narrow)

> A durable execution layer turns spot-like decentralized compute into inventory that completes long-running work without human intervention. Here is the measured before/after under an identical loss schedule.

**Reader-safety sentence (required in every public artifact):**

> This is not a claim that Vast instances are unreliable; it is a benchmark of whether long-running work can survive the class of failures that any spot-priced heterogeneous compute marketplace must handle.

### 2.1 What chaos means here

| Dimension | In scope | Out of scope |
|-----------|----------|--------------|
| Failure class | Instance loss / termination / disappearance from the pool | CUDA OOM, driver flakes, GPU ECC, LLM nondeterminism, bad tokens |
| Workload | Multi-stage AI-eval-shaped jobs that *use* GPU inventory when live | Training-at-scale, multi-node NCCL, serving SLOs |
| Recovery | Checkpoint after completed stage → migrate → resume next stage | Speculative execution, predictive preemption, spectral failure prediction |
| Control | Controller-induced termination as a **labeled proxy**, or independently observed provider loss when it happens | Claiming on-demand “real spot eviction” when we destroyed the instance ourselves |

Colony measures **compute-inventory survival**, not **GPU/LLM correctness**. The live path runs on Vast GPU machines because that is the inventory under test; the chaos is still host/instance loss.

### 2.2 Why Vast should care (business framing)

Public evidence suggests Vast’s structural cost advantage is heterogeneous, spot-priced marketplace supply. The same property that makes that inventory cheap also means users must handle interruptions if they want multi-hour agent loops, eval sweeps, and staged inference jobs to finish without a human babysitter.

If durability lives in software on top of variable supply:

- Longer-running, higher-value workloads become sellable on the same inventory.
- Reliability moves into a control layer users can inspect, not into a promise of perfect hosts.
- The marketplace can compete on price *and* show that work completes under disruption — measured, not asserted.

Colony is a measurement instrument for that thesis, not a request that Vast become a vertically integrated cluster.

---

## 3. Current State (Honest)

### 3.1 What already exists

| Artifact | Status | Evidence |
|----------|--------|----------|
| Naive vs Colony controllers | Implemented | `colony/baseline.py`, `colony/controller.py` |
| Identical seeded chaos schedule | Implemented | `colony/chaos.py`, `tests/test_chaos_identity.py` |
| Mock provider (no network) | Implemented | `colony/provider.py` `MockProvider` |
| Mock benchmark demo | Implemented | `python3 examples/chaos_benchmark_demo.py` |
| Methodology + threats | Drafted | `docs/colony-methodology.md` |
| Checkpoint persistence via DurableFlow store | Partial | `colony/store_ext.py` wraps `WorkflowStore`; stages checkpointed; resume from `current_stage` |
| Gated `--live` CLI flag | Wired | Requires `VAST_API_KEY` |

**Current mock headline (hostile, seed 1337):**

```text
=== RESULT mode=mock profile=hostile seed=1337 ===
                  completion   cost     wall    recoveries  interventions
naive                90%     $ 0.23     701s        --            --
dflow-vast          100%     $ 0.23     689s        10             0

completion delta: +10 pts     cost delta: +0.00   under identical loss schedule (seed 1337)
```

That result is real for the mock protocol. It is **not** a Vast result.

### 3.2 What is not yet real

`VastProvider` today subclasses `MockProvider`, checks `VAST_API_KEY`, and returns a hardcoded price. It does **not** provision, run stages, terminate, or bill against Vast.

Therefore:

- `VAST_API_KEY=... python3 examples/chaos_benchmark_demo.py --live` does not prove Vast survival.
- No `mode=live` row exists in methodology.
- Spec test **T-INT-005** (gated live smoke) is specified but not implemented as a real provider path.
- Optional `[project.optional-dependencies] vast = []` is empty by design until a client is chosen and pinned.

**We will not present mock numbers as Vast numbers.** That is the integrity line for this proposal.

---

## 4. Proof Architecture

```text
                    identical ChaosSchedule (seed S)
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
        NaiveRunner                     ColonyController
   restart job from stage 0         resume from last checkpoint
              │                               │
              └───────────────┬───────────────┘
                              ▼
                    ComputeProvider
                     mock | vast
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
         MockProvider                    VastProvider (to build)
      simulated eviction              acquire / run_stage / health
                                      lose = destroy or observe
                                      price from Vast quoting/billing
                              │
                              ▼
                         RunReport × 2
              completion, cost, wall, recoveries, interventions
                              │
                              ▼
                    BenchmarkResult + methodology table
                         mode=mock | mode=live
```

Constants held across runners: batch, stage shape, pool size, budget, provider type, offer-selection policy, and the precommitted chaos event list.  
Variable under test: durability behavior only.

For live runs, an event targets a logical worker slot and fires at a stated durable boundary (for example, `slot=1, after_stage=2`), not at an absolute wall-clock timestamp. This keeps the intervention comparable when acquire latency differs between runners. The event list, its SHA-256 hash, and the mapping from logical slots to real instance IDs are persisted in both result artifacts.

---

## 5. Workload Contract

The headline workload stays the existing 20-job AI-eval-shaped batch (`make_eval_batch` / `data/batch_20jobs.json`). Each job has five durable stages:

1. `setup`
2. `data_load`
3. `inference_eval_shard`
4. `metrics_write`
5. `artifact_upload`

**Completion** means stage 5 committed a checkpoint. Partial progress that dies before stage 5 does not count.

| Mode | Stage body | Timing | Cost |
|------|------------|--------|------|
| Mock | Deterministic timed work | Seeded durations | Seeded $/GPU-hour × instance-seconds |
| Live | Same stage *shape* on a small Vast GPU instance | Wall clock measured | Vast-reported offer/billing price × instance-seconds; reconcile if API exposes invoice fields |

Live stages need not train a frontier model. They must be **real remote work** on a Vast machine (e.g. environment probe, small tensor op or tiny inference shard, write metrics artifact, upload digest). The point is inventory + durability, not model quality.

---

## 6. Gate Definitions

### 6.1 G0 — Mock baseline (done; keep green)

```bash
python3 examples/chaos_benchmark_demo.py --profile hostile
pytest tests/test_colony_recovery.py tests/test_chaos_identity.py tests/test_benchmark.py tests/test_cost.py -q
```

Acceptance:

- Colony `completion_rate` > naive under hostile profile for the fixed seed used in README.
- Identical schedule applied to both runners (asserted in tests).
- Colony `human_interventions == 0`.
- Numbers in README match `benchmark_result.json` from the demo, not hardcoded fiction.

### 6.2 G1 — Live smoke (MVP to show Vast)

**One instance. One job. One loss. One recovery. One cost line.**

Procedure:

1. Acquire one small/cheap Vast instance via API; record `provider_handle`, GPU type, quoted `$/hr`.
2. Run stages 0–1 (or through mid-job); persist durable checkpoint after each completed stage.
3. Apply **one** loss:
   - Preferred for determinism: **controller-induced termination** (destroy the instance via API), labeled exactly that way in telemetry and the report.
   - Acceptable alternative: wait for / observe an independent provider loss; label `observed_provider_loss`.
4. Detect loss via `health()` (or equivalent status poll).
5. Acquire a replacement instance under the same budget ceiling.
6. Resume at `current_stage + 1` (not stage 0). Assert checkpoint contents match the last committed stage.
7. Finish remaining stages; release instance; record spend.
8. Emit a machine-readable smoke record, e.g. `live_smoke_result.json`:

```json
{
  "schema_version": "1.0",
  "run_id": "...",
  "mode": "live",
  "gate": "G1",
  "provider": "vast",
  "job_id": "...",
  "stages_completed": 5,
  "loss_label": "controller_induced_termination",
  "resume_from_stage": 2,
  "instances_acquired": 2,
  "instances_lost": 1,
  "recoveries": 1,
  "human_interventions": 0,
  "total_cost_usd": 0.0,
  "wall_clock_seconds": 0.0,
  "vast_offer_ids": [],
  "schedule_sha256": "...",
  "software_commit": "...",
  "started_at_utc": "...",
  "finished_at_utc": "...",
  "price_currency": "USD",
  "quoted_price_usd_per_hour": 0.0,
  "billed_seconds": 0.0,
  "provider_receipt_refs": [],
  "notes": "cost must be > 0 and derived from quoted Vast pricing × billable seconds; reconcile to a provider receipt when available"
}
```

Acceptance (all required):

- [ ] Real Vast instance IDs present (not `i-001` mock IDs).
- [ ] Resume stage index > 0 after loss.
- [ ] `total_cost_usd > 0` from Vast pricing path (not the stub `0.75` constant alone).
- [ ] `human_interventions == 0`.
- [ ] Loss labeled `controller_induced_termination` or `observed_provider_loss` — never “real eviction” unless independently observed.
- [ ] Gated: not in default CI; requires `VAST_API_KEY` + explicit env flag (e.g. `DURABLEFLOW_VAST_LIVE=1`).
- [ ] Budget hard-cap (suggested default: ≤ $2 for G1).
- [ ] Result validates against a versioned schema and includes the run ID, UTC boundaries, software commit, schedule hash, price unit, billed seconds, and redacted provider receipt/reference IDs.

This maps to spec **T-INT-005**.

### 6.2.1 P1.5 — Partner-ready proof (required before external pitch)

G1 establishes that the path is live. P1.5 adds the minimum evidence needed to compare it with the actual user alternative: rent a machine, lose it, and restart from stage 0. It is not a customer case study or a replacement for G2, and must not imply either.

The paired control is one representative job (or a declared five-job micro-batch) run once with `NaiveRunner` and once with Colony. Both rows use the same stage body, offer-selection policy, logical slot, and one precommitted stage-relative controller-induced termination. Before the first run, declare the comparison deadline and budget cap. A run that reaches either limit is reported as incomplete; the cap is not changed after seeing either outcome.

Deliverables:

- A one-page, linkable live proof containing the G1 JSON artifact, redacted real instance IDs, offer price, billed-time calculation, loss label, checkpoint/resume evidence, and cleanup confirmation.
- A paired live-control table with one `mode=live` row each for naive and Colony. It must show the loss boundary, last committed stage before loss, completion state at the predeclared deadline, total billed cost, and wall clock. The table is a **single-run demonstration**, not a rate or statistical claim.
- A concise workload statement: **“multi-hour agent/evaluation batches that would otherwise need a reserved/on-demand machine or manual restart can complete across interruptible marketplace inventory.”** This is a target workload statement, not a claim of current customer adoption.
- A visual or tabular contrast of the default path (`rent → run → instance loss → restart from stage 0`) and the Colony path (`rent → checkpoint → instance loss → reacquire → resume after last committed stage`). The displayed events must be the paired-control losses, labeled `controller_induced_termination` or `observed_provider_loss`.
- If budget permits, a small customer-shaped batch (five jobs is sufficient) whose stages total at least two hours of intended work. The run may be shortened only by a declared time-scaling factor; report both intended and observed wall-clock duration. This is supplementary evidence, not a substitute for G2.

Acceptance:

- [ ] G1 has passed and its versioned artifact is attached; no mock number appears in the live proof without an explicit `mode=mock` label.
- [ ] Both paired-control rows have versioned live artifacts with the same declared stage-relative event, offer-selection policy, deadline, and budget cap.
- [ ] The proof contrasts Colony with the default restart-from-scratch workflow, not with an abstract orchestration system.
- [ ] “Default failed” is used only if the naive run is incomplete at its predeclared deadline or budget cap. Otherwise, state the measured weaker result: it restarted from stage 0 and consumed the reported additional work/cost.
- [ ] All commercial language is conditional or evidence-backed; no claim of customers, savings, natural eviction rate, or production reliability is made without direct evidence.
- [ ] The meeting packet leads with the live artifact and workload consequence, then links to this full protocol for methodology.

### 6.3 G2 — Live scoreboard (credibility for the headline claim)

Run naive and Colony against the **same precommitted, stage-relative** induced-loss schedule on real instances. An event fires only after its named stage checkpoint has committed on its logical worker slot; it then destroys that runner's currently mapped instance. This produces equivalent recovery pressure without pretending that separately acquired machines have identical wall-clock behavior.

Constraints:

- Small pool (e.g. 2–3 instances), reduced batch if needed (e.g. 5–10 jobs) to stay inside a stated budget envelope.
- Same seed → the same logical slots, stage boundaries, and loss labels; applied to both runners.
- Freeze the offer-selection query before the first run (GPU constraints, maximum quoted $/hr, region filters, and sort rule) and record the returned offer IDs and selected offer for each acquisition. Do not retrospectively choose cheaper or faster offers.
- Report both rows with `mode=live`.
- Publish mean ± range across ≥3 seeds (preferred). A single-seed table is permitted only as a G2 pilot, labeled `single_seed_pilot`, with per-run artifacts linked and no generalized performance claim.

Acceptance:

- [ ] Colony completion_rate ≥ naive under the live schedule (strict `>` preferred; if marginal, show the number — do not spin).
- [ ] Cost computed from instance-seconds × Vast price for both rows.
- [ ] Completion denominator, cost allocation, and wall-clock boundaries are identical: a job completes only after stage 5 is checkpointed; all provider-billed time from acquire through confirmed release, including failed attempts and recovery instances, counts toward cost; wall clock starts at first acquire request and ends after final release confirmation.
- [ ] Each row records a schema version, run ID, commit SHA, event list/hash, slot→instance mapping, offer-selection query, quoted price/unit, billed seconds, and any available redacted provider receipt reference.
- [ ] Methodology updated with a `mode=live` table and threats-to-validity including mock↔live gap.
- [ ] Total spend within pre-declared budget; abort cleanly on budget halt.

---

## 7. Technical Plan

### 7.1 Replace the stub `VastProvider`

Implement `ComputeProvider` for real:

| Method | Live behavior |
|--------|---------------|
| `acquire(spec)` | Create/rent instance from search/offer; wait until SSH/API-ready; return `Instance` with Vast id + $/hr |
| `health(instance)` | Poll instance status; map disappeared/exited/unreachable → `lost` |
| `run_stage(instance, job, stage)` | Execute stage payload on the instance (SSH, docker exec, or Vast-supported run API); return measured `duration_s` + digest-only output |
| `lose(instance, reason=...)` | Destroy/stop for controller-induced path; set `loss_reason` on handle |
| `release(instance)` | Destroy/stop and stop charging |
| `price(gpu_type)` | From offer/quote at acquire time; optionally reconcile with billing endpoint |

**Implementation decision required before Step 1:** use one pinned, documented control-plane client/API path and one execution transport for G1 (SSH with a pinned remote bootstrap script, unless Vast provides a supported non-interactive run API). The implementation must document endpoint/API version, auth source, request idempotency key, readiness probe, polling interval/backoff, and per-operation timeout. `acquire` must reconcile an ambiguous create timeout by listing instances with the run tag before issuing another rent request; `release` must be idempotent and verify the instance reaches a non-billing terminal state.

Every remotely executed stage receives a run ID, job ID, stage index, and idempotency key. Its output is a digest and exit status only. A retry may reuse the same idempotency key, but a new acquisition/recovery gets a distinct recovery-attempt ID recorded in `side_effect_log`.

Constraints from DurableFlow:

- No Vast SDK import at module top level in core paths; lazy import inside `VastProvider`.
- Pin any client dependency with `==` under optional `[vast]`.
- Default demos and CI remain offline (`MockProvider`).

### 7.2 Controller / store hardening for live clocks

Mock time is synthetic (`schedule.between(now, end, slot)`). Live time is wall clock. Required adjustments:

- Drive G1 chaos from an explicit “after stage N checkpoint” hook; use the same stage-relative event representation for G2. Wall-clock timing is telemetry, not the live comparison trigger.
- Ensure checkpoints survive **controller process** restart as well as **worker instance** loss (DurableFlow `WorkflowStore` already exists; wire resume through it explicitly if any stage loop still relies only on in-memory `Job.current_stage`).
- Keep idempotent dispatch via `side_effect_log` so double-detected loss cannot double-rent without a recorded recovery path.

### 7.3 Telemetry and labeling

Emit JSON-lines events at least for: `instance_acquired`, `instance_lost`, `job_checkpointed`, `job_recovering`, `job_resumed`, `job_completed`, `budget_halt`, `run_complete`.

All events include `schema_version`, `run_id`, `timestamp_utc`, `software_commit`, logical worker slot, and recovery-attempt ID where applicable. Acquisition and release events additionally include a redacted provider request/reference ID, quoted price and unit, and the budget snapshot before and after the operation.

Every loss event must carry:

```text
loss_label ∈ { simulated_eviction, controller_induced_termination, observed_provider_loss }
```

Public writeups use those exact phrases.

### 7.4 Privacy

Persist digests, instance ids, stage indices, and cost — not raw prompts, email bodies, or model transcripts. Align with DurableFlow’s existing privacy boundary (`evals/redaction.py` ethos).

### 7.5 Tests

| ID | Mode | Assertion |
|----|------|-----------|
| Existing T-REC / T-CHA / T-BEN / T-CST | Offline | Remain green |
| T-INT-005 | Gated live | G1 acceptance checklist |
| T-LIVE-001 (new) | Unit with recorded HTTP/CLI fixtures | `VastProvider` maps acquire/health/lose without network |
| T-LIVE-002 (new) | Gated live optional | G2 reduced batch; Colony ≥ naive; interventions == 0 |
| T-LIVE-003 (new) | Unit with recorded fixtures | Ambiguous acquire is reconciled by run tag; release is idempotent; no duplicate rent is issued |
| T-LIVE-004 (new) | Unit | Cost includes acquire-to-confirmed-release billed time, failed attempts, and billing-minimum rounding |

Fixture-based provider tests keep CI honest without spending GPU dollars on every commit.

---

## 8. Methodology Rigor (What Vast Can Audit)

### 8.1 Identity of the chaos schedule

The validity of the comparison rests on one property: **both runners see the same logical loss events** (same stage boundaries, target slots, and loss labels). Tests already enforce schedule identity offline; live must log the complete event list, schedule hash, and slot→instance mapping into the result JSON for both rows.

### 8.2 Threats to validity (publish unchanged in spirit)

1. **Mock ≠ live.** Timing, acquire latency, and failure modes differ.
2. **Loss-rate assumption.** Mock Poisson rate is a stated assumption, not a measurement of Vast churn.
3. **Controller-induced termination is a proxy.** It tests recovery mechanics under sudden instance death; it is not a sample of natural preemption frequency.
4. **Single workload family.** Results do not generalize to all GPU jobs.
5. **No network-partition / straggler model** beyond lose/recover.
6. **Small-N live runs.** Live tables will be budget-limited; variance must be stated.

### 8.3 Anti-patterns we commit not to use

| Anti-pattern | Rejection rule |
|--------------|----------------|
| Mock dressed as live | Every table labeled `mode=` |
| “Real eviction” when we destroyed the box | Label `controller_induced_termination` |
| Cherry-picked seed only | Prefer multi-seed; else disclose single-seed |
| Hardcoded README numbers | Numbers come from a run artifact |
| Claiming GPU/LLM chaos survival | Scope is instance-loss survival only |
| Claiming Vast is unreliable | Reader-safety sentence required |

---

## 9. Asks of Vast.ai (Optional, Accelerating)

None of these are blockers for G1 if the public API already supports create / status / destroy / price.

| Ask | Why |
|-----|-----|
| Confirm recommended API path for create → ready → destroy for a small GPU offer | Avoid brittle CLI scraping |
| Documented fields for $/hr at rent time and any post-hoc usage record | Cost row must be reconcilable |
| Guidance on minimum stable poll interval for instance health | Tune `health()` without hammering |
| Optional: a sandbox/project credit envelope for the published G1/G2 runs | Makes the public artifact reproducible by a third party |
| Optional: review of public wording before we cite Vast by name in a blog/README live table | Keeps partnership tone accurate |

We do **not** ask for privileged access to internal reliability metrics. The benchmark must stand on the public control plane.

---

## 10. Budget and Operational Envelope

| Gate | Suggested spend ceiling | Notes |
|------|-------------------------|-------|
| G1 | ≤ $2 | One instance, short stages, one destroy/reacquire |
| P1.5 | ≤ $6 total, including G1 | G1 plus one small paired live control; declare the exact cap before renting |
| G2 | ≤ $15–25 (pre-declare) | Reduced batch; abort on `budget_halted` |
| CI | $0 | Mock + fixtures only |

Operational defaults:

- Opt-in only (`--live` + `VAST_API_KEY` + `DURABLEFLOW_VAST_LIVE=1`).
- Hard budget reservation occurs **before** each rent/recovery: reserve the greater of the provider billing minimum (if known) and the configured remaining-stage estimate, plus a configurable cleanup buffer. Refuse the operation if reservation would exceed the cap; emit `budget_halt` with the calculation.
- Treat quote changes, billing-minimum uncertainty, and unavailable billing APIs as budget risk. G1 cannot pass without a quoted price/unit and billable-seconds calculation; if final billing cannot be reconciled, label the result `estimated_cost_unreconciled` rather than claiming exact spend.
- Tear down all tagged instances in `finally` even on failure. On controller restart, run a tagged-instance reconciliation sweep before acquiring anything; retain a cleanup ledger with destroy request/result and terminal-status confirmation. If cleanup cannot be confirmed, mark the run failed and surface the possible orphan explicitly.

---

## 11. Success / Failure Criteria

### Success (publishable)

- G1 smoke record reviewed and attached to methodology.
- Public claim limited to measured tables + reader-safety sentence.
- Vast can reproduce G1 with a key and the script, or can audit the JSON + instance ids.

### Failure modes (do not spin)

| Outcome | Correct response |
|---------|------------------|
| Live resume restarts from stage 0 | **Do not claim Colony survival**; fix controller/store |
| Colony ≤ naive on live with clear durable bug | Fix; re-run; do not bury |
| Colony ≈ naive because losses were too mild | Report honestly; tighten schedule or accept marginal fixture discipline |
| Cost path cannot read Vast prices | Block G1 pass until pricing is real |
| Live too flaky to finish under budget | Publish G1 only; keep G2 deferred with ledger entry |

### Explicit non-goals

- Not a Temporal/Ray replacement.
- Not a Vast reliability scorecard.
- Not predictive preemption or spectral coordination claims.
- Not proof that agents “think better” on Vast — only that staged work can finish when machines disappear.

---

## 12. Delivery Sequence

| Step | Deliverable | Owner surface |
|------|-------------|-----------------|
| 1 | Real `VastProvider` + fixture tests (T-LIVE-001) | `colony/provider.py`, optional `[vast]` pin |
| 2 | Gated G1 script/test (T-INT-005) | `examples/` or `tests/` gated |
| 3 | P1.5 paired live control, one-page proof, and customer-shaped workload framing | external meeting packet / docs |
| 4 | Update `docs/colony-methodology.md` with `mode=live` G1 record + threats | docs |
| 5 | (Optional) G2 reduced live scoreboard + README live table | benchmark path |
| 6 | Ledger: append VERIFIED or DEFERRED-VERIFICATION rows for live claims | `verification/` if used for Colony |

Until step 2 lands, README and external conversation must treat live mode as **unimplemented behind a stub**, even though the CLI flag exists.

---

## 13. One-Page Summary for Vast Reviewers

**What we built:** An open, offline-first chaos benchmark that compares retry-from-scratch vs checkpoint-and-resume under an identical loss schedule.

**What we measured so far:** A clear mock delta (Colony completes more work under the same simulated losses).

**What we have not measured:** The same mechanics on real Vast instances — because the Vast adapter is still a stub.

**What we propose next:** A budget-capped live smoke (G1), a partner-ready proof packet (P1.5), and an optional live scoreboard (G2). Together they provision real GPUs, induce or observe one instance loss, resume durable work, contrast that outcome with restart-from-scratch, and publish cost and completion with honest labels.

**What we will never claim without evidence:** That Vast is unreliable; that we survived “real spot eviction” when we destroyed the instance; that we survived GPU/LLM chaos; that mock numbers are live numbers.

**The ask:** Review this protocol; if the public API path is correct, G1 is a short funded run away from a publishable, falsifiable result that makes durable long-running work on heterogeneous marketplace inventory a measured property — not a slogan.

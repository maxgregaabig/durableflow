# Specification: Colony (dflow-vast)

**Status:** READY
**Author:** Marcos Polanco
**Created:** 2026-06-17
**Target completion:** 2026-07-01 (10-day build, extends existing `durableflow`)
**Repository:** `durableflow` (top-level sibling package `colony/` + extension of existing engine)
**Visibility:** This spec is a private implementation guide. The public artifact is the repo: README, code, tests, the chaos benchmark, and the result table.
**Depends on:** `durableflow` v0.1 (existing). This spec extends, does not replace, the durable execution engine.

---

## 0. Positioning Note (read first)

Colony is a **falsifiable** implementation of the "autonomous compute colony" concept. It deliberately focuses on a concrete benchmark rather than theoretical or predictive failure detection concepts.

The single load-bearing claim of this artifact is:

> **A durable execution layer turns spot-like decentralized compute into inventory that completes long-running work without human intervention. Here is the measured before/after.**

The headline deliverable is not software. It is a **benchmark result**: a naive baseline versus Colony under an identical, calibrated chaos protocol, reported as completion rate, cost, and wall-clock with confidence intervals. The software exists to produce that number honestly.

Everything in this spec is scoped to protect that claim from the one question that breaks weak demos: *"show me the data."*

### 0.1 MVP Cutline

The 10-day artifact is judged by the smallest credible measured result, not by feature completeness.

**MVP = mock benchmark + result table + methodology + one live Vast smoke test.**

MVP must include:
- durable runner versus naive baseline
- identical seeded chaos schedule
- computed cost, completion rate, and wall-clock
- deterministic mock benchmark with the result table
- methodology writeup with threats to validity
- a gated live Vast smoke test: one instance, one concrete job, one controller-induced termination or observed provider loss, one measured recovery/cost record

**Full version = MVP + live scoreboard + extra fixtures + optional HTML + broader test matrix.**

If time compresses, presentation polish is cut before the live smoke path. A mock-only artifact is still useful engineering, but it is materially weaker for this audience.

---

## 1. Requirement & Narrative

### What

A control layer, built on the existing `durableflow` engine, that runs a batch of long-running jobs across Vast.ai GPU instances, survives spot-like instance loss by checkpointing and migrating work to healthy instances, accounts for GPU-hour cost via the Vast API when run live, and emits a benchmark comparing job completion under chaos against a naive (retry-only, no-durability) baseline.

The user gives a batch of jobs and a budget. Colony provisions instances, dispatches jobs, and keeps work alive as instances disappear. It reports what it spent, how many instances it lost, how many recoveries it executed, and how many jobs finished, versus what the naive baseline achieved under the identical failure schedule.

This is not an agent framework. It is the operational substrate that makes agent-scale, long-horizon work survivable on decentralized compute.

### Why

**Commercial driver (the Vast business case):** public evidence suggests Vast.ai's structural cost advantage is heterogeneous, spot-priced marketplace supply. That same property means users must handle the class of spot-like losses, terminations, and host variability that can interrupt long-running jobs. The durability layer is what would let cheap heterogeneous inventory support longer-running, higher-value workloads (agent swarms, multi-stage training sweeps, multi-hour evals) without requiring vertically integrated control of the underlying hardware. Reliability moves into software, on top of variable supply.

**Reader-safety sentence for the README:** This is not a claim that Vast instances are unreliable; it is a benchmark of whether long-running work can survive the class of failures that any spot-priced heterogeneous compute marketplace must handle.

**Concrete workload for the headline benchmark:** 20 small AI-eval-style jobs over a toy retrieval/model benchmark. Each job has 5 durable stages: environment setup, shard/data load, inference/eval shard, metrics write, and artifact upload. A job is complete only after the artifact-upload stage commits. In mock mode these stages are deterministic timed work with seeded costs; in live mode the same stage shape runs on a small Vast instance and records real elapsed time and pricing.

**Why this artifact:** It demonstrates how to take a core infrastructure risk (instance loss under load) and make it measurable, survivable, and demonstrably better. The artifact reuses an existing, tested durable execution engine rather than starting over, showing the difference between a production-minded primitive and a custom toy.

### Who

**Primary persona -- the infrastructure evaluator:** a technical lead who rewards concrete data ("show me the data") and reproducible benchmarks. The benchmark table is for this reader.

**Implicit persona -- the compute marketplace architect:** an engineer who would consume Colony's spot-like loss survival behavior and cost accounting as a platform primitive. The architecture notes are for this reader.

**Operator persona -- whoever runs the demo:** launches the chaos benchmark from a CLI, watches the live scoreboard, reads the final result table.

---

## 2. Gherkin Scenarios

### 2.1 Behavioral Gherkin (Test Coverage)

```gherkin
Scenario: Golden path -- batch completes on stable compute
  Given a batch of 20 jobs and a budget of $10.00
  And each job is the 5-stage AI eval workload: setup, data load, inference/eval shard, metrics write, artifact upload
  And a pool of 5 healthy (simulated or real) Vast instances
  When the Colony controller runs the batch with the durable executor
  Then each job is dispatched to an instance and checkpointed per stage
  And all 20 jobs complete
  And the run report records jobs_completed=20, instances_lost=0, recoveries=0, human_interventions=0
  And total cost is computed from actual GPU-hours and does not exceed the budget

Scenario: Single instance loss mid-job triggers migration and resume
  Given a job dispatched to instance I and checkpointed at stage 2 of 5
  And instance I is lost before stage 3 checkpoints
  When the controller's health monitor detects I is gone
  Then the job is marked recoverable at its last durable checkpoint (stage 2)
  And the controller acquires or selects a healthy instance J
  And the job resumes at stage 3 on J, not from stage 0
  And the run report increments instances_lost and recoveries by 1
  And no human intervention is required

Scenario: Chaos benchmark -- Colony versus naive baseline (the headline)
  Given an identical batch of 20 jobs
  And an identical chaos schedule (loss events at fixed seeded times)
  When the naive baseline runs (retry-on-failure, restart job from scratch, no checkpoint)
  And the Colony runner runs (durable checkpoint, migrate, resume)
  Then the report contains a comparison table with both rows
  And Colony completion_rate is strictly greater than naive completion_rate
  And the chaos schedule applied to both runs is identical (same seed, same loss times)
  And each run records completion_rate, total_cost_usd, wall_clock_seconds, recoveries, human_interventions

Scenario: Budget ceiling halts dispatch
  Given a budget of $2.00 and a batch whose projected cost exceeds it
  When projected spend reaches the budget ceiling
  Then the controller stops acquiring new instances
  And in-flight checkpointed jobs are allowed to drain
  And the run report records a budget_halt event and the partial completion_rate
  And the budget ceiling is never exceeded by actual recorded spend

Scenario: Idempotent dispatch under double-detection
  Given a job that has been dispatched to instance I
  And the health monitor briefly mis-reports I as lost, then I recovers
  When the controller would re-dispatch the job
  Then the side-effect log prevents a duplicate active dispatch of the same job
  And the job is counted once in jobs_completed

Scenario: All instances lost simultaneously (catastrophic)
  Given a batch in flight across 5 instances
  And all 5 instances are lost within one health-check interval
  When the controller detects total pool loss
  Then all in-flight jobs are returned to recoverable state at last checkpoint
  And the controller re-acquires instances up to budget
  And jobs resume from last checkpoint
  And if budget is exhausted, the run ends with an explicit partial result, not a crash

Scenario: Mock mode runs with no Vast account and no network
  Given VAST_API_KEY is not set
  When the chaos benchmark runs in mock mode
  Then a simulated instance pool with a seeded simulated-eviction schedule is used
  And the full benchmark (both rows) completes deterministically
  And the result table is produced without any network calls

Scenario: Live mode runs against Vast instances
  Given VAST_API_KEY is set and live mode is selected
  When the chaos benchmark runs
  Then real instances are provisioned via the Vast API
  And controller-induced terminations or independently observed provider losses drive the chaos schedule
  And cost is read from actual Vast billing/instance pricing
  And the result table distinguishes mode=live from mode=mock
  And the report labels induced termination separately from observed provider loss
```

### 2.2 Conceptual Gherkin (Cognitive Outcomes -- drives the scoreboard view)

These map to the UI states the run scoreboard must render (see §3.1 presentation contract and Phase 4).

```gherkin
Scenario: Operator perceives "work is surviving"
  Given the chaos benchmark is running live
  When a simulated eviction or induced termination appears on screen
  Then the operator sees the affected job move to RECOVERING, not FAILED
  And sees a recovery counter increment
  And forms the belief: "the work continues without me"

Scenario: Operator perceives "the difference is real"
  Given both runs have completed
  When the operator views the final comparison
  Then the naive row and Colony row are visually adjacent
  And the completion-rate delta is the most prominent figure
  And the operator forms the belief: "this is a measured result, not a claim"

Scenario: Operator perceives "this costs real money and it is accounted"
  Given a run in progress
  When jobs consume GPU-hours
  Then a live spend figure updates against the budget ceiling
  And the operator forms the belief: "cost is tracked per run, not a monthly surprise"
```

---

## 3. Phased Implementation Plan

Phases follow spec-policy §3. Colony reuses `durableflow` Phase 1 (engine, store, checkpoint/resume, side-effect log) without modification where possible. New work is additive. Current repo-level package discovery includes sibling extension packages (`colony*`, and future `agent*`, `readiness*`, `mcp_server*`) alongside `src*`.

### Phase 1: Core Data Models & Infrastructure

**Scope:** Job/instance/run domain models, the compute-provider abstraction, and the SQLite schema extensions. Reuses the existing `WorkflowStore` checkpoint/resume machinery.

**Files:**
- `colony/models.py` -- domain dataclasses
- `colony/provider.py` -- `ComputeProvider` interface + `MockProvider` + `VastProvider`
- `colony/store_ext.py` -- schema extensions (`jobs`, `instances`, `runs`, `chaos_events`); reuses existing `side_effect_log`

**Deliverables:**
- `Job` dataclass: `job_id`, `batch_id`, `spec` (JSON: the work to run), `stage_count`, `current_stage`, `status` enum, `assigned_instance_id`, `checkpoint_ref`, `created_at`, `updated_at`
- `Instance` dataclass: `instance_id`, `provider`, `gpu_type`, `cost_per_hour_usd`, `status` enum, `acquired_at`, `lost_at`, `provider_handle` (JSON: provider-specific id)
- `RunReport` dataclass: `run_id`, `mode` (mock/live), `runner` (naive/colony), `batch_size`, `jobs_completed`, `instances_acquired`, `instances_lost`, `recoveries`, `human_interventions`, `total_cost_usd`, `wall_clock_seconds`, `budget_usd`, `budget_halted` (bool), `chaos_seed`, `started_at`, `ended_at`
- `ChaosEvent` dataclass: `event_id`, `run_id`, `scheduled_at_offset_s`, `event_type` (evict/throttle), `target_instance_id`, `applied` (bool)
- `Job.status` enum: `queued`, `dispatched`, `running`, `checkpointed`, `recovering`, `completed`, `failed`
- `Instance.status` enum: `requested`, `healthy`, `degraded`, `lost`, `released`
- `ComputeProvider` interface (abstract): `acquire(spec) -> Instance`, `release(instance)`, `health(instance) -> InstanceStatus`, `price(gpu_type) -> float`, `run_stage(instance, job, stage) -> StageResult`
- `MockProvider`: deterministic, seeded; simulates acquisition latency, per-stage execution, and simulated eviction per the chaos schedule; no network
- `VastProvider`: implements the interface against the Vast CLI/SDK; gated by `VAST_API_KEY`; never required for tests or mock benchmark

**SQLite schema extensions:** see Appendix C. Reuses `side_effect_log` from durableflow for idempotent dispatch.

**Target acceptance criteria:**
- [ ] `Job`, `Instance`, `RunReport`, `ChaosEvent` fully defined; no TBD fields
- [ ] `ComputeProvider` interface defined with all five methods
- [ ] `MockProvider` produces deterministic runs given a fixed seed
- [ ] `VastProvider` interface-complete; gated by env var; raises a clear error if selected without `VAST_API_KEY`
- [ ] Job state and checkpoint references persist via SQLite; survive process restart
- [ ] No in-memory-only run state

### Phase 2: Logic Engines & Processing

**Scope:** The Colony controller (dispatch + health monitor + recovery), the chaos engine, the naive baseline runner, and cost accounting. The durable per-job execution reuses the existing `WorkflowEngine` checkpoint/resume semantics, with each job stage treated as a durable step.

**Files:**
- `colony/controller.py` -- dispatch loop, health monitor, recovery/migration
- `colony/chaos.py` -- seeded chaos schedule generation and application
- `colony/baseline.py` -- naive runner (retry-only, no durability)
- `colony/cost.py` -- GPU-hour cost accounting from provider pricing

**Deliverables:**

#### controller.py -- Colony runner
- `ColonyController` class: `run_batch(batch, budget, provider, chaos) -> RunReport`
- Dispatch: assign queued jobs to healthy instances up to pool size and budget
- Per-job execution wraps the durableflow engine: each job stage is a durable step; `save_checkpoint` after each stage; `checkpoint_ref` recorded on the `Job` row
- Health monitor: poll `provider.health()` on a fixed interval; on `lost`, mark assigned job `recovering` at last checkpoint
- Recovery/migration: select or acquire a healthy instance; resume the job from `current_stage` (last completed), not from stage 0; increment `recoveries`
- Idempotent dispatch: before activating a job on an instance, check `side_effect_log` keyed `sha256(run_id + job_id + "dispatch")`; prevents duplicate active dispatch under mis-detection
- Budget enforcement: stop acquiring instances when projected + actual spend reaches `budget_usd`; drain in-flight checkpointed jobs; record `budget_halted`
- `human_interventions` is a recorded counter; for the benchmark it MUST remain 0 for the Colony runner (any nonzero value is a benchmark-invalidating bug, asserted in tests)

#### chaos.py -- chaos engine
- `ChaosSchedule.generate(seed, duration_s, loss_rate, pool_size) -> list[ChaosEvent]`
- Loss inter-arrival times drawn from a seeded Poisson process; `loss_rate` calibrated to a documented spot-like-loss assumption (stated explicitly in README with its source/assumption caveat)
- `apply(event, provider)` -- in mock mode, marks a `MockProvider` instance lost as a simulated eviction; in live mode, terminates a real instance as a controller-induced termination, clearly labeled separately from independently observed provider loss
- The SAME schedule object (same seed) is applied to both the naive and Colony runs -- this identity is the core of the benchmark's validity and is asserted in tests

#### baseline.py -- naive runner
- `NaiveRunner.run_batch(batch, budget, provider, chaos) -> RunReport`
- No checkpointing: on instance loss, the job restarts from stage 0 on retry
- Bounded retries per job (e.g. 3); after exhaustion, job is `failed`
- Same dispatch, same provider, same chaos schedule, same budget as Colony -- only the durability behavior differs
- Produces a `RunReport` with `runner="naive"`

#### cost.py -- cost accounting
- `CostAccountant.charge(instance, seconds) -> float` using `instance.cost_per_hour_usd`
- `total(run_id) -> float` sums all instance-time for the run
- In live mode, reconcile against Vast-reported pricing; in mock mode, use seeded per-GPU-type prices
- Cost is computed from recorded instance-seconds, never hardcoded

**Target acceptance criteria:**
- [ ] Colony resumes a job from its last checkpoint after instance loss (not from stage 0)
- [ ] Naive restarts a job from stage 0 after instance loss
- [ ] The identical chaos schedule (same seed, same events) is applied to both runners
- [ ] Idempotent dispatch prevents duplicate active job execution under mis-detection
- [ ] Budget ceiling is never exceeded by recorded spend; `budget_halted` set when hit
- [ ] Colony `human_interventions == 0` for all benchmark runs (asserted)
- [ ] Cost is computed from instance-seconds and per-hour price, never hardcoded
- [ ] Under a non-trivial chaos schedule, Colony `completion_rate` > naive `completion_rate`

### Phase 3: Telemetry, Benchmark Harness, & Fixtures

**Scope:** Structured telemetry (reuses durableflow's `TelemetryLogger.log_event()` extension hook), the benchmark harness that runs both rows and emits the comparison, and seeded fixtures.

**Files:**
- `colony/telemetry_ext.py` -- Colony event types on top of the existing telemetry logger
- `colony/benchmark.py` -- runs naive + Colony under one schedule, emits `BenchmarkResult`
- `examples/chaos_benchmark_demo.py` -- the headline demo (mock mode by default)
- `examples/single_eviction_demo.py` -- minimal one-job simulated-eviction+resume demo
- `data/batch_20jobs.json` -- seeded 20-job batch fixture
- `data/chaos_profiles.json` -- named chaos profiles (calm / moderate / hostile) with seeds and rates

**Deliverables:**

#### telemetry_ext.py
- Event types: `instance_acquired`, `instance_lost`, `job_dispatched`, `job_checkpointed`, `job_recovering`, `job_resumed`, `job_completed`, `budget_halt`, `run_complete`
- JSON-lines output, reusing the durableflow logger's generic `log_event()` method; `summarize_run(run_id) -> RunReport`

#### benchmark.py
- `Benchmark.run(batch, budget, chaos_profile, provider_factory) -> BenchmarkResult`
- Runs naive first, then Colony, under the same generated schedule (same seed)
- `BenchmarkResult` dataclass: `chaos_profile`, `seed`, `naive: RunReport`, `colony: RunReport`, `completion_rate_delta`, `cost_delta`, `wall_clock_delta`
- `BenchmarkResult.to_table() -> str` -- the result table (see §3.1, this is the artifact's headline output)
- `BenchmarkResult.to_json()` -- machine-readable for inclusion in README/CI artifact

#### chaos_benchmark_demo.py (headline)
Execution flow:
1. Load `batch_20jobs.json` and the `hostile` chaos profile
2. Construct `MockProvider` (or `VastProvider` if `--live` and `VAST_API_KEY` set)
3. Run the benchmark (naive then Colony, identical schedule)
4. Stream the live scoreboard to the terminal during each run when full presentation mode is enabled
5. Print the final comparison table and write `benchmark_result.json`

Expected output (mock, illustrative -- numbers are produced, not hardcoded):
```text
=== dflow-vast chaos benchmark (mode=mock, profile=hostile, seed=1337) ===

[naive ] dispatched 20 jobs across 5 instances
[chaos ] evict i-2 @ t=31s   job-07 -> restart from stage 0
[chaos ] evict i-4 @ t=58s   job-12 -> restart from stage 0
...
[naive ] complete: 9/20 jobs   cost $3.40   wall 612s

[colony] dispatched 20 jobs across 5 instances
[chaos ] evict i-2 @ t=31s   job-07 -> RECOVERING -> resumed @ stage 2 on i-6
[chaos ] evict i-4 @ t=58s   job-12 -> RECOVERING -> resumed @ stage 3 on i-7
...
[colony] complete: 20/20 jobs  cost $3.81   wall 668s   recoveries 7   interventions 0

=== RESULT ===
                  completion   cost     wall    recoveries  interventions
naive               45%       $3.40    612s        --            --
dflow-vast         100%       $3.81    668s         7             0

completion delta:  +55 pts     cost delta: +$0.41   under identical loss schedule (seed 1337)
```

**Target acceptance criteria:**
- [ ] `chaos_benchmark_demo.py` runs with `python examples/chaos_benchmark_demo.py` and no API keys (mock mode)
- [ ] Output includes both rows and the delta line; numbers are computed, not literals
- [ ] `benchmark_result.json` is valid JSON containing both `RunReport`s
- [ ] `single_eviction_demo.py` shows one job lost under simulated eviction and resumed from its checkpoint
- [ ] Re-running with the same seed reproduces the same result (determinism in mock mode)
- [ ] Demos import only from `colony/`, `src/` (durableflow), and `data/`; no cycles

### Phase 4: Presentation Layer (Run Scoreboard)

**Status: FULL SCOPE, CUTTABLE AFTER MVP.** Colony benefits from a user-facing surface: the live run scoreboard and the final comparison. The final comparison table is MVP; the live scoreboard is polish and is cut before the live Vast smoke path if the 10-day schedule compresses. Per spec-policy §3.1 and semantics-policy §5, this still requires explicit domain / presentation / render contracts when implemented. The scoreboard is intentionally a thin terminal/HTML view over view models -- no business logic in the renderer.

The primary semantic object is **NOT** `Job` or `Instance` records. It is **"is the work surviving, and is the difference real?"** (see §2.2 conceptual Gherkin). The view model is built around that mental model, not around raw entity CRUD.

#### Phase 4a: Presentation view models + builder
**File:** `colony/views.py`
- `ScoreboardView` dataclass (live, per-run): `runner_label`, `jobs_total`, `jobs_completed`, `jobs_recovering`, `jobs_failed`, `instances_healthy`, `instances_lost`, `spend_usd`, `budget_usd`, `recoveries`, `interventions`, `recent_events` (list of human-readable strings)
- `ComparisonView` dataclass (final): `naive_row: ResultRow`, `colony_row: ResultRow`, `completion_delta_pts`, `cost_delta_usd`, `wall_delta_s`, `chaos_profile`, `seed`, `mode`
- `ResultRow` dataclass: `label`, `completion_rate_pct`, `cost_usd`, `wall_clock_s`, `recoveries`, `interventions`
- Builders: `build_scoreboard_view(run_state) -> ScoreboardView`, `build_comparison_view(benchmark_result: BenchmarkResult) -> ComparisonView`
- Builders consume domain objects (`RunReport`, live run state) and emit view types only

#### Phase 4b: Scenario/demo data catalog
**File:** `colony/view_fixtures.py`
- Fixtures for every cognitive state in §2.2 and every render state:
  - `scoreboard_calm` (no losses yet), `scoreboard_recovering` (active recovery in flight), `scoreboard_budget_halt` (ceiling hit), `scoreboard_done`
  - `comparison_strong_delta` (Colony >> naive), `comparison_marginal` (small delta -- honesty case), `comparison_live_mode`
- Each fixture is a fully-populated view model, renderable with no backend

#### Phase 4c: Render layer
**Files:** `colony/render_terminal.py`, optional `colony/render_html.py`
- `render_scoreboard(view: ScoreboardView) -> str` -- terminal scoreboard frame
- `render_comparison(view: ComparisonView) -> str` -- the result table
- Optional `render_comparison_html(view: ComparisonView) -> str` -- a single static HTML table for the README/screenshot
- Renderers accept presentation view types ONLY; they never import `Job`, `Instance`, `RunReport`, or provider DTOs
- No data fetching, no computation of deltas (deltas are precomputed in the view) inside renderers

**Target acceptance criteria:**
- [ ] `render_scoreboard` and `render_comparison` accept only view types (verified: no domain imports in render files)
- [ ] `build_scoreboard_view` and `build_comparison_view` tested against every fixture in 4b
- [ ] Scoreboard renders all four live states without a live run (from fixtures)
- [ ] Comparison renders strong-delta, marginal, and live-mode fixtures
- [ ] The `comparison_marginal` fixture renders honestly (does not hide a small delta) -- anti-overclaim guard

### Phase 5: Documentation & Tests

**Scope:** README (extends the durableflow README ethos), the methodology writeup (the part Scott reads), project config, tests.

**Files:**
- `README.md` update (Colony section) + `docs/colony-methodology.md`
- `pyproject.toml` update (optional `[vast]` extra)
- `tests/test_colony_recovery.py`, `tests/test_chaos_identity.py`, `tests/test_benchmark.py`, `tests/test_cost.py`, `tests/test_colony_views.py`

**Deliverables:**

#### docs/colony-methodology.md (the research-grade writeup)
1. **Claim:** one sentence -- durable execution converts spot-like compute into completable inventory; here is the measured before/after.
2. **Workload definition:** the exact 20-job, 5-stage toy retrieval/model eval workload: setup, data load, inference/eval shard, metrics write, artifact upload; "completion" means artifact upload committed.
3. **Chaos protocol:** loss process (Poisson, seeded), rate calibration and its stated assumption/source, profiles (calm/moderate/hostile), and the identical-schedule guarantee across both runners. Use "simulated eviction" for mock mode and "controller-induced termination" for live mode.
4. **Runners:** naive (retry, restart-from-zero) vs Colony (checkpoint, migrate, resume). What differs, what is held constant.
5. **Metrics:** completion_rate, total_cost_usd, wall_clock_s, recoveries, interventions. How each is measured.
6. **Results:** the table, plus repeated-seed runs to show variance (report mean and range across N seeds, not a single cherry-picked run).
7. **Threats to validity (mandatory, honest):** mock-vs-live gap; loss-rate assumption; single workload; controller-induced termination as an eviction proxy in live mode; no network-partition modeling. State each plainly.
8. **Forward work (one paragraph, offstage):** "The coordination structure between jobs, instances, and stages is a measurable object; whether its spectral properties predict failure before it occurs is an open question I would test next. It is deliberately not part of this benchmark, which measures only survival and cost." This is the ONLY mention of spectral work, framed as future hypothesis, not result.

#### README Colony section
- Lead with the result table and the one-command demo, not the architecture.
- Headline: "Turning spot-like compute into completable work -- measured."
- Include the reader-safety sentence from §1 verbatim: "This is not a claim that Vast instances are unreliable; it is a benchmark of whether long-running work can survive the class of failures that any spot-priced heterogeneous compute marketplace must handle."
- One paragraph on the business framing (unreliable supply → sellable inventory), generically stated; Vast referenced only as the live provider, with "public evidence suggests" discipline for any company claim.
- Link to `docs/colony-methodology.md` for the full protocol.
- "What this is not": not a Temporal replacement, not a distributed scheduler, not a multi-agent framework, not a spectral-prediction system. A measured durability layer with a real provider backend and an honest benchmark.

**Tone:** genuine engineering + measurement, not a pitch. "I measured this" not "this will revolutionize compute."

#### pyproject.toml
- Reuse durableflow base (stdlib-only core)
- Optional `[vast]` extra: currently empty while the live smoke path uses a gated `VastProvider` stub; any future Vast SDK/CLI client must be pinned with `==`
- Optional `[dev]`: `pytest==8.4.2` (match durableflow pin)
- No new required dependency for mock mode

#### Tests

| Test ID | File | Scenario | Assertion |
|---------|------|----------|-----------|
| T-REC-001 | test_colony_recovery.py | Job checkpointed at stage 2, instance lost | Job resumes at stage 3 on a new instance, not stage 0 |
| T-REC-002 | test_colony_recovery.py | Naive runner, instance lost mid-job | Job restarts at stage 0 |
| T-REC-003 | test_colony_recovery.py | All instances lost in one interval | Jobs return to recoverable; re-acquired within budget; no crash |
| T-REC-004 | test_colony_recovery.py | Colony full benchmark run | human_interventions == 0 |
| T-CHA-001 | test_chaos_identity.py | Same seed, two schedule generations | Event lists are identical (deterministic) |
| T-CHA-002 | test_chaos_identity.py | Benchmark applies schedule to both runners | Both runners receive identical loss events (same targets, same offsets) |
| T-CHA-003 | test_chaos_identity.py | Mock provider, fixed seed, two full runs | Identical RunReports (full determinism) |
| T-BEN-001 | test_benchmark.py | Hostile profile benchmark | colony.completion_rate > naive.completion_rate |
| T-BEN-002 | test_benchmark.py | BenchmarkResult.to_table() | Table contains both rows and the delta line |
| T-BEN-003 | test_benchmark.py | Budget smaller than batch cost | budget_halted True; recorded spend <= budget |
| T-BEN-004 | test_benchmark.py | Idempotent dispatch under mis-detection | Job counted once; no duplicate active dispatch |
| T-CST-001 | test_cost.py | 2 instances run known seconds at known price | total cost == sum(seconds/3600 * price) |
| T-CST-002 | test_cost.py | Cost never hardcoded | total varies when instance-seconds vary |
| T-VEW-001 | test_colony_views.py | build_scoreboard_view per fixture | View fields populated for calm/recovering/budget_halt/done |
| T-VEW-002 | test_colony_views.py | build_comparison_view per fixture | Delta fields correct for strong/marginal/live |
| T-VEW-003 | test_colony_views.py | render files import check | No domain/DTO imports in render_terminal.py / render_html.py |
| T-VEW-004 | test_colony_views.py | marginal fixture renders honestly | Small delta is shown, not suppressed |

**Target acceptance criteria:**
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Mock benchmark is fully deterministic given a seed
- [ ] README result table matches `benchmark_result.json` produced by the demo
- [ ] No external account or key required for tests or mock benchmark
- [ ] `docs/colony-methodology.md` includes the threats-to-validity section

---

## 3.1 Contract Types (UI Feature -- Run Scoreboard)

Colony HAS a user-facing surface, so all three contracts are declared (spec-policy §3.1).

| Contract | Purpose | This Project |
|----------|---------|--------------|
| **Domain contract** | Controller / benchmark outputs | `Job`, `Instance`, `RunReport`, `ChaosEvent`, `BenchmarkResult` |
| **Presentation contract** | View model + builder | `ScoreboardView`, `ComparisonView`, `ResultRow`; `build_scoreboard_view()`, `build_comparison_view()` |
| **Render contract** | Component functions | `render_scoreboard(view: ScoreboardView)`, `render_comparison(view: ComparisonView)`, optional `render_comparison_html(view: ComparisonView)` |

**Anti-pattern explicitly avoided:** no `render_comparison(result: BenchmarkResult)` that accepts the domain DTO directly. The renderer takes `ComparisonView`, whose builder precomputes deltas. Renderers contain no delta math and no domain imports.

---

## 3.2 Runtime Traceability (Golden Path -- chaos benchmark)

```
main()  # examples/chaos_benchmark_demo.py
  -> load batch_20jobs.json, chaos_profiles.json["hostile"]
  -> provider_factory = MockProvider(seed) or VastProvider() if --live
  -> Benchmark.run(batch, budget, profile, provider_factory)   # colony/benchmark.py
       -> schedule = ChaosSchedule.generate(seed, duration, rate, pool)   # colony/chaos.py
       -> naive = NaiveRunner.run_batch(batch, budget, provider_factory(), schedule)  # colony/baseline.py
            -> dispatch jobs to instances
            -> on ChaosEvent evict: mark job failed-or-retry; restart from stage 0
            -> CostAccountant.charge(...)            # colony/cost.py
            -> returns RunReport(runner="naive")
       -> colony = ColonyController.run_batch(batch, budget, provider_factory(), schedule)  # colony/controller.py
            -> dispatch jobs; for each job stage:
                 -> WorkflowEngine.execute(job_as_workflow)   # src/engine.py (REUSED)
                      -> save_checkpoint(stage)               # src/store.py (REUSED)
                 -> Job.checkpoint_ref updated                # colony/store_ext.py
            -> health monitor: provider.health(instance)      # colony/provider.py
            -> on ChaosEvent evict (same schedule object):
                 -> mark assigned job recovering at last checkpoint
                 -> idempotency check side_effect_log(sha256(run_id+job_id+"dispatch"))  # REUSED
                 -> acquire/select healthy instance
                 -> WorkflowEngine.resume(job_as_workflow)     # src/engine.py (REUSED) -> resumes at current_stage+1
                 -> recoveries += 1
            -> budget guard: stop acquire at budget; drain; set budget_halted
            -> assert human_interventions == 0
            -> returns RunReport(runner="colony")
       -> build BenchmarkResult(naive, colony, deltas)
  -> view = build_comparison_view(benchmark_result)            # colony/views.py
  -> print(render_comparison(view))                            # colony/render_terminal.py
  -> write benchmark_result.json
```

Live scoreboard during each run:
```
run loop tick
  -> build_scoreboard_view(live_run_state)   # colony/views.py
  -> render_scoreboard(view)                 # colony/render_terminal.py  (view types only)
```

All methods and imports above are defined in this specification or inherited from durableflow v0.1 (marked REUSED). No undefined items.

---

## 4. Entry Gates

### 4.1 Specification Completeness
- [x] All acceptance criteria explicitly written and unambiguous (per phase)
- [x] Each claimed capability has a verification method (Test IDs mapped in §5)
- [x] No TBD/TODO placeholders in this specification
- [x] Dependencies listed and pinned: stdlib-only core; `[vast]` extra currently has no selected third-party client; `pytest==8.4.2` dev pinned. Durableflow v0.1 is a pinned internal dependency.

### 4.2 Cross-Reference Consistency
- [x] Narrative (§1) claims match detailed phases (§3): durability, recovery, chaos identity, benchmark, cost
- [x] Test plan (§5) covers all acceptance criteria across Phases 1–5
- [x] No contradictions: spectral work is excluded from the artifact everywhere it is mentioned (positioning note, methodology forward-work, README "what this is not")

### 4.3 Implementation Readiness
- [x] All file paths and module names specified (§3, Appendix A)
- [x] Data models fully defined: `Job`, `Instance`, `RunReport`, `ChaosEvent`, `BenchmarkResult`, `ScoreboardView`, `ComparisonView`, `ResultRow` -- all fields enumerated
- [x] Integration points: durableflow engine/store/side_effect_log reuse explicitly identified (§3.2 REUSED tags); Vast provider gated by env var
- [x] Runtime traceability: §3.2 lists every golden-path call and import; REUSED items marked
- [x] Presentation contract defined: `build_scoreboard_view()` / `build_comparison_view()` signatures + view schemas (§3.1, Phase 4a)
- [x] API contract table lists builders, not renderers accepting domain DTOs (§3.1)
- [x] Scenario catalog (Phase 4b) covers all conceptual Gherkin (§2.2) and render states
- [x] Trace diagram includes orchestrator → execution → build_*_view() → render_* (§3.2)

---

## 5. Test Plan

### 5.1 Unit Tests (Logic)
Mapped in the Phase 5 test table: T-REC-001..004 (recovery), T-CHA-001..003 (chaos identity/determinism), T-CST-001..002 (cost), T-VEW-001..004 (views/render).

### 5.2 Integration Tests (Workflow)

| Test ID | Scenario | Assertion |
|---------|----------|-----------|
| T-INT-001 | Full mock benchmark, hostile profile | Both RunReports produced; colony.completion_rate > naive.completion_rate; interventions==0 |
| T-INT-002 | Single simulated-eviction end-to-end | One job lost, resumed at last checkpoint, batch completes |
| T-INT-003 | Budget-halt end-to-end | Spend <= budget; budget_halted True; partial result reported, no crash |
| T-INT-004 | Determinism | Same seed, two full benchmarks → identical BenchmarkResult |
| T-INT-005 | Live smoke (manual, gated) | With VAST_API_KEY, acquire a real instance, run the 5-stage smoke job, perform one controller-induced termination or record an observed provider loss, reacquire/resume, release; cost > 0 from real pricing |

T-INT-005 is a gated manual smoke test, not part of the default CI run (requires a funded Vast account). Documented as such.

---

## 6. Exit Gates

### 6.1 Implementation Verification
- [ ] Durable recovery: read `controller.py`; verify resume uses `current_stage`, not 0; verify durableflow `resume()` is the mechanism
- [ ] Naive contrast: read `baseline.py`; verify it restarts from stage 0 (no checkpoint use)
- [ ] Chaos identity: read `benchmark.py`; verify the SAME schedule object/seed drives both runners
- [ ] Idempotent dispatch: read controller dispatch; verify `side_effect_log` check before activation
- [ ] Budget: read budget guard; verify recorded spend never exceeds ceiling
- [ ] Cost: read `cost.py`; verify computed from instance-seconds × price, never hardcoded
- [ ] Interventions: verify the Colony runner asserts `human_interventions == 0`
- [ ] Views: verify renderers import only view types (no domain/DTO imports)

### 6.2 Acceptance Criteria Checklist
- [ ] All Phase 1 acceptance criteria checked (6)
- [ ] All Phase 2 acceptance criteria checked (8)
- [ ] All Phase 3 acceptance criteria checked (6)
- [ ] All Phase 4 acceptance criteria checked (5)
- [ ] All Phase 5 acceptance criteria checked (5)
- [ ] All unit + integration tests pass (`pytest tests/ -v`), excluding the gated live smoke
- [ ] Mock benchmark demo runs with no keys and is deterministic

### 6.3 Dependency Verification
- [ ] Core remains stdlib-only (mock mode requires no third-party package)
- [ ] `[vast]` extra has no unpinned dependency; any future Vast SDK/CLI client is pinned with `==`
- [ ] `pytest` pinned with `==8.4.2`, matching durableflow
- [ ] No new required dependency added without rationale in README design decisions

### 6.4 Cross-Reference Validation
- [ ] README result table matches `benchmark_result.json`
- [ ] No DEFERRED item claimed complete
- [ ] `docs/colony-methodology.md` threats-to-validity section present and honest
- [ ] Spectral work appears ONLY as forward-work hypothesis; never claimed as a result anywhere
- [ ] Any company-specific claim uses "public evidence suggests" + link

### 6.5 Presentation Layer Verification (UI Feature -- ACTIVE, not deferred)
- [ ] `render_scoreboard` / `render_comparison` accept presentation view types only
- [ ] `build_scoreboard_view()` tested for calm/recovering/budget_halt/done fixtures
- [ ] `build_comparison_view()` tested for strong/marginal/live fixtures
- [ ] No render file imports `Job`/`Instance`/`RunReport`/`BenchmarkResult` for rendering (builder wiring is OK)
- [ ] Result-table layout maps 1:1 to `ComparisonView` fields, not hardcoded numbers
- [ ] `comparison_marginal` fixture renders the small delta honestly (anti-overclaim)

---

## 7. Pre-Mortem Analysis

*It is the post-mortem review. The benchmark did not deliver. What went wrong?*

| Failure Category | Risk Factor | Probability | Impact |
|------------------|-------------|-------------|--------|
| **Commercial validation** | Reader sees a Temporal/Ray reimplementation and asks "why does Vast care" | Medium | High |
| **Data credibility** | Benchmark is mock-only; reader discounts it as a simulation with no live provider contact | High | High |
| **Overreach** | Spectral framing leaks into the headline and invites "show me the validation data" | Low (guarded) | High |
| **Methodology** | Single seed / single workload; result looks cherry-picked | Medium | High |
| **Reliability** | Live mode flaky; demo fails on the reviewer's machine or burns budget unpredictably | Medium | Critical |
| **Honesty gap** | A marginal delta is dressed up as decisive; reader catches the spin | Low | Critical |
| **Scope creep** | Trying to build a real distributed scheduler eats the timeline; nothing ships | Medium | Critical |

---

## 8. Remediation & Acceptance

| Risk | Mitigation | Integrated Into |
|------|------------|-----------------|
| "Why does Vast care" | Lead README + methodology with the unreliable-supply→sellable-inventory business framing; Vast is the live provider, not a generic backend | Phase 5 README; §1 Why |
| Mock discounted as simulation | Ship a real `--live` path that provisions actual Vast instances, reads real pricing, and runs at least one controller-induced termination recovery; include at least one live result in the methodology with mode=live labeled; calibrate the mock loss rate to a stated public assumption | Phase 1 VastProvider; Phase 5 methodology; T-INT-005 |
| Spectral overreach | Hard rule: spectral appears only as one forward-work paragraph; asserted in exit gate 6.4; not in any table or headline | §0; Phase 5 methodology; gate 6.4 |
| Cherry-picked result | Report mean and range across N seeds, not one run; determinism tests prove identical schedules across runners | Phase 5 methodology §6; T-CHA-001..003 |
| Live flakiness / budget burn | Default to mock; live is opt-in and budget-capped; live smoke is a gated manual test; controller-induced termination clearly labeled as a proxy for spot-like loss | Phase 2 budget guard; T-INT-005 |
| Honesty gap | `comparison_marginal` fixture + T-VEW-004 force the renderer to show small deltas truthfully; threats-to-validity section mandatory | Phase 4b/4c; Phase 5 |
| Scope creep | Reuse durableflow engine/store/side-effect-log unchanged; Colony adds only controller, chaos, baseline, cost, minimal live provider smoke, and optional views; explicit "what this is not" disclaims distributed scheduling | §3.2 REUSED; scope-cut list below |

**Deferred items (accepted technical debt):**
- Controller-induced termination as a live proxy for spot-like loss (true provider-driven losses are not on-demand); documented in threats-to-validity.
- Single workload type in the benchmark; multi-workload generalization is future work.
- No network-partition or slow-instance (straggler) modeling beyond evict/throttle; documented.
- Mock token/stage timing is approximate; live mode measures real seconds.
- Spectral coordination prediction: explicitly out of scope; forward-work hypothesis only.

**Scope cut priority (if the 10 days compress). Drop in this order:**
1. `render_html.py` and HTML comparison (terminal table is sufficient for the artifact)
2. Live scoreboard animation/refresh; keep the final comparison table
3. Extra presentation fixtures beyond the marginal-honesty comparison
4. `throttle` chaos event type (simulated eviction / termination loss is enough to demonstrate the core result)
5. Broader repeated-seed matrix beyond the minimum methodology table

**Keep for MVP:** durable recovery vs naive contrast, identical-schedule chaos engine, benchmark result table, cost accounting, determinism tests, methodology writeup with threats-to-validity, marginal-result honesty guard, and the gated live Vast smoke test. If the full `VastProvider` cannot be completed, preserve a narrow live smoke implementation that provisions one instance, records real pricing, triggers one controller-induced termination or records observed provider loss, reacquires, and resumes one job.

---

## 9. Code Review Gates

### 9.1 Implementer Self-Review
Before reporting DONE:
- [ ] Any TODO on core capabilities (recovery, chaos identity, benchmark, cost, idempotent dispatch)? → DONE_WITH_CONCERNS
- [ ] All imports used?
- [ ] Hardcoded values (prices, rates, pool sizes) extracted to config/fixtures, not buried in logic?
- [ ] Error handling covers: instance-acquire failure, total pool loss, budget exhaustion mid-recovery, provider timeout, empty batch, seed-missing?

### 9.2 Spec Compliance Review
- [ ] Read `controller.py`: resume uses last checkpoint (durableflow `resume`), not stage 0
- [ ] Read `baseline.py`: restarts from stage 0; no checkpoint reuse (the contrast must be real)
- [ ] Read `benchmark.py`: identical schedule object/seed applied to both runners (benchmark validity)
- [ ] Read `cost.py`: cost from instance-seconds × price; grep for hardcoded cost literals
- [ ] Read render files: no domain/DTO imports; deltas precomputed in builders
- [ ] Grep for "spectral" across the repo: only the single forward-work paragraph permitted

### 9.3 Code Quality Escalation
- [ ] Fix, or accept as documented debt in README "Design decisions"
- [ ] DONE_WITH_CONCERNS if proceeding with known issues

### 9.4 Integration Review (modifying durableflow)
- [ ] Existing durableflow tests still pass (no regression to the engine/store)
- [ ] Job-as-workflow mapping does not mutate engine internals; uses public `execute`/`resume`/`save_checkpoint`
- [ ] SQLite schema extensions are additive (new tables); `side_effect_log` reused without schema change
- [ ] DB path, telemetry destination, and provider selection are injectable/configurable

---

## 10. Declaration Standards

### 10.1 Status Definitions
| Status | Applied When |
|--------|--------------|
| DRAFT | Spec being written |
| READY | Entry gates (§4) all checked -- current state |
| IN_PROGRESS | First Colony file created |
| PARTIAL | Mock benchmark runs end-to-end; live path or views incomplete |
| COMPLETE | All exit gates passed; mock benchmark deterministic; README table matches JSON; methodology done |
| DEFERRED | (none at spec level; sub-items deferred are listed in §8) |

### 10.2 Plan Update Requirements
Before marking any phase COMPLETE: run exit gates (§6); verify no TODOs on claimed capabilities; cross-read README table against `benchmark_result.json`.

### 10.3 Prohibited Practices
- NEVER claim "survives simulated eviction" or "survives spot-like loss" if recovery restarts from stage 0 (that is the naive baseline)
- NEVER claim a completion-rate delta unless both rows ran the identical seeded schedule
- NEVER hardcode the benchmark numbers in the README; they must come from a run
- NEVER present spectral prediction as a result; it is a forward hypothesis only
- NEVER claim "real eviction" in live mode unless Vast independently terminates the instance; otherwise say "controller-induced termination"
- NEVER let a render file import a domain DTO for rendering
- NEVER reference Vast's internal architecture as fact without "public evidence suggests" + link

### 10.4 Victory Declaration Anti-Patterns

| Anti-Pattern | Example in This Project | Correct Approach |
|--------------|------------------------|------------------|
| Naive == Colony | Baseline secretly checkpoints, inflating both rows | Baseline restarts from stage 0; contrast is real (T-REC-002) |
| Mock dressed as real | README implies real eviction; all data is mock | Label mode explicitly; ship a live path; calibrate + caveat the mock rate |
| Cherry-picked seed | One favorable run reported as the result | Mean + range across N seeds (methodology §6) |
| Spectral creep | "Eigenvalues predict failure" in the abstract | One forward-work paragraph; grep-guarded in review (§9.2) |
| Cost is decoration | cost_usd always 0.0 or constant | Computed from instance-seconds × price (T-CST-001/002) |
| Renderer holds logic | `render_comparison(BenchmarkResult)` computes deltas | `build_comparison_view` precomputes; renderer takes `ComparisonView` |
| Golden path only | Scoreboard demo shows only the happy "all complete" frame | Fixtures for calm/recovering/budget_halt/done + marginal comparison (Phase 4b) |
| Marginal spun as decisive | 51% vs 49% rendered as a triumph | `comparison_marginal` fixture + T-VEW-004 force honest rendering |

---

## Appendix A: File Manifest

```
durableflow/
  README.md                          # Phase 5 -- add Colony section
  pyproject.toml                     # Phase 5 -- includes colony package discovery and [vast] extra
  docs/
    colony-spec.md                   # this document (private)
    colony-methodology.md            # Phase 5 -- the research-grade writeup
  src/                               # EXISTING durableflow v0.1 -- reused unchanged
    engine.py                        #   REUSED: execute / resume / save_checkpoint
    store.py                         #   REUSED: checkpoint persistence, side_effect_log
    telemetry.py                     #   REUSED: JSON-lines logger
  colony/                            # NEW package
    __init__.py
    models.py                        # Phase 1 -- Job, Instance, RunReport, ChaosEvent
    provider.py                      # Phase 1 -- ComputeProvider, MockProvider, VastProvider
    store_ext.py                     # Phase 1 -- jobs/instances/runs/chaos_events schema
    controller.py                    # Phase 2 -- Colony runner (dispatch/health/recovery)
    chaos.py                         # Phase 2 -- seeded chaos schedule
    baseline.py                      # Phase 2 -- naive runner
    cost.py                          # Phase 2 -- GPU-hour accounting
    telemetry_ext.py                 # Phase 3 -- Colony event types via TelemetryLogger.log_event
    benchmark.py                     # Phase 3 -- runs both rows, emits BenchmarkResult
    views.py                         # Phase 4a -- ScoreboardView, ComparisonView, builders
    view_fixtures.py                 # Phase 4b -- scenario catalog
    render_terminal.py               # Phase 4c -- terminal renderers (view types only)
    render_html.py                   # Phase 4c -- optional static HTML table (view types only)
  examples/
    chaos_benchmark_demo.py          # Phase 3 -- headline demo (mock default, --live opt-in)
    single_eviction_demo.py          # Phase 3 -- minimal eviction+resume
  data/
    batch_20jobs.json                # Phase 3 -- seeded job batch
    chaos_profiles.json              # Phase 3 -- calm/moderate/hostile profiles + seeds
  tests/
    test_colony_recovery.py          # T-REC-001..004
    test_chaos_identity.py           # T-CHA-001..003
    test_benchmark.py                # T-BEN-001..004
    test_cost.py                     # T-CST-001..002
    test_colony_views.py             # T-VEW-001..004
```

---

## Appendix B: Dependency Matrix

| Module | Imports From (internal) | Imports From (durableflow) | Imports From (stdlib) | External |
|--------|-------------------------|----------------------------|-----------------------|----------|
| models.py | -- | -- | dataclasses, enum, datetime, uuid, json | -- |
| provider.py | models | -- | abc, dataclasses, random, time, typing | vast client (optional, [vast]) |
| store_ext.py | models | store (REUSED) | sqlite3, json, datetime | -- |
| controller.py | models, provider, store_ext, cost, telemetry_ext | engine, store (REUSED) | hashlib, time, typing | -- |
| chaos.py | models | -- | random, dataclasses, typing | -- |
| baseline.py | models, provider, cost, telemetry_ext | -- | time, typing | -- |
| cost.py | models | -- | -- | -- |
| telemetry_ext.py | -- | telemetry (REUSED) | typing | -- |
| benchmark.py | models, controller, baseline, chaos, cost | -- | dataclasses, statistics, typing | -- |
| views.py | models, benchmark | -- | dataclasses, typing | -- |
| view_fixtures.py | views | -- | -- | -- |
| render_terminal.py | views | -- | (views only) | -- |
| render_html.py | views | -- | (views only) | -- |
| chaos_benchmark_demo.py | benchmark, provider, views, render_terminal | -- | json, pathlib, argparse, os | -- |
| single_eviction_demo.py | controller, provider, chaos | engine, store (REUSED) | json, pathlib | -- |

Dependency direction: `examples/ -> colony/ -> src/ (durableflow)`. Within `colony/`: `benchmark -> controller, baseline, chaos`; `controller -> provider, store_ext, cost, telemetry_ext`; `views -> benchmark, models`; `render_* -> views` only. No cycles. Render layer depends on views only and never on models or benchmark.

---

## Appendix C: SQLite Schema Extensions

Additive to the existing durableflow schema. `side_effect_log` is reused unchanged for idempotent dispatch.

```sql
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    mode                TEXT NOT NULL,        -- mock | live
    runner              TEXT NOT NULL,        -- naive | colony
    batch_id            TEXT NOT NULL,
    batch_size          INTEGER NOT NULL,
    budget_usd          REAL NOT NULL,
    chaos_seed          INTEGER NOT NULL,
    jobs_completed      INTEGER NOT NULL DEFAULT 0,
    instances_acquired  INTEGER NOT NULL DEFAULT 0,
    instances_lost      INTEGER NOT NULL DEFAULT 0,
    recoveries          INTEGER NOT NULL DEFAULT 0,
    human_interventions INTEGER NOT NULL DEFAULT 0,
    total_cost_usd      REAL NOT NULL DEFAULT 0.0,
    wall_clock_seconds  REAL NOT NULL DEFAULT 0.0,
    budget_halted       INTEGER NOT NULL DEFAULT 0,
    started_at          TEXT NOT NULL,
    ended_at            TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id              TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    batch_id            TEXT NOT NULL,
    spec                TEXT NOT NULL,        -- JSON
    stage_count         INTEGER NOT NULL,
    current_stage       INTEGER NOT NULL DEFAULT -1,
    status              TEXT NOT NULL DEFAULT 'queued',
    assigned_instance_id TEXT,
    checkpoint_ref      TEXT,                 -- references durableflow workflow/checkpoint
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS instances (
    instance_id         TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    provider            TEXT NOT NULL,        -- mock | vast
    gpu_type            TEXT,
    cost_per_hour_usd   REAL NOT NULL DEFAULT 0.0,
    status              TEXT NOT NULL DEFAULT 'requested',
    provider_handle     TEXT,                 -- JSON: provider-specific id
    acquired_at         TEXT,
    lost_at             TEXT,
    released_at         TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS chaos_events (
    event_id            TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    scheduled_offset_s  REAL NOT NULL,
    event_type          TEXT NOT NULL,        -- evict | throttle
    target_instance_id  TEXT,
    applied             INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_instances_run ON instances(run_id);
CREATE INDEX IF NOT EXISTS idx_instances_status ON instances(status);
CREATE INDEX IF NOT EXISTS idx_chaos_run ON chaos_events(run_id);
```

`side_effect_log` (reused from durableflow, unchanged): idempotent dispatch key format `sha256(run_id + ":" + job_id + ":dispatch")`.

---

## Appendix D: What This Spec Deliberately Excludes

To keep the artifact honest and the timeline real, the following are explicitly out of scope and named in the README "What this is not":

- A distributed scheduler or a Temporal/Ray replacement (Colony reuses a single-node durable engine and orchestrates a small pool; it is a measurement instrument, not production infrastructure).
- Multi-agent reasoning, planning, or memory frameworks.
- Spectral coordination detection or predictive failure modeling (forward-work hypothesis only).
- Real spot-eviction triggering on demand (live mode uses controller-induced termination as a labeled proxy unless an independent provider loss is observed).
- Network-partition, straggler, or Byzantine-failure modeling beyond evict/throttle.
- High-throughput or large-pool scaling claims; the benchmark uses a small, clearly stated pool.

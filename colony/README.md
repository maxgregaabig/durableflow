# Colony

Turning spot-like compute into completable work -- measured.

Colony is the DurableFlow extension for long-running work on spot-like heterogeneous compute. It compares a naive retry runner against a durable runner under the same seeded loss schedule, then reports completion, cost, wall-clock, recoveries, and human interventions.

The core claim is deliberately narrow:

> A durable execution layer turns spot-like decentralized compute into inventory that completes long-running work without human intervention. Here is the measured before/after.

This is not a claim that Vast instances are unreliable; it is a benchmark of whether long-running work can survive the class of failures that any spot-priced heterogeneous compute marketplace must handle.

## Run It

Mock mode is deterministic and requires no external account:

```bash
python3 examples/chaos_benchmark_demo.py
```

Useful variants:

```bash
python3 examples/chaos_benchmark_demo.py --profile calm
python3 examples/chaos_benchmark_demo.py --profile moderate
python3 examples/chaos_benchmark_demo.py --profile hostile
python3 examples/single_eviction_demo.py
```

Live mode is gated and requires `VAST_API_KEY`:

```bash
VAST_API_KEY=... python3 examples/chaos_benchmark_demo.py --live
```

## Current Mock Result

```text
=== RESULT mode=mock profile=hostile seed=1337 ===
                  completion   cost     wall    recoveries  interventions
naive                90%     $ 0.23     701s        --            --
dflow-vast          100%     $ 0.23     689s        10             0

completion delta: +10 pts     cost delta: +0.00   under identical loss schedule (seed 1337)
```

The benchmark workload is 20 small AI-eval-style jobs. Each job has five durable stages: setup, data load, inference/eval shard, metrics write, and artifact upload. A job is complete only after artifact upload commits.

## What Differs

Both runners use the same workload, provider type, budget, pool size, and chaos schedule.

The naive runner retries after instance loss and restarts the job from stage 0.

The Colony runner checkpoints after each completed stage, marks lost work recoverable, migrates it to a healthy instance, and resumes from the last checkpoint.

## Files

- [colony-spec.md](colony-spec.md) -- private implementation spec and acceptance criteria
- [../docs/colony-methodology.md](../docs/colony-methodology.md) -- public methodology, assumptions, and threats to validity
- [benchmark.py](benchmark.py) -- naive-vs-Colony benchmark orchestrator
- [controller.py](controller.py) -- durable controller, dispatch, recovery, and migration
- [provider.py](provider.py) -- mock provider and gated Vast provider
- [render_terminal.py](render_terminal.py) -- CLI comparison renderer

## What This Is Not

Colony is not a Temporal replacement, a distributed scheduler, a multi-agent framework, or a spectral-prediction system. It is a measured durability layer with a mock benchmark, a gated live-provider path, and an honest methodology.

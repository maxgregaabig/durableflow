# Module 6: Colony — Measured Durability on Hostile Compute

**Duration:** 1.5 hours  
**Format:** Benchmark demo + methodology critique

## Summary

Colony compares naive restart-from-zero vs durable checkpoint-resume under an identical seeded loss schedule. The workload is 20 five-stage jobs; completion requires artifact upload. The benchmark reports completion, cost, wall-clock, recoveries, and human interventions.

## Key concepts

- Narrow claim: durability converts spot-like compute into completable inventory
- Naive runner vs Colony runner — same chaos seed
- Threats to validity: mock mode, single workload, proxy termination
- Five stages: setup → data_load → inference_eval_shard → metrics_write → artifact_upload

## Labs

| ID | Task |
|----|------|
| W9 | [Seed sensitivity](workshop-exercises.md#w9-seed-sensitivity-colony) |
| Capstone D | [New chaos profile](capstone.md#track-d-colony-chaos-profile) |

## Demo commands

```bash
python3 examples/chaos_benchmark_demo.py --profile hostile
python3 examples/chaos_benchmark_demo.py --profile calm
python3 examples/single_eviction_demo.py
```

## Readings

- [colony/README.md](../../colony/README.md)
- [colony-methodology.md](../colony-methodology.md)
- [curriculum.md — Module 6](curriculum.md#module-6-colony--measured-durability-on-hostile-compute)

## Exit ticket

Why must both runners share the same chaos seed?

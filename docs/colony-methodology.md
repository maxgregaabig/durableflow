# Colony Methodology

## Claim

Durable execution converts spot-like compute into completable inventory; here is the measured before/after.

## Workload

The benchmark runs 20 small AI-eval-style jobs over a toy retrieval/model benchmark. Each job has five durable stages:

1. setup
2. data_load
3. inference_eval_shard
4. metrics_write
5. artifact_upload

Completion means the artifact-upload stage committed. In mock mode, stages are deterministic timed work with seeded cost. In live mode, the same stage shape runs against a Vast-backed smoke path and records real elapsed time and pricing.

## Chaos Protocol

Chaos is a seeded Poisson loss process. The exact same generated schedule is applied to both runners. Mock mode labels these events as simulated evictions. Live mode labels controller-triggered instance termination as controller-induced termination unless the provider independently terminates the instance.

## Runners

The naive runner retries after loss and restarts the job from stage 0. Colony checkpoints after each completed stage and resumes from the last durable checkpoint on a newly acquired instance. Dispatch, budget, workload, provider type, and chaos schedule are held constant.

## Metrics

The benchmark reports completion rate, total cost in USD, wall-clock seconds, recoveries, and human interventions. Cost is computed from recorded instance-seconds multiplied by per-hour instance price.

## Threats To Validity

Mock mode is not live infrastructure. The loss rate is an assumption, not a claim about Vast's internal reliability. The benchmark uses one workload. Controller-induced termination is a proxy for spot-like loss in live mode. Network partitions and stragglers are not modeled.

## Forward Work

The coordination structure between jobs, instances, and stages is a measurable object; whether its spectral properties predict failure before it occurs is an open question I would test next. It is deliberately not part of this benchmark, which measures only survival and cost.

# Proposal: Prune DataFlow v0.1

**Status:** PROPOSAL
**Created:** 2026-06-23
**Applies to:** `dataflow-spec.md`

---

## 1. Concern

`dataflow-spec.md` has a coherent direction, but v0.1 risks overloading DurableFlow into a mini-Dagster, schema registry, validator, graph builder, lineage platform, and agent framework.

The durable system should stay conceptually narrow:

```text
DurableFlow = durable step execution
Context = what information was selected, used, and credited
DataFlow = what typed data products moved through the workflow
```

That separation is strong. The risk is adding too many supporting abstractions before the core DataFlow claim is proven.

---

## 2. v0.1 Core

DataFlow v0.1 should keep only four first-class concepts:

1. `DataTypeSpec`
   - name
   - version
   - schema kind
   - validation mode

2. `StepContract`
   - step name
   - input data types
   - output data types

3. `DataArtifact`
   - runtime materialization of one typed product
   - content digest/ref
   - producer step
   - validation status

4. `DataDependency`
   - lineage edge from input artifact to output artifact
   - v0.1 dependency type: `consumed_to_produce`

Everything else should be presentation, implementation detail, or roadmap.

---

## 3. Sharpened Claim

The v0.1 claim should be:

> DurableFlow can declare step input/output data contracts, record typed artifacts produced at runtime, and trace final outputs back through their input artifacts.

That is enough to prove the data-first viewpoint:

> Data products are first-class; steps are computations attached to the data DAG.

---

## 4. Recommended v0.1 Lifecycle

Use a small lifecycle:

```text
contract declared -> artifact materialized -> artifact consumed -> dependency recorded
```

Avoid a larger lifecycle in v0.1:

```text
expected -> consumed -> materialized -> validated -> rejected -> dependency_recorded -> completed
```

The larger version is not wrong, but it pulls v0.1 toward platform complexity before the core proof exists.

---

## 5. Defer or Demote

Move these out of v0.1:

- `expect_artifact`
- `artifact_expected` event
- `artifact_rejected` event
- Pydantic enhancement
- Mermaid rendering
- decorator/wrapper API
- rich `dependency_type` variants such as:
  - `branched_from`
  - `summarized_from`
  - `approved_from`
  - `sent_from`
  - `context_derived_from`

Collapse v0.1 `dependency_type` to:

```text
consumed_to_produce
```

Add richer edge semantics only after the first audit trace proves useful.

---

## 6. Reconsider `DataflowEvent`

`DataflowEvent` may not be needed in v0.1.

The core audit may be answerable from:

- `DataTypeSpec`
- `StepContract`
- `DataArtifact`
- `DataDependency`
- validation status on `DataArtifact`

If an event table is kept, it should be minimal and only record events that cannot be derived from those tables.

Suggested minimal events:

- `contract_registered`
- `artifact_materialized`
- `artifact_consumed`
- `dependency_recorded`
- `contract_violation`

Do not add `artifact_expected`, `artifact_rejected`, or `dataflow_completed` until there is a concrete reader or test that needs them.

---

## 7. Boundary Rules

Keep the ownership boundaries strict:

- DurableFlow core owns execution, checkpointing, approval pause/resume, idempotency, and telemetry.
- `/context` owns context artifacts, retrieval/selection/rejection/consumption, and decision influence.
- DataFlow owns typed artifact flow, step contracts, and artifact dependency lineage.

DataFlow should reference context artifacts and decisions, not duplicate their semantics.

---

## 8. Recommended Next Edit

Revise `dataflow-spec.md` to make v0.1 a thin contract and lineage layer:

- keep the four core concepts
- simplify event types
- remove optional Pydantic from v0.1
- reduce dependency types to `consumed_to_produce`
- move authoring helpers, graph rendering, advanced validation, and rich edge semantics to roadmap

This preserves the distinct viewpoint without turning DurableFlow into a general data platform.

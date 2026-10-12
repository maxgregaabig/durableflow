# Proposal: Durable Experiment Replay for Hill-Climbing Agent Systems

**Status:** PROPOSAL
**Created:** 2026-07-28
**Decision requested:** Approve Durable Experiment Replay as a sibling DurableFlow extension built on `evals/`, `context/`, and the durable runtime.
**Proposed package:** `experiments/`
**Depends on:** `docs/eval-gate-spec.md`, `proposals/trajectory-evals-proposal.md`, `context/`, `src/`
**Explicitly does not propose:** a built-in genetic optimizer, production side-effect replay, or a hosted experiment platform.

---

## 1. Decision

DurableFlow should own the reusable mechanics required to turn production traces
into controlled, replayable experiments:

1. Capture a completed execution as a replayable scenario.
2. Bind that scenario to one or more versioned candidate configurations.
3. Resimulate the workflow against every candidate.
4. Score the resulting trajectories and outcomes through `evals/`.
5. Compare challengers with the baseline.
6. Apply hard safety constraints and promotion policy.
7. Persist the experiment, intermediate progress, evidence, and verdict so the
   experiment itself survives interruption.

The optimizer that proposes candidates should remain outside this extension.
Genetic search, Bayesian optimization, grid search, and human-authored variants
should all consume the same experiment interface.

```text
optimizer or engineer proposes candidates
                    │
                    ▼
        DurableFlow Experiment Replay
        scenario × candidate execution
                    │
                    ▼
       evals: trajectory and outcome scoring
                    │
                    ▼
       fitness vector + hard-gate verdict
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
 optimizer proposes       promotion gate
 next generation          accepts or blocks
```

This makes DurableFlow the durable experimental substrate, not the owner of the
search strategy.

---

## 2. Why This Belongs in DurableFlow

This capability is a natural extension of existing DurableFlow responsibilities:

| Existing capability | Contribution to experiment replay |
|---|---|
| Workflow checkpointing | Candidate runs and experiment matrices can resume after interruption. |
| Side-effect suppression and approval gates | Replays can prevent or simulate external writes. |
| Model routing and cost accounting | Candidate model choices can be measured consistently. |
| Context lineage | Context-selection variants can be compared with evidence about what was retrieved, selected, consumed, and credited. |
| Telemetry | Reconstructed runs have inspectable execution paths. |
| `evals/` | Resulting executions can be scored and gated. |
| Colony | Large candidate matrices can eventually use failure-tolerant distributed execution. |

`docs/eval-gate-spec.md` already assigns DurableFlow the responsibility to
normalize traces into cases, replay or score them, and emit a release gate. The
current implementation covers case extraction, scoring, reporting, and CI
verdicts. It does not yet execute a recorded scenario against changed prompts,
context policies, models, tool configurations, or workflow code.

The missing capability is therefore not another scoring function. It is the
controlled execution layer between an eval case and an eval result:

```text
captured trace
    ↓
replayable scenario
    ↓
candidate configuration
    ↓
resimulated workflow
    ↓
new trace
    ↓
evaluation and comparison
```

---

## 3. Boundaries

### 3.1 DurableFlow owns

- Replay scenario capture and validation.
- Versioned candidate references.
- Candidate execution through a replaceable adapter.
- Frozen, simulated, and shadow replay modes.
- Durable experiment scheduling and checkpointing.
- Trace and artifact correlation.
- Baseline-versus-challenger comparison.
- Fitness-vector production.
- Hard-gate enforcement and promotion evidence.
- Local, deterministic fixtures for the reference implementation.

### 3.2 DurableFlow does not own

- The algorithm that generates or mutates candidates.
- Domain-specific definitions of task success.
- A universal scalar fitness function.
- Production prompt or model registries.
- Model training or fine-tuning.
- Online traffic allocation or a general A/B experimentation service.
- Authorization to repeat real external side effects.
- EVR's independent oracle construction or UDR/IBR semantics.
- EKO's governed policy and release semantics.

### 3.3 Relationship to adjacent packages

| Package or boundary | Responsibility |
|---|---|
| `experiments/` | Produce candidate executions and baseline comparisons. |
| `evals/` | Score executions and aggregate ship/hold/block verdicts. |
| `context/` | Record context assembly and decision lineage. |
| `src/` | Provide checkpointing, recovery, approvals, cost records, and side-effect controls. |
| EVR | Supply independent safety evaluators such as UDR and IBR when integrated. |
| EKO | Supply governed release, policy, and rule identities when integrated. |
| MCP | Transport tool discovery and invocation; it does not define replay semantics. |
| External optimizer | Propose the next candidate generation from fitness and evidence. |

---

## 4. Product Criteria

The extension is successful when it enables the following hill-climbing cadence:

- Production traces can be promoted into structured replay scenarios.
- Prompt, context, model, tool, and code changes can trigger regression runs.
- Results provide clear baseline deltas quickly enough for daily iteration.
- Scenarios and result artifacts are reusable across agent variants.
- Quality, safety, autonomy, containment, cost, and latency are evaluated
  together.
- Individual production failures can be replayed without repeating production
  writes.
- Every result identifies the candidate and exact artifacts that influenced it.
- Trends show whether the system is becoming better, cheaper, faster, and safer.
- Promotion is blocked when a required gate fails or evidence is incomplete.
- Experiments can be created without application teams rebuilding the runner.

---

## 5. Replay Is Resimulation, Not Event Playback

A trace contains what happened under one configuration. Playing its events back
does not reveal how a new prompt, context policy, model, toolset, or workflow
would behave.

The experiment runner must instead freeze inputs at declared boundaries and let
the candidate recompute decisions:

```text
recorded request
  + frozen or simulated external observations
  + candidate configuration
                    │
                    ▼
          candidate executes anew
                    │
                    ▼
       new trajectory and outcome
                    │
                    ▼
      independent scoring and comparison
```

The source trace is provenance and scenario material. It is not the trajectory
being scored for the challenger.

---

## 6. Replay Modes

Every experiment must declare its replay mode. There is no implicit permission
to invoke external systems.

### 6.1 `frozen`

Recorded external observations and tool results are supplied to the candidate as
immutable fixtures.

Use for:

- controlled prompt comparisons;
- model comparisons;
- context-assembly comparisons over a fixed candidate corpus;
- deterministic CI;
- reproduction of known failures.

Properties:

- no network;
- no real side effects;
- strongest candidate-to-candidate comparability;
- cannot measure behavior under current external drift.

### 6.2 `simulated`

Tools execute against deterministic simulators or disposable fixtures. Writes
are allowed only inside the simulator.

Use for:

- tool selection and argument evaluation;
- approval behavior;
- retry and recovery testing;
- multi-step state transitions;
- destructive-action safety scenarios.

Properties:

- controlled mutable state;
- seeded execution;
- no production effects;
- simulator fidelity must be reported as a threat to validity.

### 6.3 `shadow`

Explicitly allowlisted read-only adapters may query current systems. Proposed
writes are recorded as intents but never dispatched.

Use for:

- retrieval and data drift;
- current latency and cost measurement;
- shadow evaluation before promotion.

Properties:

- may require network and credentials;
- is never part of the dependency-free default path;
- results may be non-deterministic;
- all external reads and versions must be recorded;
- writes remain prohibited.

### 6.4 Production writes

Repeating production side effects is out of scope and denied by default. A
future production experimentation system would require separate authorization,
traffic isolation, remote idempotency, reconciliation, and rollback contracts.
This proposal does not grant that authority.

---

## 7. Core Contracts

The first implementation should use versioned, serializable contracts rather
than importing application-specific prompt, model, or workflow objects.

### 7.1 `CandidateRef`

```python
@dataclass(frozen=True)
class CandidateRef:
    candidate_id: str
    prompt_ref: str
    context_policy_ref: str
    model_ref: str
    toolset_ref: str
    code_ref: str
    config_digest: str
    metadata: dict[str, str] = field(default_factory=dict)
```

Every mutable dimension must be explicit. A result associated only with a label
such as `candidate-7` is not reproducible.

### 7.2 `ReplayScenario`

```python
@dataclass(frozen=True)
class ReplayScenario:
    scenario_id: str
    schema_version: int
    source_trace_ref: str
    input_ref: str
    observation_fixture_ref: str
    expected_ref: str
    split: str
    tags: tuple[str, ...]
    content_digest: str
```

`split` uses the closed vocabulary:

```text
train | validation | holdout | audit
```

The scenario may persist digests and references rather than raw sensitive
content. The runner resolves raw fixtures only through an application-provided
scenario adapter with an explicit data-access boundary.

### 7.3 `ExperimentSpec`

```python
@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    baseline: CandidateRef
    challengers: tuple[CandidateRef, ...]
    scenario_manifest_ref: str
    replay_mode: str
    scorer_manifest_ref: str
    promotion_policy_ref: str
    seed: int
    max_concurrency: int
    budget_usd: float | None
```

### 7.4 `CandidateRun`

```python
@dataclass(frozen=True)
class CandidateRun:
    run_id: str
    experiment_id: str
    scenario_id: str
    candidate_id: str
    status: str
    trace_ref: str | None
    output_ref: str | None
    cost_usd: float | None
    latency_ms: int | None
    evidence_refs: tuple[str, ...]
```

Candidate run status uses:

```text
pending | running | completed | failed | blocked | incomplete
```

### 7.5 `CandidateComparison`

```python
@dataclass(frozen=True)
class CandidateComparison:
    candidate_id: str
    baseline_id: str
    fitness: dict[str, float]
    deltas: dict[str, float]
    hard_gate_status: str
    slice_results: dict[str, dict[str, float]]
    evidence_refs: tuple[str, ...]
```

### 7.6 `PromotionDecision`

```python
@dataclass(frozen=True)
class PromotionDecision:
    experiment_id: str
    candidate_id: str
    disposition: str
    reason_codes: tuple[str, ...]
    gate_report_ref: str
    comparison_ref: str
```

Disposition uses:

```text
promote | reject | hold
```

`hold` means evidence is missing or unverifiable. It must never be interpreted
as a pass.

---

## 8. Fitness and Promotion

The experiment layer should produce a fitness vector, not silently collapse all
behavior into a single score.

### 8.1 Optimization objectives

Typical objectives include:

- task success;
- answer or action correctness;
- groundedness;
- trajectory quality;
- context precision and recall;
- appropriate autonomy;
- cost per successful outcome;
- latency;
- tool-call efficiency;
- recovery success.

### 8.2 Hard constraints

Typical non-tradeable gates include:

- unsafe delivery;
- authority or tool-policy violation;
- approval bypass;
- uncontained write;
- prompt-injection success;
- duplicate side effect;
- missing required trace evidence;
- evaluator failure;
- unacceptable subgroup or scenario-slice regression.

An increase in task quality must not compensate for a hard safety failure.

### 8.3 Selection

The external optimizer may choose:

- Pareto ranking;
- a declared weighted objective;
- constrained optimization;
- lexicographic ordering;
- manual review.

The chosen selection policy must be versioned and included in the promotion
evidence. DurableFlow should not embed one permanent definition of "best."

---

## 9. Dataset Discipline

Replayable traces create an overfitting risk, especially when an optimizer can
inspect repeated failures.

The extension must distinguish:

- `train`: visible to the optimizer and usable for candidate generation;
- `validation`: used for iteration decisions but not direct mutation input;
- `holdout`: used only for final candidate comparison;
- `audit`: fixed human or independent-oracle anchors.

Required safeguards:

1. Prevent the optimizer from reading holdout expected outputs.
2. Record scenario lineage and deduplicate semantically equivalent traces across
   splits.
3. Gate on meaningful slices, not aggregate score alone.
4. Preserve failed and negative-result artifacts.
5. Report the number of candidate-selection rounds performed against each split.
6. Require a fresh or rotated holdout when repeated selection has exhausted its
   evidentiary value.

---

## 10. Proposed Package Layout

```text
durableflow/
  experiments/
    __init__.py
    models.py          # contracts in §7
    capture.py         # completed trace → ReplayScenario
    fixtures.py        # frozen/simulated observation boundary
    adapters.py        # candidate execution protocols
    runner.py          # durable scenario × candidate matrix
    comparison.py      # baseline deltas and slice aggregation
    promotion.py       # promote/reject/hold policy
    store.py           # experiment-owned SQLite tables
    cli.py             # capture, run, compare, promote
    view.py            # operator-facing view models
    render.py          # CLI and markdown output
  examples/
    experiment_replay_demo.py
  tests/
    test_experiment_*.py
  docs/
    experiment-replay-extension.md
```

The extension should sit beside `evals/`, not inside `src/`. The core engine
stays a small macro-step runner. Experiment iteration, candidate matrices, and
selection are extension-owned state machines.

---

## 11. Execution Protocol

For each `scenario × candidate` cell:

1. Resolve and verify the scenario content digest.
2. Resolve and verify every candidate artifact reference.
3. Construct an isolated run namespace and deterministic seed.
4. Bind the declared replay adapter.
5. Execute the candidate workflow from the scenario input.
6. Intercept external calls according to replay mode.
7. Persist checkpoints, trace events, context lineage, costs, and failures.
8. Normalize the completed execution into an `EvalCase`.
9. Run the scorer manifest through `evals/`.
10. Persist the per-cell gate report.

After all required cells finish:

1. Compare each challenger with the baseline on paired scenarios.
2. Calculate metric deltas and uncertainty appropriate to the sample.
3. Evaluate hard constraints and required slices.
4. Emit `CandidateComparison` artifacts.
5. Apply the versioned promotion policy.
6. Emit a verdict-first experiment report and `PromotionDecision`.

Incomplete required cells produce `hold`, not promotion.

---

## 12. Adapter Interfaces

The reference implementation should avoid assuming one agent framework.

```python
class CandidateRunner(Protocol):
    def run(
        self,
        *,
        scenario: ReplayScenario,
        candidate: CandidateRef,
        environment: ReplayEnvironment,
        seed: int,
    ) -> CandidateRun:
        ...


class ReplayEnvironment(Protocol):
    mode: str

    def invoke_tool(self, name: str, arguments: dict) -> dict:
        ...


class ArtifactResolver(Protocol):
    def resolve(self, ref: str, expected_digest: str | None = None) -> bytes:
        ...
```

The default examples should use deterministic local adapters. Optional live
providers and external evaluation services remain lazy-imported integrations.

---

## 13. Privacy and Evidence

This extension must preserve DurableFlow's existing privacy boundary:

- persisted scenario manifests use references and digests by default;
- raw prompts, model responses, and customer records are not embedded in gate
  reports;
- equality digests are not described as anonymization;
- application adapters control access to replayable raw fixtures;
- export is opt-in and cannot affect the local verdict;
- evidence reports identify the exact candidate, scenario, scorer, and adapter
  versions used.

Replayability and default redaction are in tension. A digest-only `EvalCase`
cannot by itself resimulate a workflow. `ReplayScenario` therefore separates the
portable manifest from the protected fixture store. The manifest is safe to
inspect; the resolver boundary controls access to the material required to run
the experiment.

---

## 14. CLI Shape

The intended operator flow:

```bash
python -m experiments.cli capture \
  --db workflow.sqlite \
  --workflow-id wf-123 \
  --scenario-out scenarios/failure-123.json

python -m experiments.cli run \
  --experiment experiments/prompt-generation-12.json \
  --out artifacts/experiments/prompt-generation-12/

python -m experiments.cli compare \
  --experiment-run artifacts/experiments/prompt-generation-12/run.json \
  --out artifacts/experiments/prompt-generation-12/comparison.json

python -m experiments.cli promote \
  --comparison artifacts/experiments/prompt-generation-12/comparison.json \
  --policy promotion-policy.json \
  --ci
```

CI exit codes should follow the existing eval-gate vocabulary:

```text
0 = promote
1 = reject
2 = hold or invalid/incomplete evidence
```

---

## 15. Initial Demonstration

The smallest credible demo should compare:

- one baseline candidate;
- two challenger candidates;
- a small versioned scenario set containing a success, a known failure, an
  approval case, and a tool failure;
- prompt, context-policy, and model-reference changes;
- frozen and simulated replay modes;
- trajectory, safety, cost, and latency scorers;
- one challenger that improves task quality but violates a hard gate;
- one challenger that is safe but inconclusive due to missing evidence.

Expected report behavior:

```text
Candidate A: REJECT
  quality: +8 points
  cost: -4%
  blocker: approval boundary regression

Candidate B: HOLD
  quality: +3 points
  blocker: required tool-verification evidence missing

Promotion decision: no candidate promoted
```

This demonstrates why a scalar score is insufficient and why incomplete
evidence must remain distinct from failure.

---

## 16. Implementation Phases

### Phase 0 — Contract freeze

- Define the contracts in §7.
- Define replay-mode vocabulary and side-effect invariants.
- Define adapter interfaces.
- Define scenario split rules.
- Specify evidence and redaction requirements.

### Phase 1 — Frozen replay

- Capture completed runs as scenario manifests plus protected fixtures.
- Implement a deterministic local candidate adapter.
- Run a baseline and challengers against frozen observations.
- Convert new executions into existing `EvalCase` artifacts.
- Reuse existing eval scorers and gate aggregation.

### Phase 2 — Comparison and promotion

- Add paired baseline deltas.
- Add metric vectors and slice results.
- Implement promote/reject/hold policies.
- Render verdict-first reports.
- Add deterministic CI exit behavior.

### Phase 3 — Simulated tools and recovery

- Add seeded tool simulators.
- Test approval, write, retry, crash, and recovery trajectories.
- Prove no production write path is reachable.

### Phase 4 — Optimizer integration

- Expose a stable result artifact/API for external optimizers.
- Demonstrate a small mutation loop without making the mutation strategy core.
- Enforce train/validation/holdout isolation.

### Phase 5 — Optional shadow and distributed execution

- Add explicitly gated read-only shadow adapters.
- Integrate large experiment matrices with Colony.
- Measure sub-hour feedback and interruption recovery.

---

## 17. Acceptance Criteria

Before the extension may be described as implemented:

1. A completed workflow can be captured as a digest-verified replay scenario.
2. The same scenario can execute against at least two distinct candidates.
3. The challenger produces a new trace rather than reusing the source trace's
   decisions.
4. Frozen mode performs no network calls or real side effects.
5. Simulated mode cannot reach a production tool adapter.
6. Candidate and scenario identity are present in every run and result artifact.
7. An interrupted experiment resumes without rerunning completed cells.
8. Candidate outputs flow through the existing eval gate.
9. Baseline deltas are paired by scenario.
10. A hard safety failure cannot be offset by higher aggregate quality.
11. Missing required evidence yields `hold`, never `promote`.
12. Reports cite inspectable evidence paths and content digests.
13. Holdout expected outputs are inaccessible through the optimizer interface.
14. Core tests remain standard-library-only, deterministic, offline, and free
    of optional SDK imports.

---

## 18. Risks

| Risk | Consequence | Mitigation |
|---|---|---|
| Trace playback is mistaken for resimulation | Candidate changes appear tested without recomputing decisions. | Require a new candidate trace and distinguish source trace from candidate run. |
| Production writes are replayed | Duplicate or harmful external effects. | Default-deny tool boundary; frozen/simulated modes only in the initial implementation. |
| Optimizer overfits golden traces | Reported improvement does not generalize. | Enforced splits, audit anchors, selection-round accounting, holdout rotation. |
| One scalar hides safety regressions | Unsafe candidate wins on aggregate fitness. | Fitness vector plus non-tradeable hard gates. |
| Digest-only artifacts cannot be replayed | Reproduction silently depends on unavailable data. | Separate scenario manifest from protected fixture resolver; report resolvability. |
| Simulator differs from production | Candidate passes unrealistic tool behavior. | Report simulator version and fidelity limits; use gated shadow reads for drift checks. |
| Extension expands DurableFlow beyond its educational scope | Repo becomes a partial hosted eval platform. | Keep the first implementation local, stdlib-only, inspectable, and adapter-driven. |
| Eval and optimizer become self-referential | Search exploits scorer defects. | Keep optimizer external; retain audit cases and independent evaluators. |

---

## 19. Landscape and Alternatives

The ecosystem contains several tools addressing parts of the experiment, evaluation, and durability lifecycle, but none package this complete trace-to-resimulation hill-climbing loop as a single governed control plane:

| Category / Product | What it packages | Key differences from DurableFlow Experiment Replay |
|---|---|---|
| **Trace-to-Eval Platforms**<br>*(Braintrust, LangSmith, Langfuse, Arize Phoenix, Opik)* | Production trace capture, dataset curation, candidate evaluation runs, and trend reporting. | They run evaluations over trace outputs or re-execute candidate chains directly, but lack built-in **side-effect containment** (frozen/simulated tool boundaries), context-credit lineage, and non-tradeable hard safety gates. |
| **Automated Optimizers**<br>*(DSPy)* | Automated prompt and weight hill-climbing optimization loops driven by metric functions. | DSPy is an offline pipeline compiler. It does not own production trace ingestion, durable state recovery, side-effect isolation, or enterprise release governance. |
| **Durable Infrastructure**<br>*(Temporal, Restate, LangGraph Platform)* | State durability, checkpointing, retries, time-travel debugging, and workflow execution. | Temporal and Restate offer generic durability without agent-native eval gating or candidate comparison. LangGraph offers state graph checkpoints, but leaves side-effect replay isolation and promotion gating to external tooling. |

### Architectural Positioning

DurableFlow does not aim to replace these specialized systems in production. Instead, it provides a compact, dependency-free reference implementation that unifies:

1. **Trace capture $\rightarrow$ isolated resimulation** (frozen/simulated modes so production failures replay without uncontained side effects).
2. **Multi-dimensional fitness vectors** with non-tradeable hard gates (ensuring safety/containment failures cannot be offset by higher quality scores).
3. **Context lineage and credit assignment** (tracking what was observed, selected, consumed, and credited).
4. **Eval-gated promotion** as a first-class workflow decision artifact.

---

## 20. Open Decisions

1. Should experiment state use a separate SQLite database or experiment-owned
   tables in an existing workflow store?
2. What is the minimum raw fixture format required for useful frozen replay
   while preserving the privacy boundary?
3. Should `ReplayScenario` extend `EvalCase`, reference it, or remain a separate
   artifact joined by provenance?
4. Which statistical comparison is required for the first demo: paired deltas
   only, bootstrap intervals, or a fixed minimum-effect gate?
5. How should context-policy candidates reference selector code and corpus/index
   snapshots without copying application data into DurableFlow?
6. Which trajectory-eval proposal fields must land before replay capture can be
   considered sufficiently faithful?

---

## 21. Bottom Line

DurableFlow already records durable execution, context lineage, cost, approvals,
and eval-gate evidence. The missing hill-climbing primitive is the ability to
take a recorded scenario, rerun it under a versioned candidate configuration,
and compare the resulting execution with the baseline.

That capability should be a sibling `experiments/` extension:

```text
DurableFlow records and resimulates
evals scores and gates
context explains information use
external optimizers propose the next candidates
```

This closes the trace-to-improvement loop without turning the durable runtime
into a genetic optimizer or allowing evaluation replay to widen production
authority.


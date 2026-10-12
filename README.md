
# Agent Workflow Runtime

Most agent demos optimize for intelligence. This repository is a small educational lab for the operational primitives that make agentic workflows survivable: crashes, approvals, model fallback, cost pressure, context limits, side effects, and unreliable compute.

**For:** Backend engineers and infrastructure-minded AI teams who want to inspect the mechanics underneath production agent platforms, not prompt engineering or RAG tutorials.

In production, use established tools such as Temporal, LangGraph, LiteLLM, and LangSmith. This repository strips the core ideas down to local SQLite, standard Python, deterministic fixtures, and tests you can read in one sitting.

The project includes four extension tracks:

| Extension | Status | What it demonstrates |
|-----------|--------|----------------------|
| Colony | Implemented benchmark | Durable execution can turn spot-like compute into completable long-running work, measured against a naive baseline under the same seeded loss schedule. |
| Agent Readiness Pack | Implemented demo | A readiness harness for deciding whether an agent is deployable: durable turns, gated writes, failure injection, and a verdict-first report. |
| Context | Implemented MVP | Durable information lineage: what was observed, selected, consumed by model steps, and explicitly credited as influential. |
| Target Planner | Draft spec | Budgeted, local-first target selection with verifiable escalation across local and cloud tiers. |

## Quick Start

Requires **Python 3.11+** on macOS or Linux. No API keys required.

Run these commands from the repository root.

```bash
./start.sh crash     # crash recovery demo
./start.sh test      # full test suite
./start.sh inbox     # interactive approval demo
./start.sh context   # inbox triage plus context audit trace
./start.sh readiness # agent readiness report
./start.sh mcp       # gated write over MCP CRM server
```

Or without `start.sh`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python examples/crash_resume_demo.py
pytest tests/ -v
```

After the demos, work through `docs/workshop/README.md` or `docs/exercises.md` for guided tasks involving SQLite, model fallback, and workflow extensions.

## What This Is

A minimal Python runtime for multi-step LLM and agentic workflows.

It demonstrates:

- **Durable execution:** SQLite checkpoints after every step; resume from the last completed step.
- **Crash recovery:** Real process termination using `os._exit` in a subprocess.
- **Approval gates:** Pause until an operator approves or rejects; decisions persist across restarts.
- **Model routing:** Primary/secondary fallback with per-step USD cost accounting.
- **Context selection:** TF-IDF ranking under a caller-supplied hard token budget.
- **Replay suppression:** Deterministic keys allow the side-effect log to reuse mock-send results.

It is not another assistant framework. It is the small operational layer underneath one.

Architecture documentation is available in:

- `docs/dflow-arch.md`
- `docs/walkthrough.md`

## Extension: Colony

**Turning spot-like compute into completable work — measured.**

Colony is a benchmark layer on top of the runtime.

It compares a naive retry runner against a durable runner under identical seeded loss schedules.

It measures:

- Completion rates
- Execution costs
- Wall-clock time
- Recovery attempts
- Human interventions

Run the benchmark:

```bash
python3 examples/chaos_benchmark_demo.py
```

### Benchmark Results

Current hostile-profile mock result:

```text
=== RESULT mode=mock profile=hostile seed=1337 ===

                  completion   cost     wall    recoveries  interventions

naive                90%     $0.23     701s        --            --
dflow-vast          100%     $0.23     689s        10             0

completion delta: +10 pts
cost delta: +0.00

under identical loss schedule (seed 1337)
```

This benchmark demonstrates whether long-running workflows can survive failures commonly associated with unreliable or spot-priced compute.

The workload includes 20 small toy retrieval/model evaluation jobs.

Each job contains five durable stages:

1. Setup
2. Data loading
3. Inference and evaluation
4. Metrics writing
5. Artifact uploading

Mock mode requires no external account.

A gated live smoke-test path is available using `--live` and `VAST_API_KEY`.

Additional documentation:

- `colony/README.md`
- `docs/colony-methodology.md`

## Extension: Agent Readiness Pack

**A deployment-readiness layer for agentic workflows.**

The Agent Readiness Pack wraps a reason-act-observe agent.

Every turn is checkpointed, and external writes are idempotent and approval-gated.

The harness evaluates six production failure modes.

Run:

```bash
python3 examples/readiness_demo.py
```

### Example Readiness Report

```text
VERDICT: Ship

The runtime-wrapped agent survived the readiness scenarios.

                         NAKED      WRAPPED    DELTA

Safety                     0/100      100/100    +100
Reliability                0/100      100/100    +100
Cost                       0/100      100/100    +100
Observability             10/100      100/100     +90

----------------------------------------------------

OVERALL READINESS          0/100      100/100    +100
```

These scores are generated from deterministic local fixtures.

They demonstrate evaluation structure and failure-mode coverage rather than guaranteeing production safety.

### Failure Scenarios

- Tool timeout
- Malformed tool output
- Prompt injection
- Context overflow
- Model fallback
- Crash after side effect

The report prioritizes:

- Deployment verdict
- Durability improvements
- Blocking readiness conditions
- Failure-mode coverage

Generated artifacts:

```text
readiness.json
readiness_report.md
```

The MCP path uses the `mcp==1.13.1` client/server protocol when installed.

A minimal stdio JSON fallback keeps the demo dependency-free.

The ADK integration currently validates adapter compatibility using `google-adk==1.18.0`, including:

- Agent object construction
- History conversion
- Adapter imports
- Resume-safe mock execution

Full Google ADK Runner end-to-end execution is not yet implemented.

Documentation:

- `readiness/README.md`
- `readiness/docs/dflow-readiness-spec.md`

## Extension: Target Planner

**Budgeted, local-first target selection with verifiable escalation.**

Target Planner is a draft extension implemented under `planner/`.

It is designed as an OpenAI-compatible proxy that accepts:

```json
{
  "model": "auto"
}
```

Alongside declarative constraints for:

- Budget
- Privacy
- Latency
- Execution tiers
- Target availability

The planner selects an ordered execution plan and records each attempt as a durable outcome.

Explicit model names bypass automatic target selection.

### Design Goals

The planner reuses SQLite checkpointing and cost-accounted model routing.

Additional state includes:

- Target definitions
- Planning traces
- Target statistics
- Execution outcomes
- Session budgets

Escalation depends on verifiable outcomes:

- Successful transport
- Latency within budget
- Caller-supplied output checks

The planner does not claim to predict model answer quality.

Specification:

`planner/planner-spec.md`

## Extension: Context

**Durable information state alongside durable execution state.**

Context adds an information lineage ledger to the inbox triage workflow.

It tracks what information was:

- Observed
- Retrieved
- Selected
- Consumed
- Credited as influential

### Run the Demo

```bash
python3 examples/inbox_triage_context_demo.py
```

Audit workflow state:

```bash
python3 -m context.cli audit --db examples/inbox_triage_context_demo.sqlite --workflow-id wf-context-demo
```

### Assembly Lineage

Version 0.2a introduces assembly lineage.

It records retrieved and rejected events showing how candidate information competes for limited context budgets.

It also provides metadata validation and audit summary counts.

By default, the ledger stores:

- Digests
- Source references
- Selection metadata

It does not store raw email bodies, prompts, or model responses by default.

Planned capabilities include:

- Supersession labeling
- Context replay
- Per-artifact retrieval inspection

Documentation:

- `context/README.md`
- `docs/context-extension.md`

## Architecture Notes: Scaling LLM-Powered Assistants

The first version of an assistant typically succeeds because the workflow is narrow:

1. Receive a request.
2. Construct a prompt.
3. Call a model.
4. Return a response.

Operational difficulties appear when assistants interact with real inboxes, calendars, CRMs, repositories, and long-running tasks.

### 1. Context Growth

Real assistants accumulate large amounts of information over time.

The key challenge becomes selecting relevant information while excluding unnecessary context.

This implementation uses:

- TF-IDF ranking
- Greedy budget packing
- Hard token limits
- Lightweight retrieval logic

Embeddings are intentionally avoided so the selection behavior remains inspectable.

### 2. Partial Failure

Agent workflows depend on external services that can fail unexpectedly.

These include:

- Model providers
- APIs
- Databases
- Queues
- User approval systems

SQLite checkpoints preserve completed workflow steps.

If execution crashes, the workflow resumes from its last durable checkpoint.

### 3. Cost Control

Autonomous execution increases model inference volume.

Cost accounting should operate at the workflow and step level.

The model router estimates costs using:

- Input tokens
- Output tokens
- Model-specific pricing
- Per-step execution records

This creates a more inspectable cost model.

### 4. Human Approval

Some assistant actions require explicit approval.

Examples include:

- Sending emails
- Modifying schedules
- Making commitments
- Exposing sensitive information
- Writing to external systems

Approval gates persist pending decisions until an operator approves or rejects them.

This supports durable interruption but does not replace authorization or security controls.

### 5. Observability

Important runtime events include:

- Model fallback
- Approval decisions
- Process crashes
- Workflow recovery
- Skipped side effects
- Workflow completion

The telemetry system records JSON-line events for auditing and debugging.

Production-scale systems also need governance over what autonomous workflows may access, modify, or reveal.

## Repository Structure

```text
project/
  LICENSE
  README.md
  CONTRIBUTING.md
  CHANGELOG.md
  pyproject.toml
  start.sh

  docs/
    README.md
    exercises.md
    dflow-arch.md
    dflow-spec.md
    colony-methodology.md

  src/
    engine.py
    store.py
    workflows.py
    model_router.py
    context_selector.py
    approval.py
    telemetry.py

  examples/
    inbox_triage_demo.py
    crash_resume_demo.py
    chaos_benchmark_demo.py
    single_eviction_demo.py
    readiness_demo.py
    mcp_demo.py

  agent/
    protocol.py
    runner.py
    mini_react.py
    tools.py
    mcp_client.py
    adk_adapter.py

  colony/
    README.md
    colony-spec.md
    benchmark.py
    controller.py
    provider.py

  readiness/
    README.md
    harness.py
    scoring.py
    view.py
    vocabulary.py
    render.py

    docs/
      dflow-readiness-spec.md

  planner/
    planner-spec.md

  mcp_server/
    legacy_crm.py

  data/
    mock_emails.json
    mock_calendar.json
    chaos_profiles.json

  tests/
    test_*.py
```

## Design Decisions

### SQLite for Durable State

SQLite keeps workflow persistence local and inspectable.

A production service could use Postgres, Temporal, or another durable execution framework.

For educational demonstrations, SQLite provides sufficient visibility into checkpoints, approvals, and side-effect logs.

### TF-IDF for Context Selection

TF-IDF is intentionally used instead of embedding-based retrieval.

The purpose is to expose context selection behavior rather than maximize semantic retrieval quality.

The selector enforces a hard token budget.

### Mock Providers by Default

Mock providers allow demonstrations and tests to run without external accounts.

Optional Anthropic integration uses:

```text
ANTHROPIC_API_KEY
```

And the `providers` dependency extra.

### Idempotent Side Effects

Mock sends use deterministic idempotency keys.

The runtime checks the side-effect log before persisting a new mock result.

This demonstrates local replay suppression.

It does not guarantee exactly-once delivery to external services.

Production integrations require remote idempotency support or an outbox and reconciliation design.

### Approximate Token Counting

Token counts are estimated using:

```text
Whitespace word count / 0.75
```

Production implementations should use a tokenizer matched to the target model.

### Python Imports

The Python package lives under `src/`.

Example:

```python
from src.engine import WorkflowEngine
```

Demo scripts add the repository root to `PYTHONPATH`.

See `start.sh` for execution configuration.

## Positioning and Primitives

This project is an educational reference implementation and stress-test sandbox.

It is not intended to replace established production agent platforms.

The primary goal is to isolate and demonstrate operational mechanics.

### Durable Execution

Production orchestration platforms provide distributed execution, persistence, and recovery.

This project focuses on demonstrating those mechanisms locally using Python and SQLite.

### Agent Orchestration

Frameworks such as LangGraph and CrewAI support complex agent graphs, reasoning loops, state management, and human-in-the-loop interactions.

This implementation focuses on:

- Checkpoint persistence
- Approval interruption
- Crash recovery
- Model fallback
- Replay suppression
- Failure injection

### Observability

Platforms such as LangSmith and Arize Phoenix provide tracing and evaluation infrastructure.

This project focuses on the runtime events that produce those traces.

## Production Recommendations

For production deployments:

- Use Temporal or an equivalent orchestrator for durable execution.
- Use LangGraph or LlamaIndex Workflows for workflow orchestration.
- Use LiteLLM or Portkey for model routing and cost management.
- Use LangSmith for tracing and evaluation.
- Use proper authorization for external actions.
- Implement durable side-effect handling.
- Monitor workflow costs and operational failures.
- Validate deployment readiness before rollout.

## Contributing

Bug fixes, exercises, tests, and documentation improvements are welcome.

See `CONTRIBUTING.md` for contribution guidelines.

## License

MIT License.

See `LICENSE` for details.

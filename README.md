# DurableFlow

Most agent demos optimize for intelligence. DurableFlow is a small educational lab for the operational primitives that make agentic workflows survivable: crashes, approvals, model fallback, cost pressure, context limits, side effects, and unreliable compute.

**For:** backend engineers and infrastructure-minded AI teams who want to inspect the mechanics underneath production agent platforms, not prompt engineering or RAG tutorials.

In production, use established tools such as Temporal, LangGraph, LiteLLM, and LangSmith. This repo exists because those tools are intentionally large and capable; DurableFlow strips the core ideas down to local SQLite, standard Python, deterministic fixtures, and tests you can read in one sitting.

DurableFlow now has three extension tracks:

| Extension | Status | What it demonstrates |
|-----------|--------|----------------------|
| [Colony](colony/README.md) | Implemented benchmark | Durable execution can turn spot-like compute into completable long-running work, measured against a naive baseline under the same seeded loss schedule. |
| [Agent Readiness Pack](readiness/README.md) | Implemented demo | A readiness harness shape for deciding whether an agent is deployable: durable turns, gated writes, failure injection, and a verdict-first report. |
| [Target Planner](planner/planner-spec.md) | Draft spec | Budgeted, local-first target selection with verifiable escalation across local and cloud tiers. |

## Quick start

Requires **Python 3.11+** on macOS or Linux. No API keys required.

```bash
git clone https://github.com/marcospolanco/durableflow.git
cd durableflow
./start.sh crash     # crash recovery demo (start here)
./start.sh test      # full test suite
./start.sh inbox     # interactive approval demo
./start.sh readiness # agent readiness before/after report
./start.sh mcp       # gated write over MCP CRM server
```

Or without `start.sh`:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python examples/crash_resume_demo.py
pytest tests/ -v
```

After the demos, work through **[docs/exercises.md](docs/exercises.md)** — guided tasks for inspecting SQLite, forcing fallback, and extending the workflow.

## What this is

A minimal Python runtime for multi-step LLM and agentic workflows. It demonstrates:

- **Durable execution** — SQLite checkpoint after every step; resume from last completed step
- **Crash recovery** — real process kill (`os._exit`) in a subprocess, not mocked exceptions
- **Approval gates** — pause until an operator approves or rejects; persists across restart
- **Model routing** — primary/secondary fallback with per-step USD cost accounting
- **Context selection** — TF-IDF ranking under a hard token budget (4096 in inbox triage)
- **Idempotency** — side-effect log prevents duplicate send on crash/retry

It is not another assistant framework. It is the small operational layer underneath one.

See **[docs/dflow-arch.md](docs/dflow-arch.md)** for diagrams and invariants.

## Extension: Colony

**Turning spot-like compute into completable work -- measured.**

Colony is a benchmark layer on top of DurableFlow. It compares a naive retry runner against a durable runner under the identical seeded loss schedule and reports completion, cost, wall-clock, recoveries, and human interventions.

```bash
python3 examples/chaos_benchmark_demo.py
```

Current hostile-profile mock result:

```text
=== RESULT mode=mock profile=hostile seed=1337 ===
                  completion   cost     wall    recoveries  interventions
naive                90%     $ 0.23     701s        --            --
dflow-vast          100%     $ 0.23     689s        10             0

completion delta: +10 pts     cost delta: +0.00   under identical loss schedule (seed 1337)
```

This is not a claim that Vast instances are unreliable; it is a benchmark of whether long-running work can survive the class of failures that any spot-priced heterogeneous compute marketplace must handle.

The workload is 20 small toy retrieval/model eval jobs, each with five durable stages: setup, data load, inference/eval shard, metrics write, and artifact upload. Mock mode requires no account. A gated live smoke path is available with `--live` and `VAST_API_KEY`.

Start with **[colony/README.md](colony/README.md)**, then read **[docs/colony-methodology.md](docs/colony-methodology.md)** for the protocol, assumptions, and threats to validity.

## Extension: Agent Readiness Pack

**A deployment-readiness layer for agentic workflows.**

The Agent Readiness Pack wraps a reason-act-observe agent so every turn is checkpointed, every external write is idempotent and approval-gated, and six production failure modes are tested before deployment:

```bash
python3 examples/readiness_demo.py
```

Current demo result:

```text
VERDICT: Ship: the DurableFlow-wrapped agent survived the readiness scenarios.

                         NAKED      WRAPPED    DELTA
Safety                     0 / 100  100 / 100  +100
Reliability                0 / 100  100 / 100  +100
Cost                       0 / 100  100 / 100  +100
Observability             10 / 100  100 / 100   +90
-------------------------------------------------------
OVERALL READINESS          0 / 100  100 / 100  +100
```

These scores come from deterministic local fixtures. The point is the evaluation shape and failure-mode coverage, not the absolute score.

- tool timeout
- malformed tool output
- prompt injection
- context overflow
- model fallback
- crash after side effect

The report is intentionally verdict-first: "ship" or "do not ship," the durability delta, and the single unsafe behavior that blocks deployment. The demo writes `readiness.json` and `readiness_report.md`.

The MCP path uses the official `mcp==1.13.1` client/server protocol when the optional package is installed, and falls back to a tiny stdio JSON protocol so the demo remains dependency-free. The ADK path is currently an adapter boundary: it verifies `google-adk==1.18.0` import, ADK `Agent` object construction, history conversion, and resume-safe behavior with an ADK-compatible mock. It does not yet claim real Google ADK Runner end-to-end execution.

Start with **[readiness/README.md](readiness/README.md)** for the implementation map, scenarios, and build contract. The full spec remains at **[readiness/docs/dflow-readiness-spec.md](readiness/docs/dflow-readiness-spec.md)**.

## Extension: Target Planner

**Budgeted, local-first target selection with verifiable escalation.**

Target Planner is a draft sibling extension, implemented under `planner/`. It is scoped as an OpenAI-compatible proxy that accepts `"model": "auto"` plus declarative constraints, selects an ordered target plan under budget, privacy, latency, and tier constraints, then records each attempt as a durable outcome. Explicit model names bypass the target planner.

The intended implementation reuses DurableFlow's SQLite-backed checkpoint store and cost-accounted model routing patterns, but adds target-planner-owned tables for targets, plan traces, target statistics, outcomes, and session budgets. Escalation is based on verifiable outcomes only: transport success, latency within budget, and optional caller-supplied output checks. It does not claim to predict answer quality.

Read **[planner/planner-spec.md](planner/planner-spec.md)** for the draft contract and implementation gates.

## Architecture notes: scaling LLM-powered assistants

The first version of an assistant usually succeeds because the workflow is narrow: one user request, one prompt, one model call, one response. The operational problems appear when that assistant starts running long-lived routines against real inboxes, calendars, CRMs, codebases, or ticket queues.

The first scaling problem is context growth. A small hand-picked prompt can carry the right background. A real assistant accumulates years of messages, events, preferences, documents, and prior actions. At that point, the question is no longer "can we fit context into the model?" It is "which context should be selected, and what do we exclude?" This prototype uses basic TF-IDF plus greedy budget packing, deliberately avoiding embeddings so the retrieval and budget behavior are visible in a few lines of code.

The second problem is partial failure. Assistant workflows depend on model providers, APIs, queues, databases, and user approvals. Any of those can fail after earlier steps have succeeded. The runtime checkpoints after each completed step in SQLite, so a process crash during a model call resumes from the last durable checkpoint instead of replaying the whole workflow.

The third problem is cost control. Autonomous mode increases inference volume because the system starts making calls in the background. Cost accounting has to be per workflow and per step, not a monthly surprise. The model router computes cost from estimated input and output tokens using model-specific pricing and records the model used for each call.

The fourth problem is human approval latency. Many useful assistant actions are not safe to execute automatically: sending email, rescheduling meetings, making commitments, or exposing sensitive context. The approval gate here persists a pending decision and pauses the workflow until an operator approves or rejects it. That is a small mechanism, but it changes the system from "agent loop" to "controlled execution."

The fifth problem is observability across non-deterministic paths. Model fallback, user rejection, crash recovery, and skipped side effects are all meaningful events. The telemetry logger writes JSON lines for steps, approvals, crashes, fallback, and workflow completion so the path can be audited after the run.

Public evidence suggests this class of problem is becoming more important across assistant products: platform docs increasingly emphasize [tool use](https://developers.openai.com/api/docs/guides/tools), [background execution](https://developers.openai.com/api/docs/guides/background), [agent observability](https://developers.openai.com/api/docs/agents-sdk/integrations-and-observability), [workflow evaluation](https://developers.openai.com/api/docs/guides/evals), and [cost optimization](https://developers.openai.com/api/docs/guides/cost-optimization). At scale, the missing layer is governance: what is each workflow authorized to negotiate, commit, or reveal? That is a separate and harder problem.

## Repo structure

```text
durableflow/
  LICENSE
  README.md
  CONTRIBUTING.md
  CHANGELOG.md
  pyproject.toml
  start.sh
  docs/
    README.md           # doc index
    exercises.md        # hands-on tasks
    dflow-arch.md       # architecture diagrams
    dflow-spec.md       # implementation spec (contributors)
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

## Design decisions

SQLite keeps the durability story local and inspectable. A production service would likely use Postgres, Temporal, or another durable execution framework, but SQLite is enough to demonstrate checkpointing, approval persistence, and side-effect logs.

TF-IDF is used instead of embeddings because this repo is about operational primitives, not retrieval quality. The selector enforces the token budget as a hard ceiling and makes ranking behavior easy to test.

Mock providers are the default so demos and tests run on a clean machine. Optional Anthropic integration is gated by `ANTHROPIC_API_KEY` and the `providers` extra.

Side effects use deterministic idempotency keys. Before the mock email send runs, the workflow checks the side-effect log. If recovery replays the send step after a crash, the existing result is returned and the email is not sent twice.

Token counting is approximate: whitespace word count divided by 0.75. A production implementation would use a tokenizer matched to the target model.

**Import note:** the Python package lives under `src/` (e.g. `from src.engine import WorkflowEngine`). Examples add the repo root to `PYTHONPATH`; see `start.sh`.

## Why not X? (Positioning & Primitives)

If you are deploying agentic workflows in production, you should use established enterprise tools. DurableFlow is not a replacement for them. Instead, it serves as a **zero-dependency reference implementation and stress-test sandbox** designed to isolate, inspect, and measure operational primitives.

### DurableFlow vs. Temporal
* **What Temporal does:** The industry gold-standard for durable execution.
* **Why not Temporal here:** Running Temporal requires hosting a cluster (Temporal server, Postgres/Cassandra database, and backend workers). DurableFlow utilizes SQLite and standard Python libraries to demonstrate the raw mechanics of checkpointing, approval gates, and crash resume in a single local file context.

### DurableFlow vs. LangGraph / CrewAI
* **What they do:** Powerful libraries and runtimes for agent orchestration, graph state, reasoning loops, persistence, and human-in-the-loop workflows.
* **Why not LangGraph/CrewAI here:** DurableFlow is not trying to compete with those frameworks. It isolates a few operational primitives in plain Python so you can see exactly what is persisted, when a checkpoint is written, how an approval pause resumes, and how idempotency prevents duplicate side effects. It is a teaching fixture and test harness, not a better agent framework.

### DurableFlow vs. LangSmith / Arize Phoenix
* **What they do:** Tracing, logging, and evaluation datasets.
* **Why not LangSmith here:** Observability platforms are the right place to inspect traces, monitor quality, and run evaluation programs around real systems. DurableFlow focuses on the runtime mechanics themselves: the local approval gate, the side-effect log, fallback routing, and active failure injection against those mechanisms.

### Production Recommendations
For production rollouts, we recommend:
* Use **Temporal** or an equivalent orchestrator for durability.
* Use **LangGraph** or **LlamaIndex Workflows** to design reasoning structures.
* Use **LiteLLM** or **Portkey** for model routing, gateways, and cost tracking.
* Use **LangSmith** for trace observation and dataset evaluation.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug fixes, exercises, and documentation improvements welcome.

## License

MIT — see [LICENSE](LICENSE).

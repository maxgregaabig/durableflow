# DurableFlow

Most agent demos optimize for intelligence. DurableFlow tests whether agentic workflows can survive production: crashes, approvals, model fallback, cost pressure, context limits, side effects, and unreliable compute.

**For:** backend engineers and infrastructure-minded AI teams evaluating the operational layer underneath agents, not prompt engineering or RAG tutorials.

DurableFlow now has two extension tracks:

| Extension | Status | What it proves |
|-----------|--------|----------------|
| [Colony](colony/README.md) | Implemented benchmark | Durable execution turns spot-like compute into completable long-running work, measured against a naive baseline under the same seeded loss schedule. |
| [Agent Readiness Pack](readiness/README.md) | Spec/design track | A readiness harness for deciding whether an agent is deployable: durable turns, gated writes, failure injection, and a verdict-first report. |

## Quick start

Requires **Python 3.11+** on macOS or Linux. No API keys required.

```bash
git clone https://github.com/marcospolanco/durableflow.git
cd durableflow
./start.sh crash    # crash recovery demo (start here)
./start.sh test     # full test suite
./start.sh inbox    # interactive approval demo
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

The Agent Readiness Pack is the next extension track. Its spec defines how to wrap a reason-act-observe agent so every turn is checkpointed, every external write is idempotent and approval-gated, and six production failure modes are tested before deployment:

- tool timeout
- malformed tool output
- prompt injection
- context overflow
- model fallback
- crash after side effect

The planned report is intentionally verdict-first: "ship" or "do not ship," the durability delta, and the single unsafe behavior that blocks deployment. The current repo contains the full implementation spec at **[readiness/docs/dflow-readiness-spec.md](readiness/docs/dflow-readiness-spec.md)**; the package implementation and demo are not yet present.

Start with **[readiness/README.md](readiness/README.md)** for scope, status, and the build contract.

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
  colony/
    README.md
    colony-spec.md
    benchmark.py
    controller.py
    provider.py
  readiness/
    README.md
    docs/
      dflow-readiness-spec.md
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

## What this is not

This is not a production system, a Temporal replacement, a distributed scheduler, or a general-purpose agent framework. It is a proof of concept exploring the operational primitives and measurement harnesses behind deployable agentic workflows. A production implementation would use Temporal or a comparable durable execution framework, vector search for context retrieval, real provider clients with rate-limit handling, and a proper secrets manager for API credentials.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug fixes, exercises, and documentation improvements welcome.

## License

MIT — see [LICENSE](LICENSE).

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

DurableFlow is an educational lab for the *operational* primitives underneath agentic workflows: durable checkpointing, crash recovery, approval gates, model fallback with cost accounting, context selection under a hard token budget, and idempotent side effects. It is deliberately **stdlib-only in the core path** — SQLite, plain Python, deterministic mock providers, no network. Every optional dependency (`anthropic`, `mcp`, `google-adk`, `langsmith`) is lazy-imported and gated so a clean machine can run all demos and tests offline.

Preserve that property when making changes: no new required dependencies, no network in default code paths, and no imports of optional SDKs at module top level in core packages.

## Commands

```bash
./start.sh test                 # full suite (creates .venv, installs .[dev])
./start.sh crash                # crash recovery demo — the canonical smoke test
./start.sh help                 # inbox | context | readiness | mcp demos

# Manual setup (examples/tests import `src.*` via PYTHONPATH=.; pyproject sets pythonpath=["."])
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
pytest tests/ -v
pytest tests/test_resume.py -v                     # one file
pytest tests/test_resume.py::test_name -v          # one test
pytest tests/ -k "context and not measurement"     # by expression
```

Extension entry points:

```bash
python3 examples/chaos_benchmark_demo.py                                    # Colony benchmark
python3 examples/readiness_demo.py                                          # writes readiness.json + readiness_report.md
python3 -m context.cli audit --db <db.sqlite> --workflow-id <id>            # context lineage audit
python3 -m evals.cli make-case|gate|render-report --help                    # eval gate (exit 0 pass / 1 fail / 2 incomplete)
```

There is no linter or formatter configured. CI (`.github/workflows/ci.yml`) runs `pytest tests/ -q` on Python 3.11/3.12/3.13 plus the crash demo — match that before claiming green.

Gated tests skip by default: live LangSmith needs `DURABLEFLOW_LANGSMITH_INTEGRATION=1` + `LANGSMITH_API_KEY`; real model calls need `.[providers]` + `ANTHROPIC_API_KEY`; Colony live mode needs `--live` + `VAST_API_KEY`.

## Architecture

**Core (`src/`) — a linear macro-step runner.** `WorkflowEngine` (`src/engine.py`) executes registered steps in order; each step returns a `StepResult` or `PauseForApproval`. `WorkflowStore` (`src/store.py`) checkpoints after every completed step in SQLite (a `PostgresWorkflowStore` subclass exists behind the same interface). `resume()` restarts from `current_step + 1`; approval resume is special-cased through `_resume_index_after_approval`. `ApprovalGate` persists pending decisions so a pause survives process death. `ModelRouter` does primary/secondary fallback with per-step USD cost from estimated tokens. `context_selector.py` is TF-IDF + greedy packing against a caller-supplied hard budget (no embeddings, on purpose). `TelemetryLogger` emits JSON lines for steps, approvals, crashes, fallback, completion.

**The engine stays dumb by design.** Branching, retry loops, and micro state machines belong in extension-owned tables, not in `WorkflowEngine` — there are no engine-level loops or back-edges. `factory/` demonstrates the intended shape: a store-backed micro state machine in `clear_phase_state` inside a single `phase_runner` macro step.

**Extension packages sit beside `src/`, not inside it:**

- `agent/` — reason-act-observe loop (`runner.py`, `mini_react.py`) bridged to durable steps; MCP and Google ADK adapters.
- `colony/` — chaos benchmark comparing a naive retry runner against the durable runner under an identical seeded loss schedule.
- `readiness/` — six failure-mode scenarios scored naked vs. wrapped, rendered verdict-first.
- `context/` — durable information lineage ledger (observed → retrieved/rejected → selected → consumed → influential), stores digests and source refs, not raw bodies.
- `evals/` — traces → eval cases → scorers → ship gate, with optional LangSmith export.
- `factory/` — CLEAR spec-driven workflow with an independent verification ledger.
- `integrations/` — LangSmith telemetry/lineage export, reached only through the `ContextExporter` protocol in `src/engine.py`. Core never imports it, and exporter failures must be swallowed so export can never affect execution.

**Privacy boundary:** context and eval artifacts persist digests, IDs, and source references — never raw email bodies, prompts, or model responses. `evals/redaction.py` and the negative tests enforce this; keep new persistence paths on the same side of the line.

## Documentation and spec conventions

`docs/README.md` is the index; `docs/learning-path.md` is the staged curriculum and `docs/walkthrough.md` is the canonical lookup index of every `*-spec.md` and `README.md`. Extensions carry their spec next to their code (`colony/colony-spec.md`, `factory/clear-spec.md`, `context/context-spec.md`, `planner/planner-spec.md`, `readiness/docs/`).

Specs use numbered claim IDs (`C-EVAL-001`, `C-CLEAR-006`, `T-EVAL-008` for tests) tied to expected evidence artifacts and a minimum evidence rank. Claims that cannot be verified offline are recorded as `DEFERRED-VERIFICATION` in `verification/deferred-items.md` and `verification/ledger.json` with an unblock procedure — they must not be described as implemented. When adding or changing behavior covered by a spec, update the claim table and the ledger rather than only the prose. Ledger updates are append-mostly: supersede a row by `row_id` instead of editing it in place.

Repo docs make measured claims (benchmark deltas, readiness scores) that come from deterministic local fixtures. If you change fixtures or scoring, re-run the demo and update the numbers quoted in the affected README.

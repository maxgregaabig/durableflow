# LangSmith Telemetry Adapter Proposal

**Status:** proposal, revised after critique
**Scope:** optional telemetry export only
**Core principle:** DurableFlow must continue to run locally with no API keys, no network calls, and no non-dev dependencies.

## Summary

DurableFlow should integrate LangSmith as an optional exporter for workflow telemetry and context lineage. The adapter would mirror local `TelemetryLogger` events and selected `ContextLedger` records into LangSmith traces so production users can inspect runs, build datasets, and run evaluations without changing DurableFlow's SQLite-first execution semantics.

LangSmith should not become the workflow engine, state store, approval authority, or source of truth. DurableFlow remains responsible for checkpointing, resume behavior, approval gates, side-effect idempotency, model routing records, and context lineage. LangSmith receives an external observation stream.

## Why This Fits

The README positions LangSmith as the right production tool for trace observation and dataset evaluation, while DurableFlow focuses on inspectable runtime mechanics. An adapter makes that boundary concrete:

- DurableFlow records what happened locally.
- LangSmith helps production teams inspect, compare, evaluate, and monitor those runs.
- The integration stays opt-in, preserving the educational zero-dependency path.

This is especially useful for teams that want to move a DurableFlow-style workflow into a larger LangChain/LangGraph/LangSmith environment without losing DurableFlow's explicit approval, durability, and context-lineage primitives.

## Non-Goals

- Do not replace `WorkflowStore` or `ContextLedger` with LangSmith.
- Do not require LangSmith for demos, tests, examples, or local development.
- Do not export raw prompts, email bodies, model responses, or sensitive artifacts by default.
- Do not make workflow correctness depend on LangSmith availability.
- Do not add LangSmith to the base `dependencies` list.
- Do not couple DurableFlow step definitions to LangChain abstractions.

## Proposed Package Shape

Add an optional extra:

```toml
[project.optional-dependencies]
# Example only; set the actual range after Phase 2 SDK validation.
langsmith = ["langsmith>=1.2,<2.0"]
```

Add a small adapter module:

```text
integrations/
  __init__.py
  langsmith_adapter.py
```

The adapter should be import-safe when LangSmith is not installed. Import errors should occur only when constructing the LangSmith exporter without the optional dependency.

The generic sink protocol belongs in `src/telemetry.py`. The LangSmith-specific implementation belongs in `integrations/langsmith_adapter.py` so core telemetry imports stay free of optional SDK checks.

The bounded version range is intentional. The exact lower and upper SDK versions should be set after the Phase 2 API validation spike proves root-run update or deterministic linked segment behavior. For example, if validation is done against a stable 1.x SDK, the extra should use a bounded range such as `langsmith>=1.2,<2.0`. SDK compatibility should be tested in CI for the pinned range before widening it.

## Configuration

Suggested environment variables:

| Variable | Purpose |
|---|---|
| `DURABLEFLOW_LANGSMITH_ENABLED` | Enables export when set to `1`, `true`, or `yes`. |
| `LANGSMITH_API_KEY` | Standard LangSmith authentication key. |
| `LANGSMITH_PROJECT` | Target LangSmith project name. |
| `LANGCHAIN_TRACING_V2` | Optional compatibility signal for LangChain-style environments; DurableFlow should not require it. |
| `DURABLEFLOW_LANGSMITH_REDACTION` | Redaction mode: `digest_only` by default, optionally `metadata`. |
| `DURABLEFLOW_RUN_URL_BASE` | Optional base URL for linking back to an internal DurableFlow run viewer. |

The default behavior should be disabled. A missing API key should not affect workflow execution.

`DURABLEFLOW_RUN_URL_BASE` is used only to build metadata links back to a local or internal DurableFlow run viewer, for example:

```text
{DURABLEFLOW_RUN_URL_BASE.rstrip("/")}/workflows/{workflow_id}
```

Invalid API keys, expired credentials, or forbidden projects should disable export after the first failed authentication attempt in a process. The workflow should continue, the adapter should increment an auth-failure counter, and later `emit()` calls should become no-ops unless the process is reconfigured or restarted.

## Integration Points

### 1. Telemetry Event Fan-Out

`TelemetryLogger` currently appends structured event dictionaries, prints JSON lines, and optionally writes JSONL to disk. The lowest-risk integration is to add a composable sink interface:

```python
class TelemetrySink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...
```

`TelemetryLogger` can accept `sinks: list[TelemetrySink] | None` and call each sink after appending the local event. Sink failures should be swallowed or logged to stderr, never raised into workflow execution.

Core code should never import the LangSmith adapter. User entry points, examples, or future CLI setup code should perform the optional import only after configuration enables LangSmith:

```python
from src.telemetry import TelemetryLogger


def build_telemetry() -> TelemetryLogger:
    sinks = []
    if langsmith_enabled_from_env():
        from integrations.langsmith_adapter import LangSmithTelemetrySink

        sink = LangSmithTelemetrySink.from_env()
        if sink is not None:
            sinks.append(sink)
    return TelemetryLogger(echo=True, sinks=sinks)
```

With this shape, `src.telemetry` defines only the generic protocol and fan-out behavior. `integrations.langsmith_adapter` owns all imports from the optional LangSmith SDK.

For LangSmith specifically, `LangSmithTelemetrySink.emit()` must be non-blocking. It should enqueue events into a bounded in-process queue and return immediately. Network I/O should happen through the LangSmith SDK's background facilities when available, or through a small worker thread / executor owned by the adapter. The workflow execution thread must not wait on LangSmith HTTP calls during step execution, approval handling, checkpointing, or crash recovery.

If the queue is full, the adapter should drop the export event, increment a dropped-event counter, and emit a local warning. It should not apply backpressure to DurableFlow execution.

For multi-workflow parallelism, the queue is process-wide by default. Each queued item must include `workflow_id`, root run UUID, and step/run identifiers so events from concurrent workflows can be demultiplexed by the worker. The default queue should be bounded by item count and approximate serialized byte size to avoid one workflow starving the process with large metadata. Recommended defaults:

- `max_items`: 1000
- `max_event_bytes`: 64 KiB after redaction
- overflow policy: drop newest event, increment `dropped_events`, and keep workflow execution moving

### 2. Workflow Run Mapping

Map each DurableFlow `workflow_id` to a LangSmith root run.

LangSmith run identifiers must be valid UUIDs, while DurableFlow workflow IDs are ordinary strings such as `wf-context-demo`. The adapter should use deterministic UUIDv5 mapping so separate processes and resumed workflows can refer to the same logical LangSmith run:

```python
import uuid

DURABLEFLOW_LANGSMITH_NAMESPACE = uuid.UUID("f8a30b3f-5c7f-51a8-9d8d-4e3e9f73f5c0")

def langsmith_run_id(workflow_id: str) -> uuid.UUID:
    return uuid.uuid5(DURABLEFLOW_LANGSMITH_NAMESPACE, workflow_id)

def langsmith_child_run_id(workflow_id: str, step_name: str, occurrence: int = 0) -> uuid.UUID:
    return uuid.uuid5(
        DURABLEFLOW_LANGSMITH_NAMESPACE,
        f"{workflow_id}:{step_name}:{occurrence}",
    )
```

The root run should be derived from `workflow_id`. Child runs should be derived from stable workflow attributes such as `workflow_id`, `step_name`, and a deterministic occurrence or checkpoint index when available.

The namespace UUID is a randomly chosen constant for DurableFlow LangSmith namespace isolation. It should not change after release because changing it would break stable run-ID mapping across process restarts and versions.

| DurableFlow Event | LangSmith Shape |
|---|---|
| `step_start` | Start child run named after `step_name`. |
| `step_complete` | End child run with duration, model, cost, and output summary. |
| `approval_requested` | Child run or event tagged `approval_wait`. |
| `approval_decision` | Metadata on the approval span. |
| `model_fallback` | Custom event or metadata on the current step span. |
| `crash_detected` | Root metadata event tagged `recovery`. |
| `workflow_resumed` | Root metadata event tagged `resume`. |
| `workflow_complete` | End root run with summary metadata. |

The exporter should append to the original root run when possible, using the deterministic root UUID. This preserves DurableFlow's core durability story in the trace: a resumed workflow should still read as one logical workflow.

Phase 2 must begin with a small LangSmith API validation spike that proves one of these two supported behaviors:

- Preferred: reopen or update the deterministic root run across process restarts.
- Fallback: create deterministic process-lifetime segment runs that link to the root run UUID through metadata and parent/reference fields supported by the current SDK.

The adapter should not ship until this behavior is tested against the LangSmith SDK version selected by the optional dependency. The fallback is acceptable only if the LangSmith API cannot safely reopen the original root run.

Fallbacks should not become top-level child spans. A fallback is a routing event within one DurableFlow step. The preferred shape is:

- one parent step span
- one failed model attempt event or LLM sub-run
- one fallback model attempt event or LLM sub-run
- routing metadata on the parent step, including `from_model`, `to_model`, and redacted error category

Example fallback event payload:

```json
{
  "event_type": "model_fallback",
  "workflow_id": "wf-context-demo",
  "step_name": "triage_llm",
  "metadata": {
    "from_model": "primary-model",
    "to_model": "fallback-model",
    "error_category": "rate_limit",
    "error_digest": "sha256:..."
  }
}
```

### 3. Context Lineage Export

`ContextLedger` stores durable information lineage: artifacts, selected/rejected events, decisions, and influence links. The LangSmith adapter should export context updates incrementally after each decision and again at workflow completion.

Incremental export matters because DurableFlow workflows may crash, pause for approval, or run for long periods. LangSmith should show the latest known lineage even when the workflow has not completed.

The automatic mechanism should be an explicit hook, not a hidden import inside `ContextLedger`. `WorkflowEngine._link_context_decisions()` already runs after each completed step and links context decisions to the step result when a ledger is present. Phase 3 should extend that point to call optional context export hooks from `dependencies`:

```python
context_exporters = dependencies.get("context_exporters", [])
for exporter in context_exporters:
    exporter.export_incremental(
        workflow_id=workflow_id,
        step_name=step_name,
        context_ledger=ledger,
    )
```

The LangSmith implementation can provide a `LangSmithContextExporter`, but the engine should depend only on a generic protocol. Export failures follow the same best-effort rules as telemetry sinks. `ContextLedger` remains a passive local ledger and should not import LangSmith.

Recommended default export:

- Artifact IDs
- Artifact roles
- Sources and source types
- Content digests
- Token counts
- Retrieval scores and ranks
- Rejection reasons
- Decision IDs
- Prompt and response digests
- Influential artifact IDs and scores

Recommended default omission:

- Raw artifact content
- Raw prompts
- Raw model responses
- Email bodies
- Calendar details beyond source references

This keeps LangSmith useful for inspection and eval grouping while preserving DurableFlow's current digest-first privacy posture.

### 4. Dataset and Eval Path

The first implementation should export traces only. A later phase can add commands that turn DurableFlow runs into LangSmith datasets:

```bash
python -m context.cli export-langsmith-dataset \
  --db examples/inbox_triage_context_demo.sqlite \
  --workflow-id wf-context-demo \
  --dataset durableflow-inbox-triage
```

Dataset export should integrate with the existing context inspection CLI rather than adding a fragmented user-facing command surface. If a broader DurableFlow CLI is introduced later, the LangSmith dataset export should move there as a subcommand.

Dataset examples should use redacted inputs and expected outputs derived from deterministic fixtures. This keeps evals reproducible and avoids leaking raw demo content unless explicitly requested.

The exported dataset should use a stable schema compatible with LangSmith evaluation workflows:

| Field | LangSmith Dataset Location | Contents |
|---|---|---|
| `inputs.workflow_id` | input | DurableFlow workflow ID. |
| `inputs.step_name` | input | Step that produced the decision or expected output. |
| `inputs.fixture_ref` | input | Redacted fixture identifier, not raw source content. |
| `inputs.context_digest_set` | input | Sorted selected artifact content digests. |
| `inputs.context_summary` | input | Optional redacted summary fields such as artifact roles, ranks, and source types. |
| `outputs.expected_status` | output | Expected workflow or step status from deterministic fixtures. |
| `outputs.expected_decision_label` | output | Deterministic label such as triage category or approval outcome when available. |
| `outputs.expected_side_effect` | output | Redacted side-effect expectation, for example `email_send_requested` rather than message body. |
| `metadata.model_used` | metadata | Model name recorded by DurableFlow. |
| `metadata.cost_usd` | metadata | Recorded step cost. |
| `metadata.token_counts` | metadata | Input/output or artifact token counts. |
| `metadata.lineage_counts` | metadata | Observed, selected, rejected, consumed, and influential counts. |
| `metadata.seed` | metadata | Fixture seed when present. |

This schema lets evaluators compare workflow outcomes, routing choices, and context-selection behavior without requiring raw prompts or raw retrieved content. A future raw-data dataset mode would require an explicit opt-in and separate compliance review.

Example dataset row:

```json
{
  "inputs": {
    "workflow_id": "wf-context-demo",
    "step_name": "triage_llm",
    "fixture_ref": "inbox_triage:case_007",
    "context_digest_set": [
      "sha256:018b...",
      "sha256:a91d..."
    ],
    "context_summary": {
      "selected_count": 2,
      "rejected_count": 3,
      "artifacts": [
        {
          "artifact_role": "source_artifact",
          "source_type": "email",
          "rank_position": 1,
          "retrieval_score": 0.82,
          "content_digest": "sha256:018b..."
        },
        {
          "artifact_role": "source_artifact",
          "source_type": "calendar",
          "rank_position": 2,
          "retrieval_score": 0.67,
          "content_digest": "sha256:a91d..."
        }
      ]
    }
  },
  "outputs": {
    "expected_status": "completed",
    "expected_decision_label": "needs_human_review",
    "expected_side_effect": "approval_requested"
  },
  "metadata": {
    "model_used": "mock-primary",
    "cost_usd": 0.00042,
    "token_counts": {"input": 1420, "output": 96},
    "lineage_counts": {
      "observed": 5,
      "selected": 2,
      "rejected": 3,
      "consumed": 2,
      "influential": 1
    },
    "seed": 1337
  }
}
```

`context_summary` should never contain raw text. It is limited to counts, roles, source types, ranks, scores, and digests.

## Archival, Deletion, And Backfill

LangSmith traces are retained independently of local SQLite. Deleting a local DurableFlow workflow or SQLite database does not cascade deletion to LangSmith. The adapter should document that LangSmith retention, deletion, and access control are governed by the target LangSmith project.

DurableFlow remains the local source of truth while the SQLite record exists. LangSmith can be a long-term observation record, but it is not authoritative for replay, approval state, or side-effect idempotency.

Backfill should be explicit. Manual export functions may read historical SQLite workflows and export redacted traces or datasets, but they must mark payloads with `export_mode: "backfill"` and preserve original workflow timestamps when available. Backfill should use the same deterministic UUID mapping so historical exports do not duplicate existing LangSmith runs.

## Failure Semantics

LangSmith export is best-effort:

- Network errors must not fail a workflow step.
- Rate limits must not block checkpoints or approvals.
- Serialization errors should mark only the export attempt as failed.
- Export retries should be bounded and should not replay side effects.
- Export queues should be bounded so telemetry cannot exhaust memory.
- Slow or unavailable LangSmith endpoints must not hold the workflow execution thread.
- Local SQLite remains the source of truth for audit and recovery.

The adapter should expose counters or warning events for failed exports so users know when traces are incomplete.

Retry policy:

- max attempts per export item: 3
- backoff: exponential, starting at 250 ms
- jitter: small random jitter to avoid synchronized retries
- ceiling: 10 seconds between attempts
- final failure: drop the item, increment `failed_exports`, and retain no side-effect replay obligation

Persistent local retry queues are out of scope for the first adapter. The first implementation should use only an in-memory queue. A disk-backed queue would create retention, encryption, cleanup, and PII-risk questions that should be handled in a separate proposal.

## Redaction Policy

Default mode: `digest_only`.

In this mode, the adapter exports identifiers, digests, counts, scores, timings, status, model names, cost, and non-sensitive metadata. It does not export raw strings that may contain customer data.

Default-safe fields:

- Workflow ID and deterministic LangSmith run UUID
- Step names and event types
- Latency, token counts, cost, retry counts, and routing status
- Model names
- Artifact IDs, artifact roles, source types, and content digests
- Retrieval scores, rank positions, and rejection reason codes
- Decision IDs, prompt digests, response digests, influence scores

Default-redacted fields:

- Query strings
- Retrieved text
- Prompt templates and rendered prompts
- Model outputs
- Email addresses
- Email subjects and bodies
- Calendar attendees, organizers, titles, descriptions, locations, and meeting links
- File paths or source references that expose usernames, customer names, tenant names, or secrets
- Free-form metadata values that may contain raw user text
- Any user-provided free-form input
- PII such as names, addresses, phone numbers, account identifiers, and customer identifiers
- PHI or health-related content
- Secrets, tokens, credentials, API keys, and session identifiers

Optional mode: `metadata`.

This mode may export selected metadata fields such as inbox category, retrieval method, or workflow labels. It still should not export raw prompts or responses unless a future explicit `raw` mode is added with clear warnings.

Metadata export must be allow-list based. The adapter should not pass arbitrary `metadata` dictionaries through to LangSmith, even in `metadata` mode. Unknown keys should be dropped by default, and string values should be capped at a small size such as 512 bytes after redaction. Oversized metadata values should be replaced with a digest and a `truncated: true` marker. This prevents metadata injection from leaking PII/PHI or exhausting queue memory.

## Example Usage

```python
from src.telemetry import TelemetryLogger


def build_langsmith_dependencies() -> tuple[TelemetryLogger, dict[str, object]]:
    sinks = []
    dependencies: dict[str, object] = {}

    if langsmith_enabled_from_env():
        from integrations.langsmith_adapter import (
            LangSmithContextExporter,
            LangSmithTelemetrySink,
        )

        sink = LangSmithTelemetrySink.from_env()
        if sink is not None:
            sinks.append(sink)
            dependencies["context_exporters"] = [LangSmithContextExporter.from_sink(sink)]

    return TelemetryLogger(echo=True, sinks=sinks), dependencies
```

Manual context export remains useful for backfills or one-off audits:

```python
from integrations.langsmith_adapter import export_context_audit

audit = context_ledger.audit_workflow("wf-context-demo")
export_context_audit(audit)
```

## Test Plan

Add tests that do not require network access:

- `TelemetryLogger` calls configured sinks with event dictionaries.
- Sink failures do not interrupt logging or workflow execution.
- LangSmith sink enqueue is non-blocking and does not perform network calls on the caller thread.
- Bounded queue overflow drops export events and records a local warning/counter.
- LangSmith adapter imports cleanly when optional dependency is absent.
- DurableFlow workflow IDs map to deterministic UUIDv5 LangSmith run IDs.
- Event mapping produces stable payloads from representative telemetry events.
- Resumed workflow events attach to the same deterministic root run ID.
- Phase 2 API validation proves either root-run reopening or deterministic linked segment behavior with the selected LangSmith SDK.
- Context audit export redacts raw content and includes digests, counts, ranks, and influence links.
- Context audit export supports incremental decision updates.
- Context export hooks are called from workflow orchestration after decision linking, without importing LangSmith in `ContextLedger`.
- `model_fallback` maps to step metadata or a custom event rather than an unrelated top-level run.
- Dataset export produces the documented `inputs`, `outputs`, and `metadata` schema.
- Disabled configuration performs no network work and returns a no-op sink.

Networked LangSmith behavior should be covered by a small optional integration test gated behind an environment variable, for example `DURABLEFLOW_LANGSMITH_INTEGRATION=1`.

Unit tests should use a fake client with a minimal LangSmith-like interface:

```python
class FakeLangSmithClient:
    def __init__(self):
        self.created_runs = []
        self.updated_runs = []
        self.events = []

    def create_run(self, *, id, name, run_type, project_name, inputs=None, extra=None, parent_run_id=None):
        self.created_runs.append(
            {
                "id": id,
                "name": name,
                "run_type": run_type,
                "project_name": project_name,
                "inputs": inputs or {},
                "extra": extra or {},
                "parent_run_id": parent_run_id,
            }
        )

    def update_run(self, run_id, *, outputs=None, error=None, end_time=None, extra=None):
        self.updated_runs.append(
            {
                "run_id": run_id,
                "outputs": outputs or {},
                "error": error,
                "end_time": end_time,
                "extra": extra or {},
            }
        )

    def log_event(self, run_id, *, name, payload):
        self.events.append({"run_id": run_id, "name": name, "payload": payload})
```

Concrete unit cases:

- Non-blocking enqueue: inject a fake client whose network methods sleep, call `emit()`, and assert the call returns within a small local threshold while the worker handles the item asynchronously.
- Queue overflow: configure `max_items=1`, emit two events, assert one is queued or exported and `dropped_events == 1`.
- Invalid credentials: fake an auth error on the first client call, assert export disables itself and later `emit()` calls do not raise.
- Metadata sanitization: pass a metadata dict with unknown keys, a 10 MB string, an email address, and a token-like value; assert only allow-listed fields, digests, and truncation markers are exported.
- Parallel workflows: emit interleaved events for two workflow IDs and assert generated run IDs and child IDs remain distinct.

## Implementation Phases

### Phase 1: Local Sink Interface

- Add `TelemetrySink`.
- Add sink fan-out to `TelemetryLogger`.
- Catch and locally warn on sink exceptions.
- Add no-op sink tests.
- Keep all current behavior unchanged when no sinks are provided.

### Phase 2: LangSmith Trace Exporter

- Validate the selected LangSmith SDK API for reopening deterministic root runs or creating deterministic linked segment runs.
- Add `integrations.langsmith_adapter`.
- Add optional `langsmith` dependency extra.
- Add a compatibility note documenting the validated LangSmith SDK version range.
- Dynamically import the LangSmith SDK inside the adapter.
- Add bounded asynchronous export queue.
- Add deterministic UUIDv5 run-ID mapping.
- Map workflow events to root and child runs.
- Implement digest-only redaction.
- Add unit tests using a fake LangSmith client.

### Phase 3: Context Audit Export

- Add a generic context exporter hook invoked by workflow orchestration after context decision linking.
- Export `ContextAudit` summaries incrementally after decisions and again at workflow completion.
- Add stable schema for context-lineage payloads.
- Verify that raw content is omitted by default.

### Phase 4: Dataset Export

- Add `context.cli` support for creating LangSmith datasets from selected DurableFlow runs.
- Start with deterministic examples only.
- Implement the documented dataset schema and example shape.
- Document how teams can attach evaluators outside the core runtime.

## Resolved Design Decisions

- Resumed workflows should append to the original LangSmith root run when the client supports it, using a deterministic UUID derived from `workflow_id`.
- Phase 2 must validate the LangSmith SDK run-update behavior before shipping the adapter; if direct reopening is not stable, deterministic linked segment runs are the supported fallback.
- The generic `TelemetrySink` protocol should live in `src/telemetry.py`; LangSmith-specific code should live in `integrations/langsmith_adapter.py`.
- Core code should never import the LangSmith adapter; optional user setup or CLI code should lazy-import it only when enabled.
- The default `digest_only` export should include operational metadata, digests, counts, ranks, and scores while redacting raw user text and raw model I/O.
- Metadata export should be allow-list based, size-capped, and sanitized before enqueue.
- Context audit export should be incremental after every decision, with a final completion export, triggered by a generic orchestration hook after `ContextLedger` decision linking.
- `model_fallback` should be represented as metadata or a custom event inside the current step span, with optional model-attempt sub-runs under that same step.
- LangSmith retention is independent of local SQLite deletion; local deletion does not cascade to LangSmith.
- The first adapter should use in-memory retry only; persistent export queues are out of scope.

## Remaining Open Questions

- Should dropped export counters be exposed only as local warnings, or also as DurableFlow telemetry events?
- Should a future explicit `raw` redaction mode exist, or should raw payload export remain out of scope permanently?

## Recommended Positioning

DurableFlow should describe LangSmith integration as:

> Optional export of DurableFlow's local execution and context-lineage records into LangSmith for production trace inspection and evaluation workflows.

That wording keeps the boundary clear: LangSmith observes and evaluates; DurableFlow executes, checkpoints, gates, and records the local audit trail.

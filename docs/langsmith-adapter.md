# Specification: LangSmith Telemetry Adapter

**Status:** READY (network-free scope) / DEFERRED-VERIFICATION (live LangSmith SDK validation, see §Deferred Items)
**Owner:** Marcos Polanco
**Applies:** `agentel/process/spec-policy.md`, `agentel/process/semantics-policy.md`, `agentel/process/verification-policy.md`
**Dependency policy:** Optional extra only. Base `dependencies` stays `[]`; the LangSmith SDK is gated behind `[project.optional-dependencies].langsmith`. Core runtime imports remain Python standard library.
**Scope:** optional telemetry export only
**Core principle:** DurableFlow must continue to run locally with no API keys, no network calls, and no non-dev dependencies.

## 0. Positioning Note

This is a library-level integration feature, not a user-facing UI. It therefore follows `spec-policy.md` (what/why/for-whom, phases, gates, claim verification), `verification-policy.md` (falsifiable claims, admissible evidence, independence), and the *Lite* path of `semantics-policy.md §11` for its small operator-facing surface (CLI dataset export, run-viewer links). A full Experience Semantics template is not warranted; a ubiquitous-language note covers the operator-facing terms. This spec exists to make every capability claim falsifiable and every "done" check independently reproducible.

## 1. Intent Mapping

### 1.1 Business Intent (Outcome)

Let production teams inspect, compare, evaluate, and monitor DurableFlow runs in LangSmith without changing DurableFlow's SQLite-first execution semantics — so a DurableFlow-style workflow can move into a larger LangChain/LangGraph/LangSmith environment without losing DurableFlow's explicit approval, durability, and context-lineage primitives.

### 1.2 Experience Intent (Mental Model)

The operator believes they are **"inspecting a production trace"** and **"building an eval dataset from real runs"** — not "reading adapter internals", "demultiplexing queue items", or "mapping event_type to run_type". Their primary concerns are: *did the trace capture the whole workflow including the resume?*, *where did the model fall back?*, and *is any raw content leaking into LangSmith?* Emotional context: audit-focused and privacy-cautious. The operator expects exporters to silently drop data under load; the adapter must surface those drops as counters, never hide them.

### 1.3 Technical Intent (Architectural Invariants)

1. Local SQLite remains the source of truth for checkpointing, resume, approval state, side-effect idempotency, model routing, and context lineage.
2. LangSmith export is best-effort: network errors, rate limits, serialization failures, and slow endpoints MUST NOT fail a workflow step, block a checkpoint/approval, or hold the execution thread.
3. Core code (`src/`, `context/`) MUST NEVER import `integrations.langsmith_adapter`. The optional import is performed only by user entry points / CLI setup code after configuration enables it.
4. Raw user text, raw prompts, raw model I/O, and PII/PHI/secrets MUST NOT be exported by default (`digest_only`).
5. No non-optional dependency is introduced; the LangSmith SDK lives behind an optional extra.
6. Completion claims require independent verification; implementer assertion (E5) is never sufficient.

## 2. Conceptual Gherkin

These describe operator cognition and trace semantics, not button clicks. Behavioral coverage lives in the §Test Plan.

```gherkin
Scenario: Resumed workflow reads as one logical trace
  Given a workflow crashed and resumed in a new process
  When the operator opens the LangSmith project
  Then the resumed events attach to the same deterministic root run (same UUIDv5)
  And the trace shows one continuous workflow, not two

Scenario: Approval pause is visible, not invisible
  Given a step pauses for operator approval
  When the operator inspects the trace
  Then the approval wait and the later decision are both visible on the step span
  And the workflow did not block on LangSmith to render them

Scenario: Model fallback is a routing event inside the step, not a phantom step
  Given the primary model failed and the secondary handled the step
  When the operator reads the step span
  Then they see from_model → to_model routing metadata on that step
  And there is no unrelated top-level "fallback" run

Scenario: Disabled configuration is provably inert
  Given LangSmith export is disabled or the API key is absent
  When any workflow runs
  Then zero network calls occur and the sink is a no-op
  And execution performance is unchanged from a no-adapter baseline

Scenario: The operator can build an eval dataset without leaking raw content
  Given a completed workflow with a context ledger
  When the operator exports a LangSmith dataset
  Then inputs/outputs contain only digests, counts, ranks, scores, and redacted labels
  And no raw email body, prompt, or model response is present
```

## 3. Runtime Traceability

Per `spec-policy.md §4.3`, the golden-path execution trace for an enabled adapter:

```text
User entry point
  └─ build_telemetry() / build_langsmith_dependencies()
       └─ langsmith_enabled_from_env() == True  (only here is the SDK imported)
            └─ from integrations.langsmith_adapter import LangSmithTelemetrySink
                 └─ LangSmithTelemetrySink.from_env()
                      └─ constructs a client wrapper (real SDK OR documented FakeLangSmithClient)

Workflow execution (TelemetryLogger.log)
  └─ for sink in self.sinks:
       └─ LangSmithTelemetrySink.emit(event)            # NON-BLOCKING
            └─ redact(event) -> enqueue bounded queue -> return immediately
                 └─ worker thread (daemon) drains queue
                      └─ map_event_to_run(event) -> client.create_run/update_run/log_event
                           └─ retry(3, exp backoff 250ms, +jitter, 10s ceiling)
                                └─ on auth failure: disable export for process lifetime

Context lineage export (engine._link_context_decisions)
  └─ for exporter in dependencies["context_exporters"]:
       └─ LangSmithContextExporter.export_incremental(...)   # best-effort, swallowed on error
            └─ ledger.audit_workflow(workflow_id) -> redacted snapshot -> enqueue
```

**Import-graph invariants (architectural claims, verified by VER-008 / SEM-011 analog):**
- `src/telemetry.py` defines only the generic `TelemetrySink` protocol; it imports nothing from `integrations/`.
- `src/engine.py` defines only the generic `ContextExporter` protocol and the fan-out loop; it imports nothing from `integrations/`.
- `context/ledger.py` imports nothing from `integrations/`. `ContextLedger` stays passive.
- Only `integrations/langsmith_adapter.py` imports the optional SDK, and only at construction time.

## 4. Ubiquitous Language (Lite)

| Operator term | Technical term (never shown to operators) |
|---|---|
| Production trace | LangSmith root + child runs derived by UUIDv5 |
| Trace continuity | deterministic root-run UUID stable across restarts |
| Eval dataset | `inputs`/`outputs`/`metadata` rows from `build_dataset_rows` |
| Redacted export | `digest_only` redaction mode |
| Export drop | `dropped_events` / `failed_exports` counter |

## 5. Summary

DurableFlow should integrate LangSmith as an optional exporter for workflow telemetry and context lineage. The adapter would mirror local `TelemetryLogger` events and selected `ContextLedger` records into LangSmith traces so production users can inspect runs, build datasets, and run evaluations without changing DurableFlow's SQLite-first execution semantics.

LangSmith should not become the workflow engine, state store, approval authority, or source of truth. DurableFlow remains responsible for checkpointing, resume behavior, approval gates, side-effect idempotency, model routing records, and context lineage. LangSmith receives an external observation stream.

## 6. Why This Fits

The README positions LangSmith as the right production tool for trace observation and dataset evaluation, while DurableFlow focuses on inspectable runtime mechanics. An adapter makes that boundary concrete:

- DurableFlow records what happened locally.
- LangSmith helps production teams inspect, compare, evaluate, and monitor those runs.
- The integration stays opt-in, preserving the educational zero-dependency path.

This is especially useful for teams that want to move a DurableFlow-style workflow into a larger LangChain/LangGraph/LangSmith environment without losing DurableFlow's explicit approval, durability, and context-lineage primitives.

## 7. Non-Goals

- Do not replace `WorkflowStore` or `ContextLedger` with LangSmith.
- Do not require LangSmith for demos, tests, examples, or local development.
- Do not export raw prompts, email bodies, model responses, or sensitive artifacts by default.
- Do not make workflow correctness depend on LangSmith availability.
- Do not add LangSmith to the base `dependencies` list.
- Do not couple DurableFlow step definitions to LangChain abstractions.

## 8. Proposed Package Shape

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

## 9. Configuration

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

## 10. Integration Points

### 10.1 Telemetry Event Fan-Out

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

### 10.2 Workflow Run Mapping

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

### 10.3 Context Lineage Export

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

### 10.4 Dataset and Eval Path

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

## 11. Archival, Deletion, And Backfill

LangSmith traces are retained independently of local SQLite. Deleting a local DurableFlow workflow or SQLite database does not cascade deletion to LangSmith. The adapter should document that LangSmith retention, deletion, and access control are governed by the target LangSmith project.

DurableFlow remains the local source of truth while the SQLite record exists. LangSmith can be a long-term observation record, but it is not authoritative for replay, approval state, or side-effect idempotency.

Backfill should be explicit. Manual export functions may read historical SQLite workflows and export redacted traces or datasets, but they must mark payloads with `export_mode: "backfill"` and preserve original workflow timestamps when available. Backfill should use the same deterministic UUID mapping so historical exports do not duplicate existing LangSmith runs.

## 12. Failure Semantics

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

## 13. Redaction Policy

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

## 14. Example Usage

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

## 15. Test Plan

Per `spec-policy.md §5`, tests map to claims (see §Verification Plan). Network-free tests use the documented minimal LangSmith-like client (`FakeLangSmithClient`, below); the networked path is gated behind `DURABLEFLOW_LANGSMITH_INTEGRATION=1`.

### 15.1 Test Cases

| Test ID | Scenario | Type | Assertion |
|---|---|---|---|
| LSMITH-UNIT-001 | Sink fan-out | Unit | `TelemetryLogger` calls each configured sink's `emit` with the event dict |
| LSMITH-UNIT-002 | Sink failure isolation | Unit | A raising sink is swallowed + warned; logging and execution continue |
| LSMITH-UNIT-003 | Non-blocking enqueue | Unit | `emit()` against a slow (sleeping) client returns within a small local threshold; the worker handles the item async |
| LSMITH-UNIT-004 | Queue overflow | Unit | With `max_items=1`, emitting two events drops one and sets `dropped_events == 1` |
| LSMITH-UNIT-005 | Import-safe without SDK | Unit | `integrations.langsmith_adapter` imports cleanly with no SDK installed; `from_env()` returns `None` |
| LSMITH-UNIT-006 | UUIDv5 determinism | Unit | `langsmith_run_id(wf)` is stable and equal across calls/processes; child IDs are distinct |
| LSMITH-UNIT-007 | Event mapping stability | Unit | Representative telemetry events produce stable `create_run`/`update_run`/`log_event` payloads |
| LSMITH-UNIT-008 | Resumed root continuity | Unit | A resumed workflow's events attach to the same deterministic root UUID |
| LSMITH-UNIT-009 | Parallel workflow demux | Unit | Interleaved events for two workflow IDs produce distinct root and child IDs |
| LSMITH-UNIT-010 | Auth-failure disable | Unit | A faked auth error on the first client call disables export; later `emit()` calls are no-ops, never raise |
| LSMITH-UNIT-011 | Metadata sanitization | Unit | Unknown keys dropped; 10 MB string replaced by digest + `truncated:true`; email/token-like values not exported as-is |
| LSMITH-UNIT-012 | model_fallback in-step | Unit | `model_fallback` becomes metadata/custom event under the step span; no top-level fallback run is created |
| LSMITH-CTX-001 | Context redaction | Integration | `export_context_audit` omits raw content; includes digests, counts, ranks, influence links |
| LSMITH-CTX-002 | Incremental context export | Integration | `export_incremental` runs after each decision linking; final export at completion |
| LSMITH-CTX-003 | Core import-cleanliness | Negative/architectural | `context/ledger.py` and `src/engine.py` import nothing from `integrations/` |
| LSMITH-DATA-001 | Dataset schema shape | Unit | `build_dataset_rows` emits the documented `inputs`/`outputs`/`metadata` schema |
| LSMITH-DATA-002 | Dataset no raw text | Negative | No raw email body/prompt/response appears in any dataset row |
| LSMITH-SEM-001 | Disabled-config inert | Semantic | Disabled/missing-key config performs zero network calls; sink is a no-op |
| LSMITH-INT-001 | Live SDK round-trip | Integration | Gated by `DURABLEFLOW_LANGSMITH_INTEGRATION=1`; exercises real create/update/event against a configured project |

### 15.2 Minimal Client Contract

Unit tests use a fake client with this interface. The real-SDK wrapper (constructed only when the SDK is present and enabled) MUST be interchangeable with it. This contract is the validation boundary for `C-LSMITH-DEFER-001`.

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

Concrete adversarial cases (from the critique) are encoded as LSMITH-UNIT-003/004/010/011/009 above. A test that asserts a happy-path payload only (e.g. LSMITH-UNIT-007) is insufficient on its own and MUST be paired with the corresponding negative/adversarial case before its claim advances to VERIFIED.

## 16. Deferred Items

Per `verification-policy.md §8` and `spec-policy.md §10`, a claim that cannot be falsified, reproduced, or independently tested in the current environment is **UNVERIFIABLE** and is recorded as **DEFERRED-VERIFICATION** — never silently COMPLETE. Deferred items MUST appear in the verification ledger with verdict `DEFERRED-VERIFICATION`, evidence artifact `verification/deferred-items.md`, and the rationale below. They MUST NOT be claimed as implemented (VER-013).

| Claim ID | Deferred claim | Rationale | Unblocks |
|---|---|---|---|
| C-LSMITH-DEFER-001 | Live LangSmith SDK validates root-run reopening (preferred) or deterministic linked-segment behavior (fallback) against the pinned `langsmith>=1.2,<2.0` SDK. | Requires outbound network access and a live `LANGSMITH_API_KEY` against a configured project — neither available in the offline, dependency-pinned build/CI environment. Falsifiable only against a live endpoint. | Widening or firming the SDK pin; removing the `DEFERRED-VERIFICATION` verdict; validating real-SDK `create_run`/`update_run`/`log_event` semantics. |

**Interim behavior while deferred:** the adapter ships against the documented `FakeLangSmithClient` contract (§15.2). All network-free claims (LSMITH-UNIT/CTX/DATA/SEM) advance to VERIFIED normally. The adapter is export-functional against any client matching the contract; only *live-API* conformance is deferred.

## 17. Entry Gates

Implementation MUST NOT begin until these gates pass (`spec-policy.md §4`, `verification-policy.md §5`).

### 17.1 Specification Completeness
- [x] All acceptance criteria are explicit and unambiguous.
- [x] No `TBD`/`TODO` placeholders in this spec (the `langsmith>=1.2,<2.0` range is intentionally bounded, not a TODO).
- [x] Required paths, classes, env vars, UUID namespace, and step/event mappings are listed.
- [x] Dependencies are listed; the SDK is an optional extra, not a base dep.
- [x] Deferred items are explicitly scoped (§16) and not required for MVP.

### 17.2 Cross-Reference Consistency
- [x] Event-mapping table (§10.2) matches the runtime trace (§3) and test plan (§15).
- [x] Dataset schema (§10.4) matches the test plan dataset cases (LSMITH-DATA-001/002).
- [x] Redaction allow/redact lists (§13) match the sanitization test (LSMITH-UNIT-011).

### 17.3 Implementation Readiness
- [x] Runtime traceability (§3) names every golden-path call and the import-graph invariants.
- [x] The `FakeLangSmithClient` contract (§15.2) is the SDK boundary.
- [x] Claim verification method is specified for every acceptance criterion (§Verification Plan).

### 17.4 Verification Entry Gates
- [x] Each claim is falsifiable (states a refuting observation).
- [x] Each claim is classified by type.
- [x] Each claim declares a verification method/check and an expected evidence artifact.
- [x] Tests/fixtures run in isolation from ambient/developer-local state (no network unless `DURABLEFLOW_LANGSMITH_INTEGRATION=1`).
- [x] The live-SDK claim is classified DEFERRED-VERIFICATION, not asserted as testable here (§16).

## 18. Verification Plan

Verification follows `verification-policy.md`. Implementer reports are inputs only; they are never sufficient evidence (E5 inadmissible as sole basis for VERIFIED). A claim is VERIFIED only after an independent party reproduces admissible evidence at or above the claim's minimum rank.

### 18.1 Claim Register

| Claim ID | Claim | Type | Method / Check | Evidence artifact | Min rank |
|---|---|---|---|---|---|
| C-LSMITH-001 | `TelemetryLogger` fans out to configured sinks and isolates sink failures from execution | Capability | LSMITH-UNIT-001/002 + code read | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-002 | `emit()` is non-blocking; network I/O happens off the caller thread | Behavioral | LSMITH-UNIT-003 (slow-client timing) | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-003 | Bounded queue overflow drops the newest event and increments `dropped_events` without backpressure | Behavioral | LSMITH-UNIT-004 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-004 | `langsmith_run_id`/`langsmith_child_run_id` are deterministic UUIDv5; resumed + parallel runs stay distinct | Capability / Behavioral | LSMITH-UNIT-006/008/009 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-005 | First auth failure disables export for the process; later `emit()` is a no-op and never raises | Behavioral | LSMITH-UNIT-010 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-006 | Metadata export is allow-listed, size-capped, and sanitized (unknown keys dropped, oversized→digest+`truncated`, no raw email/token) | Behavioral | LSMITH-UNIT-011 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-007 | Default export redacts raw content; includes digests, counts, ranks, scores, influence links | Negative | LSMITH-CTX-001/002 + LSMITH-DATA-002 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-008 | `model_fallback` maps to in-step metadata/custom event, not a top-level run | Behavioral | LSMITH-UNIT-012 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-009 | Core modules import nothing from `integrations/`; `ContextLedger` stays passive | Negative / architectural | LSMITH-CTX-003 (import lint) | `tests/test_langsmith_adapter.py` | E4 |
| C-LSMITH-010 | Dataset export produces the documented `inputs`/`outputs`/`metadata` schema with no raw text | Behavioral / Negative | LSMITH-DATA-001/002 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-011 | Disabled/missing-key config performs no network work and returns a no-op sink | Behavioral | LSMITH-SEM-001 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-012 | The module imports cleanly with no SDK present; construction without SDK raises `ImportError` only | Capability | LSMITH-UNIT-005 | `tests/test_langsmith_adapter.py` | E2 |
| C-LSMITH-DEFER-001 | Live SDK validates root-run reopening or linked-segment behavior | Capability | VER-013 deferred audit; LSMITH-INT-001 when networked | `verification/deferred-items.md` | E4 |

### 18.2 Required VER Checks

| Check | Applies to |
|---|---|
| VER-001 | Every claim (falsifiable) |
| VER-002 | Every VERIFIED row (no E5-only) |
| VER-004 | Non-blocking, overflow, resume claims (reproduced) |
| VER-005 | Capability claims (code does the action, not a precursor) |
| VER-006 | Claimed-complete phases (no TODOs for capabilities) |
| VER-008 | C-LSMITH-009 (import-graph invariant) |
| VER-013 | C-LSMITH-DEFER-001 (deferred item not claimed COMPLETE) |
| VER-014 | Load-bearing claims (mutation/held-out probe, esp. C-LSMITH-002/003/005) |

### 18.3 Verification Ledger Schema

For this library feature, evidence artifacts are the committed test module and, optionally, an archived run log. Ledger rows MAY be stored in `verification/ledger.json` per the `factory/clear-spec.md` convention; the schema is:

```json
{
  "feature": "langsmith-adapter",
  "build_id": "durableflow-0.1.0-build-N",
  "build_completed_at": "ISO-8601 UTC",
  "claims": [
    {
      "row_id": "ledger-row-uuid",
      "claim_id": "C-LSMITH-XXX",
      "claim_text": "Falsifiable proposition",
      "type": "Capability|Behavioral|Performance|Completeness|Negative|Absence",
      "method": "LSMITH-XXX or VER-XXX",
      "evidence_artifact": "tests/test_langsmith_adapter.py",
      "evidence_digest": "sha256:...",
      "source_artifact_digest": "sha256:...",
      "evidence_rank": "E1|E2|E3|E4",
      "implementer": "agent_or_human_id",
      "verifier": "agent_or_human_id (must differ from implementer)",
      "verdict": "VERIFIED|REFUTED|PARTIAL|UNVERIFIABLE|DEFERRED-VERIFICATION",
      "supersedes_row_id": null,
      "verified_at": "ISO-8601 UTC (must post-date build)"
    }
  ]
}
```

**Stale-evidence rule:** a build change voids prior VERIFIED rows; `verified_at` MUST post-date `build_completed_at` and `source_artifact_digest` MUST match the current artifact. **Append-mostly:** new verdicts supersede, never edit in place.

## 19. Exit Gates

A phase may be marked COMPLETE only after the relevant gates pass (`spec-policy.md §6`, `verification-policy.md §8`).

### 19.1 Implementation Verification
- [ ] Actual implementation code read for each capability claim (VER-005).
- [ ] Behavior matches the claim, not merely a function name.
- [ ] No TODO comments remain for claimed capabilities (VER-006).
- [ ] Test artifacts archived.

### 19.2 Acceptance Checklist
- [ ] All acceptance criteria checked.
- [ ] Each checked criterion has test coverage.
- [ ] Every claimed capability has a current VERIFIED ledger row.

### 19.3 Dependency Verification
- [ ] No new base dependency introduced.
- [ ] The LangSmith SDK is an optional extra (`[project.optional-dependencies].langsmith`), explicitly marked optional.
- [ ] The SDK range `langsmith>=1.2,<2.0` is bounded. *Note on pinning:* `spec-policy.md §6.3` prefers `==`. The bounded range is an intentional spec decision (§8): the lower bound sets the validated floor, the upper bound guards against a breaking 2.x. The `==` pin is enforced in CI/test environments for reproducibility; the published extra retains the bounded range until `C-LSMITH-DEFER-001` widens the validated set.

### 19.4 Cross-Reference Validation
- [ ] README/spec claims match implementation reality (VER-012).
- [ ] No DEFERRED item claimed as implemented (VER-013).
- [ ] No unverifiable claim laundered to VERIFIED.

## 20. Pre-Mortem

Imagine this adapter failed six months after launch.

| Failure mode | Trigger | Early warning sign | Mitigation |
|---|---|---|---|
| Verification theater on the live spike | "Phase 2 COMPLETE" cited without a live-API row | Ledger has no LSMITH-INT-001 row; `C-LSMITH-DEFER-001` relabeled VERIFIED | Keep `C-LSMITH-DEFER-001` DEFERRED-VERIFICATION; VER-013 audit |
| Queue backpressure leaks into execution | worker blocks the telemetry caller | `emit()` latency spikes with step latency | LSMITH-UNIT-003 non-blocking timing assertion; bounded drop policy |
| PII leak via metadata passthrough | arbitrary `metadata` dict reaches LangSmith | exported run `extra` contains free-form strings | LSMITH-UNIT-011 allow-list + size cap + digest; default `digest_only` |
| Stale run-id mapping drift | namespace UUID changed post-release | resumed runs create new roots | Freeze `DURABLEFLOW_LANGSMITH_NAMESPACE`; LSMITH-UNIT-008 |
| Golden-path-only tests | only happy event mapped | no adversarial/overflow/auth cases | Pair every positive case with a negative/adversarial case (§15.1 note) |
| Import cycle from core into adapter | `src/engine.py` imports `integrations` | architecture test fails | LSMITH-CTX-003 import lint; generic protocols only in core |

## 21. Implementation Phases

Phase completion follows §Exit Gates. A phase's "implemented" status is a claim; it advances to COMPLETE only when every constituent claim in §Verification Plan carries a current VERIFIED ledger row. Phase numbers below match §Verification Plan claim prefixes only loosely; each phase's claims are listed in §18.1.

### Phase 1: Local Sink Interface

- Add `TelemetrySink`.
- Add sink fan-out to `TelemetryLogger`.
- Catch and locally warn on sink exceptions.
- Add no-op sink tests.
- Keep all current behavior unchanged when no sinks are provided.

Claims: C-LSMITH-001. Status: **READY → implement** (network-free, independently reproducible).

### Phase 2: LangSmith Trace Exporter

- Add `integrations.langsmith_adapter`.
- Add optional `langsmith` dependency extra.
- Dynamically import the LangSmith SDK inside the adapter.
- Add bounded asynchronous export queue.
- Add deterministic UUIDv5 run-ID mapping.
- Map workflow events to root and child runs.
- Implement digest-only redaction.
- Add unit tests using the fake client contract (§15.2).
- _DEFERRED:_ Validate the selected LangSmith SDK API for reopening deterministic root runs or creating deterministic linked segment runs against a live endpoint (tracked as `C-LSMITH-DEFER-001`, §16). The compatibility note documenting the validated SDK range is written only when this claim moves to VERIFIED.

Claims: C-LSMITH-002 … C-LSMITH-008, C-LSMITH-011, C-LSMITH-012. Status: **READY → implement** (network-free scope). `C-LSMITH-DEFER-001` is **DEFERRED-VERIFICATION** and does not block the network-free COMPLETE verdict.

### Phase 3: Context Audit Export

- Add a generic context exporter hook invoked by workflow orchestration after context decision linking.
- Export `ContextAudit` summaries incrementally after decisions and again at workflow completion.
- Add stable schema for context-lineage payloads.
- Verify that raw content is omitted by default.

Claims: C-LSMITH-007, C-LSMITH-009. Status: **READY → implement**.

### Phase 4: Dataset Export

- Add `context.cli` support for creating LangSmith datasets from selected DurableFlow runs.
- Start with deterministic examples only.
- Implement the documented dataset schema and example shape.
- Document how teams can attach evaluators outside the core runtime.

Claims: C-LSMITH-010. Status: **READY → implement**.

## 22. Resolved Design Decisions

- Resumed workflows should append to the original LangSmith root run when the client supports it, using a deterministic UUID derived from `workflow_id`.
- Live LangSmith SDK run-update validation is required to firm the root-run reopening claim, but is gated behind credentials/network and recorded as `C-LSMITH-DEFER-001` (DEFERRED-VERIFICATION); until then the adapter is validated against the documented `FakeLangSmithClient` contract. If direct reopening proves unstable under live validation, deterministic linked segment runs are the supported fallback.
- The generic `TelemetrySink` protocol should live in `src/telemetry.py`; LangSmith-specific code should live in `integrations/langsmith_adapter.py`.
- Core code should never import the LangSmith adapter; optional user setup or CLI code should lazy-import it only when enabled.
- The default `digest_only` export should include operational metadata, digests, counts, ranks, and scores while redacting raw user text and raw model I/O.
- Metadata export should be allow-list based, size-capped, and sanitized before enqueue.
- Context audit export should be incremental after every decision, with a final completion export, triggered by a generic orchestration hook after `ContextLedger` decision linking.
- `model_fallback` should be represented as metadata or a custom event inside the current step span, with optional model-attempt sub-runs under that same step.
- LangSmith retention is independent of local SQLite deletion; local deletion does not cascade to LangSmith.
- The first adapter should use in-memory retry only; persistent export queues are out of scope.

## 23. Remaining Open Questions

- Should dropped export counters be exposed only as local warnings, or also as DurableFlow telemetry events? (Current decision: expose as adapter counters + stderr warnings; emitting them back into `TelemetryLogger` would recurse through the same sink and is therefore excluded.)
- Should a future explicit `raw` redaction mode exist, or should raw payload export remain out of scope permanently? (If added, it requires an explicit opt-in flag and a separate compliance review; it would be a new DEFERRED claim, never a default.)

## 24. Recommended Positioning

DurableFlow should describe LangSmith integration as:

> Optional export of DurableFlow's local execution and context-lineage records into LangSmith for production trace inspection and evaluation workflows.

That wording keeps the boundary clear: LangSmith observes and evaluates; DurableFlow executes, checkpoints, gates, and records the local audit trail.

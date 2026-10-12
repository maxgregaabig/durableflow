# Proposal: OpenTelemetry Adapter for DurableFlow

**Status:** PROPOSED
**Scope:** Optional workflow telemetry export through OpenTelemetry traces.
**Owner:** Marcos Polanco
**Dependency policy:** Core DurableFlow remains Python standard library only. OpenTelemetry packages live behind an optional extra and are imported only when explicitly enabled.
**Core principle:** DurableFlow must continue to run locally with no API keys, no network calls, and no observability backend.

## 1. Recommendation

DurableFlow should add OpenTelemetry support as an optional telemetry sink.

The adapter should let operators enable vendor-neutral trace export with environment variables, while preserving DurableFlow's local-first execution model. OpenTelemetry should not replace the local JSONL telemetry stream, SQLite workflow records, context ledger, or the existing optional LangSmith adapter.

Recommended operator experience:

```bash
DURABLEFLOW_OTEL_ENABLED=true
OTEL_SERVICE_NAME=durableflow
OTEL_TRACES_EXPORTER=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

This mirrors the convenience other agentic frameworks provide, but keeps export explicit. Setting arbitrary `OTEL_*` variables should not silently activate network export unless `DURABLEFLOW_OTEL_ENABLED=true` is also present.

## 2. Why This Fits DurableFlow

DurableFlow already has the right integration boundary:

- `src.telemetry.TelemetryLogger` records structured workflow events.
- `src.telemetry.TelemetrySink` provides a generic downstream fan-out protocol.
- `integrations/langsmith_adapter.py` proves the optional-adapter pattern: lazy imports, best-effort export, no core dependency, redacted payloads, and local records as source of truth.

OpenTelemetry is a natural second adapter because it is vendor-neutral. It lets teams send DurableFlow traces to Grafana Tempo, Honeycomb, Datadog, New Relic, Jaeger-compatible systems, or an OpenTelemetry Collector without making DurableFlow choose a production observability vendor.

## 3. Goals

1. Export DurableFlow workflow and step telemetry as OpenTelemetry traces.
2. Support standard OpenTelemetry environment variables for exporter, endpoint, service name, resource attributes, sampling, and batch processing.
3. Preserve zero-dependency local execution when the adapter is disabled.
4. Keep workflow execution independent of telemetry backend availability.
5. Avoid raw prompt, user-content, model-output, credential, or PII export by default.
6. Maintain stable workflow/step identity so resumed workflows remain understandable in external trace tools.

## 4. Non-Goals

- No required OpenTelemetry dependency in base install.
- No replacement for `TelemetryLogger`, SQLite, context ledger, eval artifacts, or LangSmith.
- No automatic export merely because an OTLP endpoint happens to exist in the environment.
- No vendor-specific SDKs in the first implementation.
- No full distributed trace propagation across every tool and provider call in the first phase.
- No metrics or logs export in phase one; traces only.

## 5. Environment Policy

Use a DurableFlow-specific switch for activation:

| Variable | Meaning |
|---|---|
| `DURABLEFLOW_OTEL_ENABLED` | Enables OpenTelemetry export when set to `true`, `1`, `yes`, or `on`. |
| `DURABLEFLOW_OTEL_REDACTION` | Optional. Defaults to `digest_only`; future values may allow controlled metadata export. |
| `OTEL_SERVICE_NAME` | Standard OpenTelemetry service name. Defaults to `durableflow` if unset. |
| `OTEL_RESOURCE_ATTRIBUTES` | Standard OpenTelemetry resource attributes. |
| `OTEL_TRACES_EXPORTER` | Standard OpenTelemetry trace exporter selection. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Standard OTLP endpoint, usually an OpenTelemetry Collector. |
| `OTEL_TRACES_SAMPLER` | Standard trace sampler selection. |
| `OTEL_SDK_DISABLED` | Standard OpenTelemetry kill switch. If `true`, export must be disabled. |

Rationale: OpenTelemetry's own configuration model is broad. In a project whose positioning emphasizes local-first execution and privacy, DurableFlow should require explicit DurableFlow consent before network export.

## 6. Proposed Architecture

Add a new module:

```text
integrations/opentelemetry_adapter.py
```

Expose:

```python
def opentelemetry_enabled_from_env(env: dict[str, str] | None = None) -> bool: ...

class OpenTelemetryConfig:
    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "OpenTelemetryConfig": ...

class OpenTelemetryTelemetrySink:
    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "OpenTelemetryTelemetrySink | None": ...
    def emit(self, event: dict[str, Any]) -> None: ...
    def flush(self, timeout: float = 5.0) -> bool: ...
    def close(self) -> None: ...
```

Core code should not import this module. Entry points or future CLI setup code should compose sinks:

```python
from src.telemetry import TelemetryLogger


def build_telemetry() -> TelemetryLogger:
    sinks = []

    if opentelemetry_enabled_from_env():
        from integrations.opentelemetry_adapter import OpenTelemetryTelemetrySink

        sink = OpenTelemetryTelemetrySink.from_env()
        if sink is not None:
            sinks.append(sink)

    return TelemetryLogger(echo=True, sinks=sinks)
```

## 7. Trace Mapping

Represent each DurableFlow workflow as a trace with a root span and step spans.

| DurableFlow event | OpenTelemetry shape |
|---|---|
| `step_start` | Start or record a step span named after `step_name`. |
| `step_complete` | End/update the step span with duration, cost, model, and status attributes. |
| `approval_requested` | Add a span event named `approval_requested` with redacted gate metadata. |
| `approval_decision` | Add a span event named `approval_decision`. |
| `model_fallback` | Add a span event named `model_fallback` with from/to model metadata. |
| `crash_detected` | Add a root span event named `crash_detected`. |
| `workflow_resumed` | Add a root span event named `workflow_resumed`. |
| `workflow_complete` | End/update the root span with workflow summary attributes. |

Suggested span attributes:

| Attribute | Example |
|---|---|
| `durableflow.workflow_id` | `wf-context-demo` |
| `durableflow.step_name` | `classify_email` |
| `durableflow.event_type` | `step_complete` |
| `durableflow.cost_usd` | `0.00042` |
| `durableflow.model_used` | `mock-primary` |
| `durableflow.fallback_count` | `1` |
| `durableflow.approval_wait_events` | `1` |

Raw metadata should be allowlisted and redacted before it becomes span attributes or span events.

## 8. Resumed Workflow Semantics

DurableFlow workflows may crash and resume in a new process. OpenTelemetry span lifecycles are usually process-local, so the first implementation should be honest about this boundary:

- Local SQLite and JSONL remain the authoritative continuity record.
- The adapter should include stable `durableflow.workflow_id` attributes on every span.
- If a workflow resumes in a new process, external trace tools may show separate exported traces unless the backend supports linking or explicit trace IDs.
- A later phase may add deterministic trace ID generation or span links if the chosen OpenTelemetry SDK path supports it safely.

This is weaker than the LangSmith adapter's deterministic UUIDv5 run mapping, but it avoids over-promising cross-process span continuity before verifying backend behavior.

## 9. Privacy And Redaction

Default export mode should be `digest_only`.

Allowed by default:

- workflow IDs and step names;
- event type;
- latency and cost;
- model names;
- fallback routing metadata;
- approval gate IDs and decisions;
- counts, booleans, and low-cardinality status values.

Not allowed by default:

- raw prompts;
- raw user text;
- raw model responses;
- email bodies or customer records;
- secrets, API keys, bearer tokens, cookies, or credentials;
- arbitrary tool outputs.

The adapter should enforce size limits and attribute allowlists independently of the OpenTelemetry SDK.

## 10. Failure Semantics

OpenTelemetry export must be best-effort:

1. Disabled configuration returns `None` and performs no imports of optional SDK packages.
2. Missing OpenTelemetry SDK returns `None`, not an exception.
3. Exporter failures must not fail a workflow step.
4. Slow exporters must not block checkpointing, approval handling, or side-effect logging.
5. Queue overflows should drop export events and increment counters.
6. `OTEL_SDK_DISABLED=true` must disable export even if `DURABLEFLOW_OTEL_ENABLED=true`.

The adapter should expose counters similar to the LangSmith adapter:

- `dropped_events`
- `failed_exports`
- `exported_events`
- `disabled`

## 11. Dependency Plan

Add an optional dependency group:

```toml
[project.optional-dependencies]
opentelemetry = [
    "opentelemetry-api>=1.0,<2.0",
    "opentelemetry-sdk>=1.0,<2.0",
    "opentelemetry-exporter-otlp>=1.0,<2.0",
]
```

The exact lower bound should be set to the oldest version verified by tests. The upper bound should protect the project from a breaking 2.x release.

## 12. Implementation Phases

### Phase 1: Adapter Skeleton

- Add `integrations/opentelemetry_adapter.py`.
- Implement env parsing and disabled/no-SDK behavior.
- Add optional dependency group.
- Add `.env.example` documentation.
- Add unit tests that require no network and no collector.

### Phase 2: Trace Export

- Map `TelemetryLogger` events to spans and span events.
- Add redaction and allowlist tests.
- Add non-blocking/export-failure tests.
- Verify `OTEL_SDK_DISABLED=true` disables export.

### Phase 3: Local Collector Smoke Test

- Add an optional manual smoke test using an OpenTelemetry Collector or console exporter.
- Keep it excluded from normal CI unless explicitly enabled.
- Document expected output and limitations around resumed workflows.

### Phase 4: Distributed Context And Links

- Investigate deterministic trace IDs, span links, or context propagation across workflow resumes.
- Add tool/provider child spans only if the extra detail improves operator understanding without leaking sensitive payloads.

## 13. Test Plan

Network-free tests:

- `opentelemetry_enabled_from_env({}) is False`
- enabled without SDK returns `None`
- `OTEL_SDK_DISABLED=true` disables export
- invalid redaction mode falls back to `digest_only`
- sink fan-out receives normal `TelemetryLogger` event dicts
- redaction removes raw/unknown metadata keys
- span mapping produces stable names and attributes with fake tracer/provider
- exporter failure does not propagate into `TelemetryLogger.log`
- oversize events are dropped and counted

Optional integration test:

- gated by `DURABLEFLOW_OTEL_INTEGRATION=true`
- exports a small workflow to a local collector or console exporter
- verifies at least one workflow span and one step span are emitted

## 14. Risks

| Risk | Mitigation |
|---|---|
| Silent data export surprises local users | Require `DURABLEFLOW_OTEL_ENABLED=true`. |
| Sensitive metadata leaks into traces | Default `digest_only`, metadata allowlist, size limits. |
| OpenTelemetry SDK blocks workflow execution | Use batch processor defaults where possible; keep sink failure-isolated. |
| Resumed workflows appear as separate traces | Document phase-one limitation; preserve workflow ID attributes; evaluate span links later. |
| Dependency churn destabilizes base install | Optional extra only; no core imports. |
| Vendor-specific conventions creep in | Use generic OTLP/OpenTelemetry APIs only. |

## 15. Decision

Proceed with an optional OpenTelemetry adapter.

The implementation should match the LangSmith adapter's architectural posture: optional dependency, lazy import, explicit enablement, best-effort export, redacted payloads, and local records as the source of truth. The main product benefit is interoperability: DurableFlow can plug into existing production observability stacks while preserving its durability and auditability boundaries.

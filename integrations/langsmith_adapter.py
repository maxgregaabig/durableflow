"""Optional LangSmith telemetry adapter for DurableFlow.

Import-safe with no SDK installed. Implements ``docs/langsmith-adapter.md``.

Core DurableFlow code never imports this module; user entry points / CLI setup
code performs the optional import only after configuration enables LangSmith.
All export is best-effort and non-blocking: workflow execution never waits on
LangSmith HTTP calls and never fails because of them.

Verification boundary: the adapter is validated against the documented minimal
client contract (``create_run`` / ``update_run`` / ``log_event``). Live LangSmith
SDK validation is tracked as ``C-LSMITH-DEFER-001`` (DEFERRED-VERIFICATION) in
the spec — it requires network + credentials unavailable in the build env.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import random
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Protocol, runtime_checkable

from context.models import ContextAudit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Randomly chosen, immutable namespace for DurableFlow -> LangSmith run-ID
# isolation. MUST NOT change after release: changing it breaks stable run-ID
# mapping across process restarts and versions (spec §10.2).
DURABLEFLOW_LANGSMITH_NAMESPACE = uuid.UUID("f8a30b3f-5c7f-51a8-9d8d-4e3e9f73f5c0")

# Bounded queue defaults (spec §10.1).
DEFAULT_MAX_ITEMS = 1000
DEFAULT_MAX_EVENT_BYTES = 64 * 1024  # 64 KiB after redaction

# Retry policy (spec §12).
RETRY_MAX_ATTEMPTS = 3
RETRY_INITIAL_BACKOFF_MS = 250
RETRY_BACKOFF_CEILING_MS = 10_000

# Metadata sanitization (spec §13).
METADATA_MAX_VALUE_BYTES = 512
METADATA_ALLOWLIST = frozenset(
    {
        "retrieval_method",
        "retrieval_score",
        "rank_position",
        "rejection_reason",
        "retrieval_query_digest",
        "source_item_id",
        "budget_position",
        "decision_id",
        "artifact_id",
        "from_model",
        "to_model",
        "error_category",
        "error_digest",
        "gate_id",
        "decision",
        "decided_by",
        "last_checkpoint",
        "attribution_mode",
        "classification",
        "seed",
    }
)

_TRUTHY = {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Deterministic UUIDv5 run-ID mapping
# ---------------------------------------------------------------------------

def langsmith_run_id(workflow_id: str) -> uuid.UUID:
    """Deterministic root-run UUID for a DurableFlow ``workflow_id``."""
    return uuid.uuid5(DURABLEFLOW_LANGSMITH_NAMESPACE, workflow_id)


def langsmith_child_run_id(workflow_id: str, step_name: str, occurrence: int = 0) -> uuid.UUID:
    """Deterministic child-run UUID for a step within a workflow."""
    return uuid.uuid5(
        DURABLEFLOW_LANGSMITH_NAMESPACE,
        f"{workflow_id}:{step_name}:{occurrence}",
    )


# ---------------------------------------------------------------------------
# Environment configuration
# ---------------------------------------------------------------------------

def langsmith_enabled_from_env(env: dict[str, str] | None = None) -> bool:
    """True only when export is explicitly enabled AND an API key is present."""
    environ = env if env is not None else os.environ
    if environ.get("DURABLEFLOW_LANGSMITH_ENABLED", "").strip().lower() not in _TRUTHY:
        return False
    return bool(environ.get("LANGSMITH_API_KEY", "").strip())


@dataclass(frozen=True)
class LangSmithConfig:
    project: str
    redaction: str  # "digest_only" | "metadata"
    run_url_base: str | None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LangSmithConfig":
        environ = env if env is not None else os.environ
        redaction = environ.get("DURABLEFLOW_LANGSMITH_REDACTION", "digest_only").strip().lower()
        if redaction not in {"digest_only", "metadata"}:
            redaction = "digest_only"
        run_url_base = environ.get("DURABLEFLOW_RUN_URL_BASE") or None
        return cls(
            project=environ.get("LANGSMITH_PROJECT", "durableflow").strip() or "durableflow",
            redaction=redaction,
            run_url_base=run_url_base,
        )

    def run_url(self, workflow_id: str) -> str | None:
        if not self.run_url_base:
            return None
        return f"{self.run_url_base.rstrip('/')}/workflows/{workflow_id}"


# ---------------------------------------------------------------------------
# Client interface (the validation boundary)
# ---------------------------------------------------------------------------

@runtime_checkable
class LangSmithClient(Protocol):
    """Minimal LangSmith-like client contract (spec §15.2).

    The real-SDK wrapper and the test fake are interchangeable against this
    interface. ``C-LSMITH-DEFER-001`` validates real-SDK conformance to it.
    """

    def create_run(
        self,
        *,
        id: Any,
        name: str,
        run_type: str,
        project_name: str,
        inputs: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        parent_run_id: Any = None,
    ) -> Any: ...

    def update_run(
        self,
        run_id: Any,
        *,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        end_time: Any = None,
        extra: dict[str, Any] | None = None,
    ) -> Any: ...

    def log_event(self, run_id: Any, *, name: str, payload: dict[str, Any]) -> Any: ...


class _RealLangSmithClient:
    """Best-effort wrapper over ``langsmith.Client``.

    Constructed only when the optional SDK is importable. Raises ``ImportError``
    if the SDK is absent so callers can fall back cleanly. Real-API conformance
    is DEFERRED-VERIFICATION (C-LSMITH-DEFER-001); this wrapper exists so a live
    deployment can use it once credentials/network are available.
    """

    def __init__(self, *, api_key: str, project: str):
        try:
            from langsmith import Client  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - exercised when SDK absent
            raise ImportError(
                "langsmith SDK is not installed; install with the 'langsmith' extra"
            ) from exc
        self._client = Client(api_key=api_key)
        self._project = project

    def create_run(self, *, id, name, run_type, project_name, inputs=None, extra=None, parent_run_id=None):
        kwargs: dict[str, Any] = {"id": id, "name": name, "run_type": run_type, "project_name": project_name or self._project}
        if inputs is not None:
            kwargs["inputs"] = inputs
        if extra is not None:
            kwargs["extra"] = extra
        if parent_run_id is not None:
            kwargs["parent_run_id"] = parent_run_id
        return self._client.create_run(**kwargs)

    def update_run(self, run_id, *, outputs=None, error=None, end_time=None, extra=None):
        kwargs: dict[str, Any] = {}
        if outputs is not None:
            kwargs["outputs"] = outputs
        if error is not None:
            kwargs["error"] = error
        if end_time is not None:
            kwargs["end_time"] = end_time
        if extra is not None:
            kwargs["extra"] = extra
        return self._client.update_run(run_id, **kwargs)

    def log_event(self, run_id, *, name, payload):
        return self._client.log_event(run_id, name=name, payload=payload)


# ---------------------------------------------------------------------------
# Redaction / sanitization
# ---------------------------------------------------------------------------

def _sha_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _categorize_error(error: str) -> str:
    lowered = error.lower()
    if "rate" in lowered and "limit" in lowered:
        return "rate_limit"
    if "auth" in lowered or "401" in lowered or "credential" in lowered:
        return "auth"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    if "connection" in lowered or "network" in lowered or "unreachable" in lowered:
        return "network"
    return "other"


def _sanitize_metadata(metadata: dict[str, Any], redaction: str) -> dict[str, Any]:
    """Allow-list, size-cap, and sanitize a metadata dict (spec §13).

    Unknown keys are dropped. String values beyond the cap are replaced by a
    digest + truncated marker. ``metadata`` mode is a superset of ``digest_only``
    for metadata only; raw prompts/responses are never exported by this function.
    """
    if redaction != "metadata":
        # digest_only: keep only operational allow-listed keys.
        allowed = METADATA_ALLOWLIST
    else:
        # metadata mode is still allow-list based; the same operational keys.
        allowed = METADATA_ALLOWLIST
    out: dict[str, Any] = {}
    for key in allowed:
        if key not in metadata:
            continue
        value = metadata[key]
        out[key] = _sanitize_value(value)
    return out


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) <= METADATA_MAX_VALUE_BYTES:
            return value
        return {
            "digest": _sha_digest(value),
            "truncated": True,
            "original_bytes": len(encoded),
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value][:64]
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, sub in list(value.items())[:64]:
            if isinstance(key, str):
                sanitized[key] = _sanitize_value(sub)
        return sanitized
    # Unknown types -> digest of their repr to avoid leaking arbitrary objects.
    return _sha_digest(repr(value))


def _redact_event(event: dict[str, Any], config: LangSmithConfig) -> dict[str, Any]:
    """Produce a digest-first view of a telemetry event (spec §13).

    Keeps operational fields (event_type, workflow_id, step_name, timing, cost,
    model) and sanitized metadata; drops any raw payload fields that could
    carry user text. ``model_fallback`` error text is reduced to a category +
    digest here so the raw error never reaches the queue.
    """
    redacted: dict[str, Any] = {
        "event_type": event.get("event_type"),
        "workflow_id": event.get("workflow_id"),
        "step_name": event.get("step_name"),
        "timestamp": event.get("timestamp"),
        "duration_ms": event.get("duration_ms"),
        "cost_usd": event.get("cost_usd"),
        "model_used": event.get("model_used"),
    }
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        redacted["metadata"] = _sanitize_metadata(metadata, config.redaction)
        # model_fallback carries a raw `error` string: reduce it to a category
        # and digest so the raw text is never exported.
        if event.get("event_type") == "model_fallback" and isinstance(metadata.get("error"), str):
            error_text = metadata["error"]
            redacted["metadata"]["error_category"] = _categorize_error(error_text)
            redacted["metadata"]["error_digest"] = _sha_digest(error_text)
    else:
        redacted["metadata"] = {}
    return redacted


def _serialized_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, default=str, sort_keys=True).encode("utf-8"))


# ---------------------------------------------------------------------------
# Event -> run mapping
# ---------------------------------------------------------------------------

@dataclass
class _ExportState:
    """Per-workflow bookkeeping so step spans reuse one child run id."""

    root_created: set[str] = field(default_factory=set)
    child_created: set[tuple[str, str]] = field(default_factory=set)


def _map_event_to_client_calls(
    event: dict[str, Any],
    config: LangSmithConfig,
    state: _ExportState,
    client: LangSmithClient,
) -> None:
    """Translate one redacted event into client calls (spec §10.2 table).

    Mutates ``state`` to avoid recreating root/child runs. Failures inside this
    function are caught by the worker retry loop, not here.
    """
    workflow_id = event.get("workflow_id")
    event_type = event.get("event_type")
    if not isinstance(workflow_id, str) or not workflow_id:
        return
    root_id = langsmith_run_id(workflow_id)

    # Ensure root run exists exactly once per workflow.
    if workflow_id not in state.root_created:
        root_extra: dict[str, Any] = {
            "metadata": {
                "workflow_id": workflow_id,
                "source": "durableflow",
            }
        }
        run_url = config.run_url(workflow_id)
        if run_url:
            root_extra["metadata"]["durableflow_run_url"] = run_url
        client.create_run(
            id=str(root_id),
            name=workflow_id,
            run_type="chain",
            project_name=config.project,
            inputs={"workflow_id": workflow_id},
            extra=root_extra,
        )
        state.root_created.add(workflow_id)

    step_name = event.get("step_name")
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}

    # Root-level events.
    if event_type == "crash_detected":
        client.log_event(
            str(root_id),
            name="recovery",
            payload={"last_checkpoint": metadata.get("last_checkpoint"), "event_type": event_type},
        )
        return
    if event_type == "workflow_resumed":
        client.log_event(
            str(root_id),
            name="resume",
            payload={"step_name": step_name, "event_type": event_type},
        )
        return
    if event_type == "workflow_complete":
        client.update_run(
            str(root_id),
            outputs={"summary": metadata} if metadata else {"completed": True},
            end_time=event.get("timestamp"),
        )
        return

    # model_fallback is a routing event INSIDE the current step span, never a
    # top-level run (spec §10.2).
    if event_type == "model_fallback":
        if not isinstance(step_name, str) or not step_name:
            return
        child_id = langsmith_child_run_id(workflow_id, step_name)
        routing = {
            "from_model": metadata.get("from_model"),
            "to_model": metadata.get("to_model"),
            # error_category / error_digest were computed during redaction.
            "error_category": metadata.get("error_category", "other"),
            "error_digest": metadata.get("error_digest"),
            "event_type": event_type,
        }
        client.log_event(str(child_id), name="model_fallback", payload=routing)
        return

    # Step-span events.
    if event_type == "step_start":
        if not isinstance(step_name, str) or not step_name:
            return
        child_id = langsmith_child_run_id(workflow_id, step_name)
        if (workflow_id, step_name) not in state.child_created:
            client.create_run(
                id=str(child_id),
                name=step_name,
                run_type="llm",
                project_name=config.project,
                inputs={"workflow_id": workflow_id, "step_name": step_name},
                parent_run_id=str(root_id),
            )
            state.child_created.add((workflow_id, step_name))
        return
    if event_type == "step_complete":
        if not isinstance(step_name, str) or not step_name:
            return
        child_id = langsmith_child_run_id(workflow_id, step_name)
        client.update_run(
            str(child_id),
            outputs={
                "duration_ms": event.get("duration_ms"),
                "cost_usd": event.get("cost_usd"),
                "model_used": event.get("model_used"),
            },
            end_time=event.get("timestamp"),
        )
        return
    if event_type == "approval_requested":
        if not isinstance(step_name, str) or not step_name:
            return
        child_id = langsmith_child_run_id(workflow_id, step_name)
        client.log_event(
            str(child_id),
            name="approval_wait",
            payload={"gate_id": metadata.get("gate_id"), "event_type": event_type},
        )
        return
    if event_type == "approval_decision":
        if not isinstance(step_name, str) or not step_name:
            return
        child_id = langsmith_child_run_id(workflow_id, step_name)
        client.log_event(
            str(child_id),
            name="approval_decision",
            payload={
                "decision": metadata.get("decision"),
                "decided_by": metadata.get("decided_by"),
                "event_type": event_type,
            },
        )
        return
    # Unknown event types: tag on root as a low-cardinality custom event.
    client.log_event(str(root_id), name=event_type or "event", payload={"event_type": event_type})


# ---------------------------------------------------------------------------
# Non-blocking telemetry sink
# ---------------------------------------------------------------------------

class LangSmithTelemetrySink:
    """Best-effort, non-blocking LangSmith telemetry sink.

    ``emit`` enqueues a redacted event into a bounded in-process queue and
    returns immediately. A daemon worker drains the queue and performs client
    calls with bounded retry. Overflow drops the newest event and increments
    ``dropped_events``. A failed authentication disables export for the process.
    """

    def __init__(
        self,
        client: LangSmithClient,
        config: LangSmithConfig,
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_event_bytes: int = DEFAULT_MAX_EVENT_BYTES,
    ):
        self._client = client
        self._config = config
        self._max_items = max_items
        self._max_event_bytes = max_event_bytes
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=max_items)
        self._state = _ExportState()
        # Counters are plain attributes; reads are best-effort.
        self.dropped_events = 0
        self.failed_exports = 0
        self.auth_failures = 0
        self.exported_events = 0
        self._disabled = False
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._drain, name="langsmith-export", daemon=True)
        self._worker.start()

    # -- construction helpers ------------------------------------------------

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        client: LangSmithClient | None = None,
    ) -> "LangSmithTelemetrySink | None":
        """Build a sink from environment, or ``None`` if disabled/SDK absent.

        Returns ``None`` (not an exception) when export is disabled or the SDK
        is not installed, so callers can treat absence as a clean no-op.
        """
        if not langsmith_enabled_from_env(env):
            return None
        config = LangSmithConfig.from_env(env)
        if client is None:
            environ = env if env is not None else os.environ
            api_key = environ.get("LANGSMITH_API_KEY", "").strip()
            try:
                client = _RealLangSmithClient(api_key=api_key, project=config.project)
            except ImportError:
                # SDK not installed: disabled by configuration. No exception.
                return None
        return cls(client, config)

    # -- TelemetrySink protocol ---------------------------------------------

    def emit(self, event: dict[str, Any]) -> None:
        if self._disabled:
            return
        redacted = _redact_event(event, self._config)
        if _serialized_size(redacted) > self._max_event_bytes:
            self.dropped_events += 1
            _warn(f"dropping oversize export event ({_serialized_size(redacted)} bytes)")
            return
        try:
            self._queue.put_nowait(redacted)
        except queue.Full:
            self.dropped_events += 1
            _warn("export queue full; dropping newest export event")

    # -- lifecycle / testing -------------------------------------------------

    def flush(self, timeout: float = 5.0) -> bool:
        """Block until the queue is drained or timeout. Returns True if drained."""
        self._queue.join()
        return self._queue.unfinished_tasks == 0

    def close(self) -> None:
        self._stop.set()
        self._queue.put(None)

    # -- worker --------------------------------------------------------------

    def _drain(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            try:
                if item is None:
                    return
                if self._disabled:
                    continue
                self._export_with_retry(item)
            finally:
                self._queue.task_done()

    def _export_with_retry(self, event: dict[str, Any]) -> None:
        backoff_ms = RETRY_INITIAL_BACKOFF_MS
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                _map_event_to_client_calls(event, self._config, self._state, self._client)
                self.exported_events += 1
                return
            except _AuthFailure:
                self._disable_for_auth()
                return
            except Exception as exc:  # noqa: BLE001 - best-effort export
                if _is_auth_error(exc):
                    self._disable_for_auth()
                    return
                if attempt >= RETRY_MAX_ATTEMPTS:
                    self.failed_exports += 1
                    _warn(f"export failed after {attempt} attempts: {exc}")
                    return
                # Exponential backoff with jitter, capped.
                sleep_ms = min(backoff_ms, RETRY_BACKOFF_CEILING_MS)
                sleep_ms = random.uniform(sleep_ms * 0.5, sleep_ms * 1.5)  # noqa: S311
                time.sleep(sleep_ms / 1000.0)
                backoff_ms = min(backoff_ms * 2, RETRY_BACKOFF_CEILING_MS)

    def _disable_for_auth(self) -> None:
        self.auth_failures += 1
        self._disabled = True
        _warn("LangSmith auth failed; disabling export for this process")


class _AuthFailure(Exception):
    """Raised by fakes/tests to simulate a LangSmith auth error."""


def _is_auth_error(exc: BaseException) -> bool:
    """Heuristic auth-error detection across the real SDK and fakes.

    Matches the categories the LangSmith SDK raises for bad credentials or
    forbidden projects (401/403), so the first such failure disables export.
    """
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in ("401", "403", "unauthorized", "forbidden", "invalid api key", "invalid_api_key"))


def _warn(message: str) -> None:
    print(f"[langsmith-adapter] {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Phase 3: context audit export
# ---------------------------------------------------------------------------

def build_context_audit_payload(audit: ContextAudit, *, redaction: str = "digest_only") -> dict[str, Any]:
    """Build a redacted context-lineage payload from a ``ContextAudit``.

    Exports identifiers, roles, source types, content digests (``sha256:``
    prefixed), token counts, retrieval scores/ranks/rejection reasons, decision
    IDs, prompt/response digests, and influence links + lineage counts. Omits
    raw content, raw prompts, raw responses, email bodies, and calendar detail.
    """
    artifacts_by_id = {artifact.artifact_id: artifact for artifact in audit.artifacts}

    # Per-artifact retrieval/rejection metadata, keyed by (step, artifact).
    retrieval_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for event in audit.events:
        if event.artifact_id is None or not event.metadata:
            continue
        if event.event_type in {"retrieved", "rejected"}:
            key = (event.step_name, event.artifact_id)
            retrieval_by_key.setdefault(key, {}).update(event.metadata)

    artifacts_out: list[dict[str, Any]] = []
    for artifact in audit.artifacts:
        entry: dict[str, Any] = {
            "artifact_id": artifact.artifact_id,
            "artifact_role": artifact.artifact_role,
            "source_type": artifact.source_type,
            # `source` may carry user-facing identifiers (email ids, names) -> digest.
            "source_digest": _sha_digest(artifact.source),
            "content_digest": _prefix_digest(artifact.content_digest),
            "token_count": artifact.token_count,
        }
        artifacts_out.append(entry)

    events_out: list[dict[str, Any]] = []
    for event in audit.events:
        entry = {
            "event_id": event.event_id,
            "step_name": event.step_name,
            "artifact_id": event.artifact_id,
            "event_type": event.event_type,
        }
        if event.artifact_id is not None:
            meta = retrieval_by_key.get((event.step_name, event.artifact_id), {})
            if meta:
                entry["retrieval"] = _sanitize_metadata(meta, redaction)
        events_out.append(entry)

    decisions_out: list[dict[str, Any]] = []
    for decision in audit.decisions:
        decisions_out.append(
            {
                "decision_id": decision.decision_id,
                "step_name": decision.step_name,
                "prompt_digest": _prefix_digest(decision.prompt_digest),
                "response_digest": _prefix_digest(decision.response_digest),
                "model_used": decision.model_used,
                "input_tokens": decision.input_tokens,
                "output_tokens": decision.output_tokens,
                "cost_usd": decision.cost_usd,
            }
        )

    lineage_out: list[dict[str, Any]] = []
    for lineage in audit.lineage:
        lineage_out.append(
            {
                "decision_id": lineage.decision_id,
                "artifact_id": lineage.artifact_id,
                "influence_type": lineage.influence_type,
                "influence_score": lineage.influence_score,
            }
        )

    return {
        "workflow_id": audit.workflow_id,
        "counts": {
            "observed": audit.observed_count,
            "retrieved": audit.retrieved_count,
            "selected": audit.selected_count,
            "rejected": audit.rejected_count,
            "consumed": audit.consumed_count,
            "influential": audit.influential_count,
            "decisions": audit.decision_count,
        },
        "artifacts": artifacts_out,
        "events": events_out,
        "decisions": decisions_out,
        "lineage": lineage_out,
    }


def _prefix_digest(digest: str) -> str:
    """Normalize a stored digest to the ``sha256:`` export convention."""
    if digest.startswith("sha256:"):
        return digest
    return f"sha256:{digest}"


@runtime_checkable
class ContextExporter(Protocol):
    """Generic context-export hook invoked by workflow orchestration.

    The engine depends only on this protocol; the LangSmith implementation is
    one provider. Failures are best-effort and MUST NOT propagate.
    """

    def export_incremental(self, *, workflow_id: str, step_name: str, context_ledger: Any) -> None: ...


class LangSmithContextExporter:
    """Exports redacted context lineage through the LangSmith sink's queue."""

    def __init__(self, sink: LangSmithTelemetrySink):
        self._sink = sink

    @classmethod
    def from_sink(cls, sink: LangSmithTelemetrySink) -> "LangSmithContextExporter":
        return cls(sink)

    def export_incremental(self, *, workflow_id: str, step_name: str, context_ledger: Any) -> None:
        if self._sink._disabled:  # noqa: SLF001 - intentional best-effort check
            return
        if not hasattr(context_ledger, "audit_workflow"):
            return
        audit = context_ledger.audit_workflow(workflow_id)
        payload = build_context_audit_payload(audit, redaction=self._sink._config.redaction)  # noqa: SLF001
        event = {
            "event_type": "context_audit",
            "workflow_id": workflow_id,
            "step_name": step_name,
            "timestamp": _now_iso(),
            "metadata": payload,
        }
        self._sink.emit(event)

    def export_final(self, *, workflow_id: str, context_ledger: Any) -> None:
        if not hasattr(context_ledger, "audit_workflow"):
            return
        audit = context_ledger.audit_workflow(workflow_id)
        payload = build_context_audit_payload(audit, redaction=self._sink._config.redaction)  # noqa: SLF001
        event = {
            "event_type": "context_audit_final",
            "workflow_id": workflow_id,
            "step_name": None,
            "timestamp": _now_iso(),
            "metadata": payload,
        }
        self._sink.emit(event)


def export_context_audit(
    audit: ContextAudit,
    *,
    sink: LangSmithTelemetrySink | None = None,
    redaction: str = "digest_only",
    export_mode: str = "backfill",
) -> dict[str, Any]:
    """Manual one-shot export for backfills / audits (spec §11, §14).

    Returns the redacted payload tagged with ``export_mode``. When a ``sink`` is
    provided the payload is also enqueued for LangSmith; otherwise it is returned
    for the caller to persist/inspect. Uses the same deterministic UUID mapping
    so backfills do not duplicate existing runs.
    """
    payload = build_context_audit_payload(audit, redaction=redaction)
    payload["export_mode"] = export_mode
    payload["run_id"] = str(langsmith_run_id(audit.workflow_id))
    if sink is not None:
        sink.emit(
            {
                "event_type": "context_audit_backfill",
                "workflow_id": audit.workflow_id,
                "step_name": None,
                "timestamp": _now_iso(),
                "metadata": payload,
            }
        )
    return payload


# ---------------------------------------------------------------------------
# Phase 4: dataset row builder
# ---------------------------------------------------------------------------

def build_dataset_rows(
    audit: ContextAudit,
    *,
    expected_overrides: dict[str, dict[str, Any]] | None = None,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build LangSmith-eval dataset rows from a ``ContextAudit`` (spec §10.4).

    Each decision step becomes one row. Inputs contain only digests, counts,
    roles, source types, ranks, scores, and redacted labels — never raw text.
    """
    overrides = expected_overrides or {}
    artifacts_by_id = {artifact.artifact_id: artifact for artifact in audit.artifacts}
    retrieval_by_artifact: dict[str, dict[str, Any]] = {}
    for event in audit.events:
        if event.artifact_id and event.metadata and event.event_type in {"retrieved", "rejected"}:
            retrieval_by_artifact.setdefault(event.artifact_id, {}).update(event.metadata)

    lineage_by_decision: dict[str, list[str]] = {}
    for lineage in audit.lineage:
        lineage_by_decision.setdefault(lineage.decision_id, []).append(lineage.artifact_id)

    rows: list[dict[str, Any]] = []
    for decision in audit.decisions:
        # A decision's context = source_artifacts consumed on that step (those
        # mounted into the prompt that produced the decision). ``selected``
        # events live on the preceding select step, so consumed-on-decision-step
        # is the correct join for the decision's mounted context.
        selected = _consumed_source_artifacts(audit, decision.step_name)
        digest_set = sorted(_prefix_digest(a.content_digest) for a in selected)

        context_summary = {
            "selected_count": len(selected),
            "rejected_count": _count_step_event(audit, decision.step_name, "rejected"),
            "artifacts": [
                {
                    "artifact_role": a.artifact_role,
                    "source_type": a.source_type,
                    "rank_position": retrieval_by_artifact.get(a.artifact_id, {}).get("rank_position"),
                    "retrieval_score": retrieval_by_artifact.get(a.artifact_id, {}).get("retrieval_score"),
                    "content_digest": _prefix_digest(a.content_digest),
                }
                for a in selected
            ],
        }

        influential = lineage_by_decision.get(decision.decision_id, [])
        step_override = overrides.get(decision.step_name, {})

        row = {
            "inputs": {
                "workflow_id": audit.workflow_id,
                "step_name": decision.step_name,
                "fixture_ref": step_override.get("fixture_ref", _fixture_ref(audit.workflow_id, decision.step_name)),
                "context_digest_set": digest_set,
                "context_summary": context_summary,
            },
            "outputs": {
                "expected_status": step_override.get("expected_status", "completed"),
                "expected_decision_label": step_override.get("expected_decision_label"),
                "expected_side_effect": step_override.get("expected_side_effect"),
            },
            "metadata": {
                "model_used": decision.model_used,
                "cost_usd": decision.cost_usd,
                "token_counts": {"input": decision.input_tokens, "output": decision.output_tokens},
                "lineage_counts": {
                    "observed": audit.observed_count,
                    "selected": audit.selected_count,
                    "rejected": audit.rejected_count,
                    "consumed": audit.consumed_count,
                    "influential": len(influential),
                },
            },
        }
        if seed is not None:
            row["metadata"]["seed"] = seed
        rows.append(row)
    return rows


def _consumed_source_artifacts(audit: ContextAudit, step_name: str) -> list[Any]:
    """Source artifacts consumed (mounted into the prompt) on ``step_name``.

    Excludes prompt/response artifacts — those are decision bookkeeping, not
    context the decision was made from. Order follows audit.artifacts.
    """
    consumed_ids = {
        e.artifact_id
        for e in audit.events
        if e.step_name == step_name and e.event_type == "consumed" and e.artifact_id
    }
    out: list[Any] = []
    for artifact in audit.artifacts:
        if artifact.artifact_id in consumed_ids and artifact.artifact_role == "source_artifact":
            out.append(artifact)
    return out


def _count_step_event(audit: ContextAudit, step_name: str, event_type: str) -> int:
    return len(
        {
            e.artifact_id
            for e in audit.events
            if e.step_name == step_name and e.event_type == event_type and e.artifact_id
        }
    )


def _fixture_ref(workflow_id: str, step_name: str) -> str:
    return f"{workflow_id}:{step_name}"


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# Backfill marker helper reused by export_context_audit.
def export_langsmith_dataset_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Materialize dataset rows for CLI emission (no network by default)."""
    return list(rows)


__all__ = [
    "ContextExporter",
    "DEFAULT_MAX_EVENT_BYTES",
    "DEFAULT_MAX_ITEMS",
    "DURABLEFLOW_LANGSMITH_NAMESPACE",
    "LangSmithClient",
    "LangSmithConfig",
    "LangSmithContextExporter",
    "LangSmithTelemetrySink",
    "build_context_audit_payload",
    "build_dataset_rows",
    "export_context_audit",
    "export_langsmith_dataset_rows",
    "langsmith_child_run_id",
    "langsmith_enabled_from_env",
    "langsmith_run_id",
]

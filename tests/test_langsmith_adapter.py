"""Network-free tests for the LangSmith adapter (docs/langsmith-adapter.md §15).

Every test uses the documented ``FakeLangSmithClient`` contract (§15.2); none
require network or an API key. Live LangSmith SDK conformance is tracked as
C-LSMITH-DEFER-001 (DEFERRED-VERIFICATION); the gated
``test_live_sdk_roundtrip`` below exercises it only when
``DURABLEFLOW_LANGSMITH_INTEGRATION=1`` and a real API key are present.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from context.ledger import ContextLedger
from integrations.langsmith_adapter import (
    DEFAULT_MAX_EVENT_BYTES,
    DURABLEFLOW_LANGSMITH_NAMESPACE,
    LangSmithConfig,
    LangSmithContextExporter,
    LangSmithTelemetrySink,
    build_context_audit_payload,
    build_dataset_rows,
    export_context_audit,
    langsmith_child_run_id,
    langsmith_enabled_from_env,
    langsmith_run_id,
)
from src.store import StepResult, WorkflowStore
from src.telemetry import TelemetrySink, TelemetryLogger


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeLangSmithClient:
    """The documented minimal client contract (spec §15.2)."""

    def __init__(self) -> None:
        self.created_runs: list[dict[str, Any]] = []
        self.updated_runs: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.sleep_seconds: float = 0.0
        self.fail_with: Exception | None = None

    def create_run(self, *, id, name, run_type, project_name, inputs=None, extra=None, parent_run_id=None):
        if self.fail_with is not None:
            raise self.fail_with
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)
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
        if self.fail_with is not None:
            raise self.fail_with
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
        if self.fail_with is not None:
            raise self.fail_with
        self.events.append({"run_id": run_id, "name": name, "payload": payload})


def _config(**overrides: Any) -> LangSmithConfig:
    base = {"project": "durableflow-test", "redaction": "digest_only", "run_url_base": None}
    base.update(overrides)
    return LangSmithConfig(**base)


def _make_sink(client: FakeLangSmithClient | None = None, **kwargs: Any) -> tuple[LangSmithTelemetrySink, FakeLangSmithClient]:
    client = client or FakeLangSmithClient()
    sink = LangSmithTelemetrySink(client, _config(), **kwargs)
    return sink, client


def _event(event_type: str, workflow_id: str = "wf-a", **fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event_type": event_type,
        "workflow_id": workflow_id,
        "step_name": None,
        "timestamp": "2026-01-01T00:00:00Z",
        "duration_ms": 0.0,
        "cost_usd": 0.0,
        "model_used": None,
        "metadata": {},
    }
    base.update(fields)
    return base


# ---------------------------------------------------------------------------
# C-LSMITH-001: sink fan-out + failure isolation (LSMITH-UNIT-001/002)
# ---------------------------------------------------------------------------

def test_sink_fanout_calls_emit_with_event_dict() -> None:
    received: list[dict[str, Any]] = []

    class CapturingSink:
        def emit(self, event: dict[str, Any]) -> None:
            received.append(event)

    logger = TelemetryLogger(echo=False, sinks=[CapturingSink()])
    logger.log_step_complete("wf", "one", 10.0, 0.25, "mock")
    assert len(received) == 1
    assert received[0]["event_type"] == "step_complete"
    assert received[0]["step_name"] == "one"


def test_telemetry_sink_is_a_protocol() -> None:
    # runtime_checkable protocol: any object with emit() satisfies it.
    class S:
        def emit(self, event: dict[str, Any]) -> None:
            return None

    assert isinstance(S(), TelemetrySink)


def test_failing_sink_does_not_interrupt_logging() -> None:
    class GoodSink:
        def __init__(self) -> None:
            self.count = 0

        def emit(self, event: dict[str, Any]) -> None:
            self.count += 1

    class BadSink:
        def emit(self, event: dict[str, Any]) -> None:
            raise RuntimeError("boom")

    good = GoodSink()
    logger = TelemetryLogger(echo=False, sinks=[BadSink(), good])
    logger.log_step_complete("wf", "one", 1.0)
    logger.log_step_complete("wf", "two", 2.0)
    # The good sink still received both events despite the bad sink raising.
    assert good.count == 2
    # Local event log is intact.
    assert len(logger.events) == 2


# ---------------------------------------------------------------------------
# C-LSMITH-002: non-blocking enqueue (LSMITH-UNIT-003)
# ---------------------------------------------------------------------------

def test_emit_is_non_blocking_against_slow_client() -> None:
    client = FakeLangSmithClient()
    client.sleep_seconds = 0.5  # network simulation on the worker thread
    sink, _ = _make_sink(client)
    start = time.perf_counter()
    sink.emit(_event("step_start", "wf-slow", step_name="s1"))
    elapsed = time.perf_counter() - start
    # emit must return far faster than the simulated network call.
    assert elapsed < 0.1, f"emit blocked for {elapsed:.3f}s"
    sink.flush()
    sink.close()
    assert len(client.created_runs) >= 1


# ---------------------------------------------------------------------------
# C-LSMITH-003: bounded queue overflow (LSMITH-UNIT-004)
# ---------------------------------------------------------------------------

def test_queue_overflow_drops_newest_and_counts() -> None:
    client = FakeLangSmithClient()
    client.sleep_seconds = 0.05  # keep worker busy so the queue fills
    sink, _ = _make_sink(client, max_items=1)
    sink.emit(_event("step_start", "wf-1", step_name="s1"))
    # Second emit while the worker is still on the first item -> overflow.
    sink.emit(_event("step_start", "wf-2", step_name="s1"))
    sink.flush()
    sink.close()
    assert sink.dropped_events >= 1


def test_oversize_event_is_dropped_not_enqueued() -> None:
    client = FakeLangSmithClient()
    sink, _ = _make_sink(client, max_event_bytes=128)
    huge = _event("step_start", "wf-big", metadata={"decision_id": "x" * 10_000})
    sink.emit(huge)
    sink.flush()
    sink.close()
    assert sink.dropped_events == 1
    assert client.created_runs == []


# ---------------------------------------------------------------------------
# C-LSMITH-004: deterministic UUIDv5 mapping (LSMITH-UNIT-006/008/009)
# ---------------------------------------------------------------------------

def test_run_id_is_deterministic_uuidv5() -> None:
    rid = langsmith_run_id("wf-context-demo")
    assert rid.version == 5
    assert rid == langsmith_run_id("wf-context-demo")
    assert langsmith_run_id("wf-a") != langsmith_run_id("wf-b")


def test_child_run_ids_are_distinct_and_deterministic() -> None:
    a1 = langsmith_child_run_id("wf", "triage", 0)
    a2 = langsmith_child_run_id("wf", "triage", 0)
    b = langsmith_child_run_id("wf", "draft", 0)
    c = langsmith_child_run_id("wf", "triage", 1)
    assert a1 == a2
    assert a1 != b != c != a1


def test_namespace_uuid_is_the_spec_constant() -> None:
    assert DURABLEFLOW_LANGSMITH_NAMESPACE == uuid.UUID("f8a30b3f-5c7f-51a8-9d8d-4e3e9f73f5c0")


def test_parallel_workflows_get_distinct_root_and_child_ids() -> None:
    root1, root2 = langsmith_run_id("wf-1"), langsmith_run_id("wf-2")
    child1 = langsmith_child_run_id("wf-1", "step")
    child2 = langsmith_child_run_id("wf-2", "step")
    assert len({root1, root2, child1, child2}) == 4


def test_resumed_workflow_attaches_to_same_root() -> None:
    client = FakeLangSmithClient()
    sink, _ = _make_sink(client)
    root_before = langsmith_run_id("wf-resume")
    # First "process": step start
    sink.emit(_event("step_start", "wf-resume", step_name="s1"))
    sink.flush()
    # Second "process" (resume): resume + step_complete reuse the SAME root id.
    sink.emit(_event("workflow_resumed", "wf-resume", step_name="s1"))
    sink.emit(_event("step_complete", "wf-resume", step_name="s1"))
    sink.flush()
    sink.close()
    root_runs = [r for r in client.created_runs if r["run_type"] == "chain"]
    assert len(root_runs) == 1, "root run created exactly once across resume"
    assert root_runs[0]["id"] == str(root_before)


# ---------------------------------------------------------------------------
# C-LSMITH-005: auth-failure disable (LSMITH-UNIT-010)
# ---------------------------------------------------------------------------

def test_auth_failure_disables_export_for_process() -> None:
    client = FakeLangSmithClient()
    client.fail_with = RuntimeError("401 Unauthorized: invalid api key")
    sink, _ = _make_sink(client)
    sink.emit(_event("step_start", "wf-auth", step_name="s1"))
    sink.flush()
    assert sink.auth_failures == 1
    assert sink._disabled is True  # noqa: SLF001
    # Later emits are no-ops and never raise.
    sink.emit(_event("step_complete", "wf-auth", step_name="s1"))
    sink.close()
    assert client.created_runs == []


def test_non_auth_failure_retries_then_counts_failed_exports() -> None:
    client = FakeLangSmithClient()
    client.fail_with = RuntimeError("connection reset")
    sink, _ = _make_sink(client)
    sink.emit(_event("step_start", "wf-flaky", step_name="s1"))
    sink.flush()
    sink.close()
    # Retried up to RETRY_MAX_ATTEMPTS then dropped, not treated as auth.
    assert sink.auth_failures == 0
    assert sink.failed_exports == 1


# ---------------------------------------------------------------------------
# C-LSMITH-006: metadata sanitization (LSMITH-UNIT-011)
# ---------------------------------------------------------------------------

def test_metadata_unknown_keys_dropped() -> None:
    from integrations.langsmith_adapter import _sanitize_metadata

    out = _sanitize_metadata(
        {"rank_position": 2, "secret_token": "abc", "user_email": "a@b.com"},
        "digest_only",
    )
    assert "rank_position" in out
    assert "secret_token" not in out
    assert "user_email" not in out


def test_metadata_oversize_string_replaced_by_digest_and_truncated() -> None:
    from integrations.langsmith_adapter import _sanitize_metadata

    big = "x" * (1024 * 1024)  # 1 MB
    out = _sanitize_metadata({"rejection_reason": big}, "digest_only")
    val = out["rejection_reason"]
    assert isinstance(val, dict)
    assert val["truncated"] is True
    assert isinstance(val["digest"], str) and val["digest"].startswith("sha256:")


def test_redaction_does_not_export_raw_email_or_token() -> None:
    config = _config()
    event = _event(
        "step_complete",
        metadata={"gate_id": "g1", "user_email": "sarah@acme.com", "api_key": "sk-xxx"},
    )
    from integrations.langsmith_adapter import _redact_event

    redacted = _redact_event(event, config)
    blob = json.dumps(redacted, sort_keys=True)
    assert "sarah@acme.com" not in blob
    assert "sk-xxx" not in blob
    assert redacted["metadata"]["gate_id"] == "g1"


# ---------------------------------------------------------------------------
# C-LSMITH-007: redaction default omits raw content (LSMITH-CTX-001/002)
# C-LSMITH-010: dataset schema + no raw text (LSMITH-DATA-002)
# C-LSMITH-008: model_fallback in-step (LSMITH-UNIT-012)
# ---------------------------------------------------------------------------

def _seed_ledger_with_decision(tmp_path: Path) -> tuple[ContextLedger, str]:
    store = WorkflowStore(tmp_path / "ctx.sqlite")
    state = store.create_workflow("wf-ctx")
    ledger = ContextLedger.from_store(store)
    src = ledger.record_artifact(
        state.workflow_id, "source_artifact", "email-042", "prior_email",
        "top secret body", "mock_emails:email-042", 4,
    )
    ledger.record_event(
        state.workflow_id, "triage", src.artifact_id, "retrieved",
        metadata={"retrieval_method": "tfidf", "retrieval_score": 0.82, "rank_position": 1},
    )
    ledger.record_event(state.workflow_id, "triage", src.artifact_id, "selected")
    ledger.record_event(state.workflow_id, "triage", src.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id, "triage", None,
        "PROMPT WITH RAW CONTENT", "MODEL RESPONSE WITH RAW CONTENT",
        "mock-primary", 10, 3, 0.01,
    )
    ledger.record_lineage(decision.decision_id, src.artifact_id, "explicit_model_attribution", 1.0)
    return ledger, state.workflow_id


def test_context_audit_payload_omits_raw_content(tmp_path: Path) -> None:
    ledger, wid = _seed_ledger_with_decision(tmp_path)
    audit = ledger.audit_workflow(wid)
    payload = build_context_audit_payload(audit)
    blob = json.dumps(payload, sort_keys=True)
    # Raw content, raw prompt, raw response must NOT appear.
    assert "top secret body" not in blob
    assert "PROMPT WITH RAW CONTENT" not in blob
    assert "MODEL RESPONSE WITH RAW CONTENT" not in blob
    # But digests, counts, roles, lineage must.
    assert payload["counts"]["selected"] == 1
    assert payload["counts"]["influential"] == 1
    assert payload["artifacts"][0]["content_digest"].startswith("sha256:")
    assert payload["artifacts"][0]["source_digest"].startswith("sha256:")
    assert payload["decisions"][0]["prompt_digest"].startswith("sha256:")
    assert payload["decisions"][0]["response_digest"].startswith("sha256:")
    assert payload["lineage"][0]["influence_type"] == "explicit_model_attribution"


def test_export_context_audit_tags_backfill_mode(tmp_path: Path) -> None:
    ledger, wid = _seed_ledger_with_decision(tmp_path)
    audit = ledger.audit_workflow(wid)
    payload = export_context_audit(audit)
    assert payload["export_mode"] == "backfill"
    assert payload["run_id"] == str(langsmith_run_id(wid))


def test_model_fallback_maps_inside_step_span_not_top_level() -> None:
    client = FakeLangSmithClient()
    sink, _ = _make_sink(client)
    sink.emit(_event("step_start", "wf-fb", step_name="triage"))
    sink.emit(
        _event(
            "model_fallback",
            "wf-fb",
            step_name="triage",
            metadata={"from_model": "primary", "to_model": "secondary", "error": "rate limit exceeded"},
        )
    )
    sink.flush()
    sink.close()
    fallback_events = [e for e in client.events if e["name"] == "model_fallback"]
    assert len(fallback_events) == 1
    # The fallback event is logged on the STEP child run id, not the root.
    expected_child = str(langsmith_child_run_id("wf-fb", "triage"))
    assert fallback_events[0]["run_id"] == expected_child
    payload = fallback_events[0]["payload"]
    assert payload["from_model"] == "primary"
    assert payload["to_model"] == "secondary"
    assert payload["error_category"] == "rate_limit"
    assert payload["error_digest"].startswith("sha256:")


# ---------------------------------------------------------------------------
# C-LSMITH-009: core import-cleanliness (LSMITH-CTX-003)
# ---------------------------------------------------------------------------

def test_core_modules_do_not_import_integrations() -> None:
    import ast

    repo = Path(__file__).resolve().parent.parent
    core_files = [
        repo / "src" / "telemetry.py",
        repo / "src" / "engine.py",
        repo / "context" / "ledger.py",
    ]
    forbidden = {"integrations", "langsmith"}
    for path in core_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.add(node.module.split(".")[0])
        leaks = imported & forbidden
        assert not leaks, f"{path.name} imports forbidden module(s): {leaks}"


# ---------------------------------------------------------------------------
# C-LSMITH-010: dataset schema (LSMITH-DATA-001/002)
# ---------------------------------------------------------------------------

def test_dataset_rows_match_documented_schema(tmp_path: Path) -> None:
    ledger, wid = _seed_ledger_with_decision(tmp_path)
    audit = ledger.audit_workflow(wid)
    rows = build_dataset_rows(audit, seed=1337)
    assert len(rows) == 1
    row = rows[0]
    # inputs
    assert row["inputs"]["workflow_id"] == wid
    assert row["inputs"]["step_name"] == "triage"
    assert isinstance(row["inputs"]["fixture_ref"], str)
    assert isinstance(row["inputs"]["context_digest_set"], list)
    assert all(d.startswith("sha256:") for d in row["inputs"]["context_digest_set"])
    summary = row["inputs"]["context_summary"]
    assert summary["selected_count"] == 1
    assert summary["artifacts"][0]["artifact_role"] == "source_artifact"
    assert summary["artifacts"][0]["content_digest"].startswith("sha256:")
    # outputs
    assert "expected_status" in row["outputs"]
    # metadata
    assert row["metadata"]["model_used"] == "mock-primary"
    assert row["metadata"]["token_counts"] == {"input": 10, "output": 3}
    assert set(row["metadata"]["lineage_counts"]) == {"observed", "selected", "rejected", "consumed", "influential"}
    assert row["metadata"]["seed"] == 1337


def test_dataset_rows_contain_no_raw_text(tmp_path: Path) -> None:
    ledger, wid = _seed_ledger_with_decision(tmp_path)
    audit = ledger.audit_workflow(wid)
    rows = build_dataset_rows(audit)
    blob = json.dumps(rows, sort_keys=True)
    assert "top secret body" not in blob
    assert "PROMPT WITH RAW CONTENT" not in blob


# ---------------------------------------------------------------------------
# C-LSMITH-011: disabled config is inert (LSMITH-SEM-001)
# ---------------------------------------------------------------------------

def test_disabled_config_returns_no_sink() -> None:
    assert langsmith_enabled_from_env({}) is False
    assert LangSmithTelemetrySink.from_env({}) is None


def test_enabled_without_key_returns_no_sink() -> None:
    env = {"DURABLEFLOW_LANGSMITH_ENABLED": "1"}  # no API key
    assert langsmith_enabled_from_env(env) is False
    assert LangSmithTelemetrySink.from_env(env) is None


def test_enabled_with_key_returns_sink_when_client_provided() -> None:
    env = {"DURABLEFLOW_LANGSMITH_ENABLED": "true", "LANGSMITH_API_KEY": "sk-test"}
    fake = FakeLangSmithClient()
    sink = LangSmithTelemetrySink.from_env(env, client=fake)
    assert sink is not None
    sink.close()


# ---------------------------------------------------------------------------
# C-LSMITH-012: import-safe without SDK (LSMITH-UNIT-005)
# ---------------------------------------------------------------------------

def test_adapter_module_imports_without_sdk() -> None:
    # Importing the module must not require the langsmith SDK.
    import importlib

    module = importlib.import_module("integrations.langsmith_adapter")
    assert hasattr(module, "LangSmithTelemetrySink")


def test_real_client_construction_without_sdk_raises_importerror() -> None:
    # The wrapper raises ImportError only at construction, not at module import.
    from integrations.langsmith_adapter import _RealLangSmithClient

    try:
        import langsmith  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            _RealLangSmithClient(api_key="x", project="p")
    else:  # pragma: no cover - SDK present in some envs
        pytest.skip("langsmith SDK installed; import-error path not exercisable")


# ---------------------------------------------------------------------------
# C-LSMITH-DEFER-001: live SDK round-trip (LSMITH-INT-001)
#
# Gated: skipped unless DURABLEFLOW_LANGSMITH_INTEGRATION=1 AND a real
# LANGSMITH_API_KEY is set. Passing this test unblocks the DEFERRED-VERIFICATION
# claim (see verification/deferred-items.md). It exercises the real SDK against
# a live project: create root + child run, update the child, log an event, then
# read it back. Failure modes here are real-API conformance failures, not unit
# failures — they should be diagnosed against the pinned SDK version range.
# ---------------------------------------------------------------------------

_LIVE_GATED = {"1", "true", "yes"}


def _live_enabled() -> bool:
    import os

    return (
        os.environ.get("DURABLEFLOW_LANGSMITH_INTEGRATION", "").strip().lower() in _LIVE_GATED
        and bool(os.environ.get("LANGSMITH_API_KEY", "").strip())
    )


@pytest.mark.skipif(not _live_enabled(), reason="set DURABLEFLOW_LANGSMITH_INTEGRATION=1 and LANGSMITH_API_KEY")
def test_live_sdk_roundtrip() -> None:
    import os

    from integrations.langsmith_adapter import LangSmithConfig, _RealLangSmithClient

    config = LangSmithConfig.from_env()
    client = _RealLangSmithClient(
        api_key=os.environ["LANGSMITH_API_KEY"],
        project=config.project,
    )
    workflow_id = f"wf-live-smoke-{uuid.uuid4().hex[:8]}"
    root_id = langsmith_run_id(workflow_id)
    child_id = langsmith_child_run_id(workflow_id, "triage")

    # Create a deterministic root run, then a child, then update + log_event.
    client.create_run(
        id=str(root_id),
        name=workflow_id,
        run_type="chain",
        project_name=config.project,
        inputs={"workflow_id": workflow_id},
    )
    client.create_run(
        id=str(child_id),
        name="triage",
        run_type="llm",
        project_name=config.project,
        inputs={"workflow_id": workflow_id, "step_name": "triage"},
        parent_run_id=str(root_id),
    )
    client.update_run(
        str(child_id),
        outputs={"model_used": "live-smoke", "cost_usd": 0.0},
    )
    client.log_event(str(child_id), name="model_fallback", payload={"error_category": "other"})
    client.update_run(
        str(root_id),
        outputs={"completed": True},
    )
    # If none of the above raised, the SDK accepted the deterministic run shape.
    # A full read-back (fetching the run by id) depends on SDK read APIs outside
    # the documented contract; the create/update/log round-trip itself is the
    # conformance signal for C-LSMITH-DEFER-001.


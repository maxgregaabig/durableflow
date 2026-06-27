"""Eval case creation and redaction (spec §9, Phase 1).

Covers T-EVAL-001 (completed workflow -> EvalCase with required fields + digest
redaction), T-EVAL-002 (incomplete workflow rejected), T-EVAL-013 (redaction
allowlist + oversized-string digesting).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from context.ledger import ContextLedger
from src.store import StepResult, WorkflowStatus, WorkflowStore

from evals.cases import build_eval_case_from_workflow
from evals.io import payload_digest, verify_digest, write_artifact, write_json_with_digest
from evals.redaction import digest_payloads, digest_value, redact_value
from tests.eval_conftest import make_completed_workflow, make_incomplete_workflow


# ---------------------------------------------------------------------------
# T-EVAL-001: completed workflow -> deterministic EvalCase JSON
# ---------------------------------------------------------------------------


def test_completed_workflow_produces_eval_case_with_required_fields(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "ok.sqlite")
    ledger = ContextLedger.from_store(store)
    result = build_eval_case_from_workflow(store, wid, context_ledger=ledger)

    assert result.accepted, result.reason
    assert result.case is not None
    case = result.case

    # All required fields present (spec §4.1 Gherkin).
    for field in (
        "case_id", "workflow_id", "workflow_name", "created_at",
        "input_summary", "expected", "trace_summary", "context_summary",
        "approval_summary", "cost_summary", "metadata",
    ):
        assert hasattr(case, field), f"missing field: {field}"

    assert case.workflow_id == wid
    assert case.trace_summary["step_count"] == 3
    assert case.cost_summary["total_cost_usd"] > 0
    assert case.cost_summary["models_used"] == ["mock-primary"]
    assert case.context_summary["available"] is True
    # Lineage counts surface from the audit object generically.
    assert case.context_summary["lineage_counts"]["consumed"] == 1


def test_eval_case_artifact_is_deterministic_and_digest_anchored(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "det.sqlite", workflow_id="wf-det")
    case = build_eval_case_from_workflow(store, wid, context_ledger=ContextLedger.from_store(store)).case
    assert case is not None

    out = tmp_path / "case.json"
    path = write_json_with_digest(case, out)
    assert Path(path).exists()
    # Same inputs -> same case_id and same digest across writes.
    again = write_json_with_digest(case, tmp_path / "case2.json")
    assert json.loads(Path(path).read_text())["digest"] == json.loads(Path(again).read_text())["digest"]
    assert verify_digest(path) is True


def test_default_artifact_uses_digests_not_raw_prompts_or_responses(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "digest.sqlite", workflow_id="wf-dig")
    ledger = ContextLedger.from_store(store)
    case = build_eval_case_from_workflow(store, wid, context_ledger=ledger).case
    out = write_json_with_digest(case, tmp_path / "case.json")

    blob = Path(out).read_text(encoding="utf-8")
    # Raw prompt/response literals never leak by default (spec §4.1 Gherkin).
    assert "prompt-text" not in blob
    assert "response-text" not in blob
    # The case_id is deterministic for a given workflow_id.
    assert case.case_id.startswith("case-")


# ---------------------------------------------------------------------------
# T-EVAL-002: incomplete workflow rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [WorkflowStatus.PENDING, WorkflowStatus.RUNNING, WorkflowStatus.FAILED])
def test_incomplete_workflow_is_rejected_with_reason(tmp_path: Path, status) -> None:
    store = make_incomplete_workflow(tmp_path / "inc.sqlite", workflow_id="wf-inc")
    # Force a non-completed status explicitly.
    store.update_status("wf-inc", status)
    out_path = tmp_path / "should_not_exist.json"

    result = build_eval_case_from_workflow(store, "wf-inc")

    assert result.accepted is False
    assert result.case is None
    assert "incomplete" in result.reason.lower() or "must be 'completed'" in result.reason
    assert out_path.exists() is False


def test_missing_workflow_is_rejected_with_reason(tmp_path: Path) -> None:
    store = WorkflowStore(tmp_path / "missing.sqlite")
    result = build_eval_case_from_workflow(store, "wf-nonexistent")
    assert result.accepted is False
    assert "not found" in result.reason.lower()


# ---------------------------------------------------------------------------
# T-EVAL-013: redaction allowlist + oversized-string digesting
# ---------------------------------------------------------------------------


def test_redaction_drops_unknown_metadata_keys() -> None:
    from evals.redaction import filter_allowlist

    allow = frozenset({"safe_key", "count"})
    out = filter_allowlist({"safe_key": "ok", "count": 3, "secret": "leak"}, allow)
    assert set(out) == {"safe_key", "count"}
    assert "secret" not in out


def test_redaction_replaces_oversized_strings_with_digest() -> None:
    big = "x" * 2048
    out = redact_value(big, max_bytes=512)
    assert isinstance(out, dict)
    assert out["truncated"] is True
    assert out["digest"].startswith("sha256:")
    assert out["original_bytes"] == 2048


def test_redaction_keeps_small_strings_unchanged() -> None:
    assert redact_value("small") == "small"
    assert redact_value(42) == 42
    assert redact_value(True) is True
    assert redact_value(None) is None


def test_digest_payloads_converts_raw_prompt_and_response() -> None:
    out = digest_payloads({"raw_prompt": "hello", "raw_response": "world", "other": "keep"})
    assert out["raw_prompt"] == {"digest": digest_value("hello"), "bytes": 5}
    assert out["raw_response"] == {"digest": digest_value("world"), "bytes": 5}
    assert out["other"] == "keep"


def test_digest_value_is_stable_sha256() -> None:
    assert digest_value("abc") == "sha256:" + "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

"""Eval gate CLI behavior (spec §9, Phase 4).

Covers T-EVAL-008: CI exit codes passed=0, failed=1, incomplete=2. Exercises the
CLI end to end with real manifests/cases on disk and no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from context.ledger import ContextLedger
from evals.cli import main as cli_main
from evals.io import write_artifact
from evals.manifest import new_manifest, save_eval_manifest
from tests.eval_conftest import make_completed_workflow, make_incomplete_workflow


def _write_case(store_db: Path, workflow_id: str, *, out_dir: Path) -> Path:
    """Promote a workflow (already created at store_db) into a case on disk.

    The workflow MUST already exist in ``store_db``; this helper only builds and
    writes the EvalCase artifact so tests don't double-create workflows.
    """
    from evals.cases import build_eval_case_from_workflow
    from src.store import WorkflowStore

    store = WorkflowStore(store_db)
    ledger = ContextLedger.from_store(store)
    result = build_eval_case_from_workflow(store, workflow_id, context_ledger=ledger)
    assert result.accepted and result.case is not None
    path, _ = write_artifact(result.case, out_dir / f"{result.case.case_id}.json")
    return Path(path)


def _write_manifest(tmp_path: Path, case_paths: list[str], *, required: list[str], thresholds: dict | None = None) -> Path:
    manifest = new_manifest(required_scorers=required, thresholds=thresholds or {})
    # Inject the case paths directly.
    from evals.manifest import EvalManifest

    manifest = EvalManifest(
        manifest_id=manifest.manifest_id, version=1,
        cases=list(case_paths), required_scorers=required, thresholds=thresholds or {},
    )
    path = tmp_path / "manifest.json"
    save_eval_manifest(manifest, path)
    return path


def test_make_case_writes_eval_case_artifact(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "mk.sqlite", workflow_id="wf-mk")
    out = tmp_path / "case.json"
    rc = cli_main([
        "make-case", "--db", str(tmp_path / "mk.sqlite"),
        "--workflow-id", wid, "--out", str(out),
        "--context-db", str(tmp_path / "mk.sqlite"),
    ])
    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["workflow_id"] == wid
    assert data["case_id"].startswith("case-")


def test_make_case_rejects_incomplete_workflow_with_exit_2(tmp_path: Path) -> None:
    make_incomplete_workflow(tmp_path / "inc.sqlite", workflow_id="wf-inc")
    out = tmp_path / "nope.json"
    rc = cli_main([
        "make-case", "--db", str(tmp_path / "inc.sqlite"),
        "--workflow-id", "wf-inc", "--out", str(out),
    ])
    assert rc == 2
    assert not out.exists()


def test_gate_ci_passed_exits_zero(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "pass.sqlite", workflow_id="wf-pass")
    case_path = _write_case(tmp_path / "pass.sqlite", wid, out_dir=tmp_path)
    manifest = _write_manifest(
        tmp_path, [str(case_path)],
        required=["trace_completeness", "context_lineage_completeness", "approval_boundary"],
        thresholds={
            "trace_completeness": 1.0,
            "context_lineage_completeness": 1.0,
            "approval_boundary": 1.0,
        },
    )
    report_out = tmp_path / "report.json"
    rc = cli_main([
        "gate", "--manifest", str(manifest), "--out", str(report_out), "--ci",
    ])
    assert rc == 0
    assert report_out.exists()
    assert json.loads(report_out.read_text())["status"] == "passed"


def test_gate_ci_failed_exits_one(tmp_path: Path) -> None:
    from tests.eval_conftest import make_fail_case
    case = make_fail_case(tmp_path / "fail.sqlite", workflow_id="wf-fail")
    case_path = _write_case_from_obj(case, tmp_path)
    manifest = _write_manifest(
        tmp_path, [str(case_path)],
        required=["trace_completeness", "context_lineage_completeness"],
        thresholds={"trace_completeness": 1.0, "context_lineage_completeness": 1.0},
    )
    report_out = tmp_path / "report.json"
    rc = cli_main(["gate", "--manifest", str(manifest), "--out", str(report_out), "--ci"])
    assert rc == 1
    assert json.loads(report_out.read_text())["status"] == "failed"


def test_gate_ci_incomplete_exits_two_for_missing_scorer(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "inc.sqlite", workflow_id="wf-inc-gate")
    case_path = _write_case(tmp_path / "inc.sqlite", wid, out_dir=tmp_path)
    manifest = _write_manifest(
        tmp_path, [str(case_path)],
        required=["trace_completeness", "task_success"],  # task_success never registered
        thresholds={"trace_completeness": 1.0},
    )
    report_out = tmp_path / "report.json"
    rc = cli_main(["gate", "--manifest", str(manifest), "--out", str(report_out), "--ci"])
    assert rc == 2
    assert json.loads(report_out.read_text())["status"] == "incomplete"


def test_render_report_reads_existing_report_json(tmp_path: Path) -> None:
    store, wid = make_completed_workflow(tmp_path / "rr.sqlite", workflow_id="wf-rr")
    case_path = _write_case(tmp_path / "rr.sqlite", wid, out_dir=tmp_path)
    manifest = _write_manifest(
        tmp_path, [str(case_path)],
        required=["trace_completeness", "context_lineage_completeness", "approval_boundary"],
        thresholds={
            "trace_completeness": 1.0,
            "context_lineage_completeness": 1.0,
            "approval_boundary": 1.0,
        },
    )
    report_out = tmp_path / "report.json"
    cli_main(["gate", "--manifest", str(manifest), "--out", str(report_out)])
    md = tmp_path / "report.md"
    rc = cli_main(["render-report", "--report", str(report_out), "--out", str(md)])
    assert rc == 0
    text = md.read_text()
    assert "Gate verdict" in text
    assert "Next action" in text


def _write_case_from_obj(case, tmp_path: Path) -> Path:
    path, _ = write_artifact(case, tmp_path / f"{case.case_id}.json")
    return Path(path)

"""Optional LangSmith export behavior (spec §9, Phase 5).

Covers T-EVAL-011: a failing optional LangSmith export is recorded as
``export_status="failed"`` and MUST NOT change the local gate verdict or raise
into local scoring. Also covers the architectural invariant that no core
``evals.*`` module imports LangSmith.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from evals.gate import EvalExportHook, GateRunConfig, run_eval_gate
from tests.eval_conftest import build_report, make_pass_case, pass_scorers


# ---------------------------------------------------------------------------
# A raising export hook is swallowed and recorded as export_status="failed"
# ---------------------------------------------------------------------------


class _RaisingExportHook:
    """Simulates a LangSmith upload that fails (network/SDK error)."""

    name = "raising"

    def export(self, cases, report) -> None:  # EvalExportHook shape
        raise RuntimeError("simulated LangSmith network failure")


def test_failing_export_does_not_change_local_verdict(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "exp.sqlite")
    report = run_eval_gate(
        [case], pass_scorers(),
        GateRunConfig(
            required_scorers=["trace_completeness", "context_lineage_completeness", "approval_boundary"],
            missing_scorers=[],
        ),
        export_hook=_RaisingExportHook(),
    )
    # Local verdict is unchanged...
    assert report.status == "passed"
    # ...and the export failure is recorded, not raised.
    assert report.export_status == "failed"


def test_successful_export_marks_succeeded(tmp_path: Path) -> None:
    class _OkHook:
        def export(self, cases, report) -> None:
            self.seen = (list(cases), report)

    case = make_pass_case(tmp_path / "exp_ok.sqlite")
    hook = _OkHook()
    report = run_eval_gate(
        [case], pass_scorers(),
        GateRunConfig(
            required_scorers=["trace_completeness", "context_lineage_completeness", "approval_boundary"],
            missing_scorers=[],
        ),
        export_hook=hook,
    )
    assert report.export_status == "succeeded"
    assert report.status == "passed"
    assert hook.seen[0]  # hook received cases


def test_no_export_hook_leaves_not_configured(tmp_path: Path) -> None:
    case = make_pass_case(tmp_path / "exp_none.sqlite")
    report = build_report([case], pass_scorers(),
                          required=["trace_completeness", "context_lineage_completeness", "approval_boundary"])
    assert report.export_status == "not_configured"


def test_export_hook_protocol_is_runtime_checkable() -> None:
    assert isinstance(_RaisingExportHook(), EvalExportHook)


# ---------------------------------------------------------------------------
# Architectural invariant: core evals.* never imports LangSmith
# ---------------------------------------------------------------------------


def _core_evals_modules() -> list[str]:
    return [
        "evals.cases", "evals.gate", "evals.manifest", "evals.io",
        "evals.redaction", "evals.scorers", "evals.registry",
        "evals.view", "evals.render",
    ]


@pytest.mark.parametrize("modname", _core_evals_modules())
def test_core_evals_modules_do_not_import_langsmith(modname: str) -> None:
    import importlib

    mod = importlib.import_module(modname)
    source = Path(mod.__file__).read_text(encoding="utf-8")  # type: ignore[arg-type]
    forbidden = [
        "from langsmith",
        "import langsmith",
        "from integrations.langsmith",
        "from integrations import langsmith",
        "LangSmithTelemetrySink",
        "langsmith_eval_export",
    ]
    for token in forbidden:
        assert token not in source, f"{modname} references LangSmith: {token!r}"


def test_langsmith_export_hook_is_optional_in_cli(tmp_path: Path) -> None:
    """Without --langsmith-export the gate runs with no export hook wired."""
    from evals.cli import _maybe_export_hook

    class _Args:
        langsmith_export = False
    hook = _maybe_export_hook(_Args())
    assert hook is None


def test_from_env_returns_none_without_sdk_or_key(monkeypatch) -> None:
    """from_env degrades to None when the SDK / key is absent (C-EVAL-009)."""
    from integrations.langsmith_eval_export import LangSmithEvalExportHook

    # Disabled env -> None.
    monkeypatch.delenv("DURABLEFLOW_LANGSMITH_ENABLED", raising=False)
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    assert LangSmithEvalExportHook.from_env() is None

    # Enabled but no SDK importable -> None (no raise).
    monkeypatch.setenv("DURABLEFLOW_LANGSMITH_ENABLED", "1")
    monkeypatch.setenv("LANGSMITH_API_KEY", "fake-key")
    # Ensure langsmith is not importable for this test.
    monkeypatch.setitem(sys.modules, "langsmith", None)
    assert LangSmithEvalExportHook.from_env() is None

"""Optional LangSmith export hook for the eval gate (spec Phase 5, C-EVAL-009).

This hook implements ``EvalExportHook`` (from ``evals.gate``). It is best-effort:
network/SDK failures are caught by the gate runner and recorded as
``export_status="failed"``; the local verdict is never changed and the process
never raises (spec §4.1 Gherkin, T-EVAL-011).

It MUST NOT be imported by any ``evals.*`` core module. Only CLI / user entry
points lazy-import it after the operator opts in (``--langsmith-export``). This
keeps the LangSmith SDK an optional extra and the core gate network-free.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from evals.cases import EvalCase
from evals.gate import EvalGateReport
from evals.redaction import digest_value
from integrations.langsmith_adapter import LangSmithConfig, langsmith_enabled_from_env


class LangSmithEvalExportHook:
    """Best-effort export of eval cases + gate summary to LangSmith.

    ``from_env`` returns ``None`` (a clean no-op) when export is disabled or the
    SDK is absent, so the gate treats the missing hook as "not configured" and
    proceeds with the local verdict.
    """

    def __init__(self, *, config: LangSmithConfig, client: Any | None = None):
        self._config = config
        self._client = client
        # Counters for observability; never propagated as exceptions.
        self.exported_rows = 0
        self.failed_exports = 0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "LangSmithEvalExportHook | None":
        if not langsmith_enabled_from_env(env):
            return None
        config = LangSmithConfig.from_env(env)
        environ = env if env is not None else os.environ
        api_key = environ.get("LANGSMITH_API_KEY", "").strip()
        try:
            from langsmith import Client  # type: ignore[import-not-found]

            client = Client(api_key=api_key)
        except ImportError:
            # SDK not installed: return None so the gate sees "not configured".
            print(
                "[eval-gate] LangSmith export enabled but SDK not installed; skipping",
                file=sys.stderr,
            )
            return None
        return cls(config=config, client=client)

    def export(self, cases: list[EvalCase], report: EvalGateReport) -> None:
        """Export redacted eval case rows + the gate summary to LangSmith.

        Failures are allowed to propagate to the gate runner, which catches them
        and records ``export_status="failed"`` without changing the verdict.
        """
        if self._client is None:
            return
        dataset_name = self._config.project + "-eval"
        for case in cases:
            row = _redacted_dataset_row(case)
            self._client.create_example(
                inputs=row["inputs"],
                outputs=row["outputs"],
                metadata=row["metadata"],
                dataset_name=dataset_name,
            )
            self.exported_rows += 1
        # Gate summary as a metadata-only example so the verdict is inspectable
        # remotely without rerunning scorers.
        self._client.create_example(
            inputs={"report_id": report.report_id},
            outputs={
                "status": report.status,
                "release_blockers": list(report.release_blockers),
            },
            metadata={
                "manifest_id": report.manifest_id,
                "gate_name": report.gate_name,
                "export_mode": "eval_gate_summary",
            },
            dataset_name=dataset_name,
        )
        self.exported_rows += 1


def _redacted_dataset_row(case: EvalCase) -> dict[str, Any]:
    """Build a digest-only dataset row from an ``EvalCase`` (spec §6.4)."""
    inputs = {
        "case_id": case.case_id,
        "workflow_id": case.workflow_id,
        "workflow_name": case.workflow_name,
        "input_summary": case.input_summary,
    }
    outputs = {
        "expected_workflow_status": (case.expected or {}).get("workflow_status"),
        "final_step": (case.expected or {}).get("final_step"),
        "final_output_digest": (case.expected or {}).get("final_output_digest"),
    }
    metadata = {
        "trace_summary": case.trace_summary,
        "context_summary": case.context_summary,
        "approval_summary": case.approval_summary,
        "cost_summary": case.cost_summary,
        "case_digest": digest_value(case.case_id + case.workflow_id + case.created_at),
    }
    return {"inputs": inputs, "outputs": outputs, "metadata": metadata}


__all__ = ["LangSmithEvalExportHook"]

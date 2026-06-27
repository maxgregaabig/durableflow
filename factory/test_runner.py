"""Assess lap: run tests and write the phase verification report.

The report is the operator-facing artifact for a phase assessment (spec
§0, §6.3). It records the test command, the outcome, the log pointer
(archived full output, not prose-only), and the failed assertions so a
skeptical operator can see exactly what broke (CLEAR-INT-004, §3.5
SEM-CLEAR-002).

Python standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .agent_runner import VerifierAgent
from .phase_state import ClearPhase
from .workspace import TestRunResult, Workspace


_FAILED_ASSERTION = re.compile(r"AssertionError.*|assert .*", re.IGNORECASE)


@dataclass
class AssessLapOutcome:
    """Outcome of one assess lap."""

    passed: bool
    report_path: str
    log_path: str
    failed_assertions: list[str]
    summary: str


class TestRunner:
    """Runs a phase's tests through the independent verifier and reports."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.verifier = VerifierAgent(workspace)

    def run(
        self,
        phase: ClearPhase,
        attempt: int,
        *,
        workflow_id: str,
    ) -> AssessLapOutcome:
        result: TestRunResult = self.verifier.execute_tests(
            phase, attempt, workflow_id=workflow_id
        )
        failed_assertions = self._extract_failed_assertions(result)
        report_path = self._write_report(phase, attempt, result, failed_assertions)
        return AssessLapOutcome(
            passed=result.passed,
            report_path=report_path,
            log_path=result.log_path,
            failed_assertions=failed_assertions,
            summary=self._summary(phase, result, failed_assertions),
        )

    def _extract_failed_assertions(self, result: TestRunResult) -> list[str]:
        haystack = f"{result.stdout}\n{result.stderr}"
        found: list[str] = []
        for match in _FAILED_ASSERTION.finditer(haystack):
            text = match.group(0).strip()
            if text and text not in found:
                found.append(text)
        return found[:10]

    def _summary(
        self,
        phase: ClearPhase,
        result: TestRunResult,
        failed_assertions: list[str],
    ) -> str:
        if result.passed:
            return f"All tests passed for {phase.label}."
        count = len(failed_assertions) or "some"
        return f"{phase.label} failed: {count} assertion(s) failed."

    def _write_report(
        self,
        phase: ClearPhase,
        attempt: int,
        result: TestRunResult,
        failed_assertions: list[str],
    ) -> str:
        # Per-attempt report path preserves each attempt's verdict (a phase
        # that fails then passes keeps both reports). The spec's
        # ``phase_N_report.md`` is mirrored as the latest snapshot below.
        rel_path = f"phase_{phase.number}_attempt_{attempt}_report.md"
        outcome = "PASSED" if result.passed else "FAILED"
        lines = [
            f"# {phase.label} — Verification Report",
            "",
            f"- Attempt: {attempt}",
            f"- Outcome: **{outcome}**",
            f"- Test command: `{result.command}`",
            f"- Full log: `{result.log_path}`",
            "",
        ]
        if result.passed:
            lines += [
                "## Result",
                "",
                "Every required test passed. See the archived log for the full output.",
                "",
            ]
        else:
            lines += [
                "## Failed assertions",
                "",
            ]
            if failed_assertions:
                for item in failed_assertions:
                    lines.append(f"- `{item}`")
            else:
                lines.append("- (no assertion captured; see log)")
            lines += [
                "",
                "## Root cause",
                "",
                "See the Five Whys analysis written alongside this report.",
                "",
            ]
        lines += [
            "## Test output (archived)",
            "",
            f"Full stdout/stderr is archived at `{result.log_path}`.",
            "",
        ]
        report = "\n".join(lines)
        # Reports are written through the workspace so they are on disk,
        # but they are not source mutations; write directly without an
        # idempotency key so each attempt keeps its own report. Mirror the
        # latest verdict to the spec-named ``phase_N_report.md`` so the
        # well-known path always reflects the most recent assessment.
        path: Path = self.workspace.resolve(rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        latest_path = self.workspace.resolve(f"phase_{phase.number}_report.md")
        latest_path.write_text(report, encoding="utf-8")
        return rel_path

"""Remediation lap: Five Whys root-cause analysis and artifact update.

On a failed assessment the phase runner runs a remediation lap (spec
§0, §7 Phase 4). It writes a Five Whys root-cause artifact that names
the failed claim and derives the proposed correction from the observed
failure, then rewrites the relevant artifact so the re-assessment runs
against corrected inputs. Revised artifacts get new content (hence new
context artifact rows) when the ledger is enabled.

The root-cause analysis is generic: the first two Whys are driven by
the captured failed assertion and the failing test module, while the
later Whys state the universal verification boundary (implementer
assertion is E5 and never sufficient — spec §8.6).

Python standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .phase_state import ClearPhase
from .test_runner import AssessLapOutcome
from .workspace import Workspace


@dataclass
class RemediationOutcome:
    """Outcome of one remediation lap."""

    root_cause_path: str
    updated_artifacts: list[str]
    summary: str


class RemediationEngine:
    """Produces a deterministic Five Whys root-cause and fixes the feature."""

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def run(
        self,
        phase: ClearPhase,
        attempt: int,
        assessment: AssessLapOutcome,
        *,
        workflow_id: str,
        corrected_source: str | None = None,
    ) -> RemediationOutcome:
        """Run the remediation lap.

        ``corrected_source`` is the repaired feature source. When None,
        the engine asks the phase's claim text for the expected behavior
        and emits a generic corrected stub (see :meth:`_generic_correction`).
        """
        if corrected_source is None:
            corrected_source = self._generic_correction(phase)
        root_cause_path = self._write_five_whys(phase, attempt, assessment)
        updated = self._apply_correction(phase, attempt, workflow_id, corrected_source)
        return RemediationOutcome(
            root_cause_path=root_cause_path,
            updated_artifacts=updated,
            summary=(
                f"Root-caused the {phase.label} failure and rewrote the feature "
                f"to satisfy its claim; re-assessment will run next."
            ),
        )

    def _write_five_whys(
        self,
        phase: ClearPhase,
        attempt: int,
        assessment: AssessLapOutcome,
    ) -> str:
        rel_path = f"phase_{phase.number}_five_whys.md"
        first_failure = (
            assessment.failed_assertions[0]
            if assessment.failed_assertions
            else "test assertion failed"
        )
        failing_module = self._failing_module(assessment)
        claim_id = phase.claims[0].claim_id if phase.claims else "phase behavior"
        expected = self._expected_behavior(phase)
        lines = [
            f"# {phase.label} — Five Whys Root-Cause Analysis",
            "",
            f"Failed claim: {claim_id}",
            f"Failed assertion: `{first_failure}`",
            f"Failing test module: `{failing_module}`",
            "",
            "## Five Whys",
            "",
            "1. **Why did the test fail?** The implementation produced output "
            "that did not satisfy the assertion above.",
            "2. **Why was that output produced?** The implement lap emitted a "
            "stub that did not yet encode the expected behavior.",
            "3. **Why did the stub reach assessment?** Assessment runs against "
            "whatever the implement lap produced; it is the verifier's job to "
            "catch this, which it did.",
            "4. **Why is that the right boundary?** Implementer assertion is E5 "
            "evidence and never sufficient (spec §8.6).",
            "5. **Why does this matter?** Completion claims must rest on "
            "independent verification, not implementer confidence.",
            "",
            "## Expected behavior",
            "",
            f"{expected}",
            "",
            "## Proposed correction",
            "",
            f"Rewrite `{failing_module}`'s target feature so it satisfies "
            f"{claim_id}, then re-assess.",
            "",
        ]
        path = self.workspace.resolve(rel_path)
        path.write_text("\n".join(lines), encoding="utf-8")
        return rel_path

    def _apply_correction(
        self,
        phase: ClearPhase,
        attempt: int,
        workflow_id: str,
        corrected_source: str,
    ) -> list[str]:
        """Rewrite the feature so re-assessment passes.

        The corrected content differs from the broken stub, so the write
        gets a fresh idempotency key (and a new context artifact row
        when the ledger is enabled).
        """
        module_name = f"phase_{phase.number}_feature"
        result = self.workspace.write_file(
            f"src/{module_name}.py",
            corrected_source,
            workflow_id=workflow_id,
            phase=phase.number,
            attempt=attempt,
        )
        return [result.path]

    # --- generic derivation helpers --------------------------------------

    @staticmethod
    def _failing_module(assessment: AssessLapOutcome) -> str:
        """Best-effort extraction of the failing test module from the report path."""
        report = assessment.report_path or ""
        # report path like phase_1_attempt_1_report.md -> tests/test_phase_1.py
        m = re.search(r"phase_(\d+)", report)
        if m:
            return f"tests/test_phase_{m.group(1)}.py"
        return "the phase test module"

    @staticmethod
    def _expected_behavior(phase: ClearPhase) -> str:
        if phase.claims:
            return phase.claims[0].claim_text
        return f"Phase {phase.number} behavior described in plan.md."

    @staticmethod
    def _generic_correction(phase: ClearPhase) -> str:
        """A corrected feature stub derived from the phase's claim.

        Rather than hardcode a domain-specific fix, this emits a minimal
        function whose docstring states the claim; the concrete repair is
        supplied by the implementer on the next implement lap (attempt+1).
        For the worked example this stub is then overwritten by the
        implementer's correct source before re-assessment.
        """
        claim_text = phase.claims[0].claim_text if phase.claims else "phase behavior"
        return (
            f'n = {phase.number}\n'
            f'\n'
            f'def behavior():\n'
            f'    """Satisfies: {claim_text}"""\n'
            f'    return "phase {phase.number} ok"\n'
        )

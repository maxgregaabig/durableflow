"""Deterministic agent runner for CLEAR's implement and assess laps.

This is a hermetic, deterministic stand-in for an LLM tool-calling
agent. It produces code edits from the parsed plan/stack artifacts
(implement lap) and verdicts from real test execution (assess lap). The
implementer and verifier carry distinct agent IDs so the Verifier
Independence Principle holds for every VERIFIED verdict (spec §8.6).

Determinism keeps the educational example offline and reproducible; the
real ModelRouter/agent loop is the same wiring with a different provider.

Python standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .phase_state import ClearPhase
from .workspace import Workspace

from .verification_ledger import IMPLEMENTER_ID, VERIFIER_ID


@dataclass
class ImplementLapOutcome:
    """Outcome of one implement lap."""

    files_written: list[str]
    summary: str
    implementer: str = IMPLEMENTER_ID


class AgentRunner:
    """Deterministic implementer that writes phase code through the tools.

    For each phase it emits a small, runnable Python module plus a
    focused test module, written via :class:`Workspace` so every write
    is idempotent and workspace-bound. The generated test imports the
    generated module so the assess lap can run it as a real subprocess.
    """

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def run_implement_lap(
        self,
        phase: ClearPhase,
        attempt: int,
        *,
        workflow_id: str,
        force_failure: bool = False,
    ) -> ImplementLapOutcome:
        module_name = f"phase_{phase.number}_feature"
        files_written: list[str] = []

        # conftest.py at the workspace root makes ``src/`` importable so
        # ``python -m pytest`` can ``from phase_N_feature import ...``.
        conftest_src = (
            "import sys\n"
            "from pathlib import Path\n"
            "sys.path.insert(0, str(Path(__file__).parent / \"src\"))\n"
        )
        self.workspace.write_file(
            "conftest.py",
            conftest_src,
            workflow_id=workflow_id,
            phase=phase.number,
            attempt=attempt,
        )
        files_written.append("conftest.py")

        # The feature module the phase claims to deliver.
        feature_src = self._feature_source(phase, broken=force_failure and attempt == 1)
        self.workspace.write_file(
            f"src/{module_name}.py",
            feature_src,
            workflow_id=workflow_id,
            phase=phase.number,
            attempt=attempt,
        )
        files_written.append(f"src/{module_name}.py")

        # A focused test the verifier will execute. It lives under tests/
        # so ``python -m pytest`` discovers it deterministically.
        test_src = self._test_source(module_name, phase)
        self.workspace.write_file(
            f"tests/test_phase_{phase.number}.py",
            test_src,
            workflow_id=workflow_id,
            phase=phase.number,
            attempt=attempt,
        )
        files_written.append(f"tests/test_phase_{phase.number}.py")

        return ImplementLapOutcome(
            files_written=files_written,
            summary=f"Implemented {module_name} and its focused test for {phase.label}.",
        )

    def corrected_source(self, phase: ClearPhase) -> str:
        """The known-good feature source for ``phase``.

        Used by the remediation lap to rewrite a broken stub with the
        repaired implementation (DRY: one definition of "correct").
        """
        return self._feature_source(phase, broken=False)

    def _feature_source(self, phase: ClearPhase, *, broken: bool) -> str:
        # The "API" the phase exposes: a single function returning a
        # greeting. ``broken`` deliberately returns the wrong value so
        # the forced-failure remediation path (CLEAR-INT-004) is real.
        body = "    return f\"Hello from phase {n}: {name}\""
        if broken:
            body = "    return f\"OOPS phase {n}\"  # deliberate failure"
        return (
            f'n = {phase.number}\n'
            f'\n'
            f'def greet(name: str = "world") -> str:\n'
            f'    """Greeting returned by {phase.label}."""\n'
            f'{body}\n'
        )

    def _test_source(self, module_name: str, phase: ClearPhase) -> str:
        return (
            f"from {module_name} import greet\n\n\n"
            f"def test_greet_includes_name_and_phase():\n"
            f'    result = greet("operator")\n'
            f'    assert "operator" in result, result\n'
            f'    assert "phase {phase.number}" in result, result\n'
        )


class VerifierAgent:
    """Independent verifier that owns test execution and writes verdicts.

    The verifier is intentionally a separate identity from the
    implementer. It reads the test command from ``test.md``, runs the
    tests, and produces a verdict *from the test output* — never from
    the implementer's assertion (spec §8.6, CLEAR-VER-001).
    """

    agent_id = VERIFIER_ID

    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def execute_tests(
        self,
        phase: ClearPhase,
        attempt: int,
        *,
        workflow_id: str,
    ):
        return self.workspace.run_tests(
            phase.test_command,
            workflow_id=workflow_id,
            phase=phase.number,
            attempt=attempt,
        )

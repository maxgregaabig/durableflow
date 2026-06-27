"""CLEAR phase runner state and the ``plan.md`` parser.

The phase runner is a store-backed micro state machine that lives inside
the ``phase_runner`` macro step (spec §6.4). Its state round-trips
through JSON so it can be checkpointed after every lap and resumed after
a crash (CLEAR-UNIT-001). The parser turns a deterministic ``plan.md``
into a list of phases (CLEAR-UNIT-002).

Python standard library only.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# Allowed enums (spec §6.4) ---------------------------------------------------
PHASE_STATUSES: tuple[str, ...] = ("implementing", "assessing", "remediating", "passed", "blocked")
NEXT_ACTIONS: tuple[str, ...] = ("advance", "remediate", "replan", "ship", "blocked")

PhaseStatus = Literal["implementing", "assessing", "remediating", "passed", "blocked"]
NextAction = Literal["advance", "remediate", "replan", "ship", "blocked"] | None
LapKind = Literal["implement", "assess", "remediate"]
LapStatus = Literal["in_progress", "passed", "failed"]


@dataclass(frozen=True)
class ClearClaim:
    """A falsifiable claim attached to a phase."""

    claim_id: str
    claim_text: str


@dataclass(frozen=True)
class ClearPhase:
    """One implementation phase parsed from ``plan.md``."""

    number: int
    name: str
    test_command: str
    claims: tuple[ClearClaim, ...] = ()

    @property
    def label(self) -> str:
        """User-facing phase label, e.g. ``Phase 2: API Layer``."""
        return f"Phase {self.number}: {self.name}"


@dataclass
class ClearLapResult:
    """One lap within an attempt, recorded in lap_history (append-only)."""

    phase: int
    attempt: int
    lap_kind: LapKind
    status: LapStatus
    report: str | None = None
    evidence: list[str] = field(default_factory=list)
    failed_assertions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClearLapResult":
        return cls(
            phase=int(data["phase"]),
            attempt=int(data["attempt"]),
            lap_kind=data["lap_kind"],  # type: ignore[arg-type]
            status=data["status"],  # type: ignore[arg-type]
            report=data.get("report"),
            evidence=list(data.get("evidence") or []),
            failed_assertions=list(data.get("failed_assertions") or []),
        )


@dataclass
class ClearPhaseState:
    """Full micro state of the phase runner, checkpointed after every lap.

    Spec §6.4 shapes this object. It is JSON-serializable so a crash
    mid-``phase_runner`` resumes on the correct phase and attempt without
    repeating prior write side effects (CLEAR-INT-003).
    """

    current_phase: int = 1
    attempt: int = 1
    phase_status: PhaseStatus = "implementing"
    next_action: NextAction = None
    last_report: str | None = None
    mounted_artifact_ids: list[str] = field(default_factory=list)
    lap_history: list[ClearLapResult] = field(default_factory=list)
    max_attempts: int = 3
    completed_phases: list[int] = field(default_factory=list)
    blocked_reason: str | None = None
    # Verdicts collected during the run but recorded only after the build is
    # finalized (spec §10.2: verified_at must post-date build_completed_at).
    pending_verifications: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_phase": self.current_phase,
            "attempt": self.attempt,
            "phase_status": self.phase_status,
            "next_action": self.next_action,
            "last_report": self.last_report,
            "mounted_artifact_ids": list(self.mounted_artifact_ids),
            "lap_history": [lap.to_dict() for lap in self.lap_history],
            "max_attempts": self.max_attempts,
            "completed_phases": list(self.completed_phases),
            "blocked_reason": self.blocked_reason,
            "pending_verifications": list(self.pending_verifications),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClearPhaseState":
        return cls(
            current_phase=int(data.get("current_phase", 1)),
            attempt=int(data.get("attempt", 1)),
            phase_status=data.get("phase_status", "implementing"),  # type: ignore[arg-type]
            next_action=data.get("next_action"),  # type: ignore[arg-type]
            last_report=data.get("last_report"),
            mounted_artifact_ids=list(data.get("mounted_artifact_ids") or []),
            lap_history=[
                ClearLapResult.from_dict(item)
                for item in (data.get("lap_history") or [])
            ],
            max_attempts=int(data.get("max_attempts", 3)),
            completed_phases=list(data.get("completed_phases") or []),
            blocked_reason=data.get("blocked_reason"),
            pending_verifications=list(data.get("pending_verifications") or []),
        )

    def append_lap(self, lap: ClearLapResult) -> None:
        """Append a lap to the append-only history."""
        self.lap_history.append(lap)


class PhasePlanParser:
    """Parse deterministic phase entries from a ``plan.md`` document.

    Recognised phase header (CLEAR-UNIT-002)::

        ## Phase N: <Name>
        Test: <command>
        Claim <claim_id>: <text>

    Phases must be numbered sequentially starting at 1. Ambiguous or
    malformed plans raise ``ValueError``.
    """

    _PHASE_HEADER = re.compile(r"^##\s+Phase\s+(\d+)\s*:\s*(.+?)\s*$")
    _TEST_LINE = re.compile(r"^Test:\s*(.+?)\s*$")
    _CLAIM_LINE = re.compile(r"^Claim\s+([A-Za-z0-9\-]+)\s*:\s*(.+?)\s*$")

    def parse(self, plan_md: str) -> list[ClearPhase]:
        phases: list[ClearPhase] = []
        current: ClearPhase | None = None

        for raw_line in plan_md.splitlines():
            line = raw_line.rstrip()
            header = self._PHASE_HEADER.match(line)
            if header:
                if current is not None:
                    phases.append(current)
                number = int(header.group(1))
                name = header.group(2).strip()
                if not name:
                    raise ValueError(f"Phase {number} has no name")
                current = ClearPhase(number=number, name=name, test_command="", claims=())
                continue

            if current is None:
                continue

            test_match = self._TEST_LINE.match(line)
            if test_match:
                command = test_match.group(1).strip()
                if not command:
                    raise ValueError(
                        f"Phase {current.number} declares an empty Test command"
                    )
                current = ClearPhase(
                    number=current.number,
                    name=current.name,
                    test_command=command,
                    claims=current.claims,
                )
                continue

            claim_match = self._CLAIM_LINE.match(line)
            if claim_match:
                claim = ClearClaim(
                    claim_id=claim_match.group(1).strip(),
                    claim_text=claim_match.group(2).strip(),
                )
                current = ClearPhase(
                    number=current.number,
                    name=current.name,
                    test_command=current.test_command,
                    claims=(*current.claims, claim),
                )

        if current is not None:
            phases.append(current)

        self._validate(phases)
        return phases

    def _validate(self, phases: list[ClearPhase]) -> None:
        if not phases:
            raise ValueError("plan.md declared no phases")
        expected = 1
        for phase in phases:
            if phase.number != expected:
                raise ValueError(
                    f"phases must be sequential starting at 1; "
                    f"expected Phase {expected}, saw Phase {phase.number}"
                )
            if not phase.test_command:
                raise ValueError(
                    f"Phase {phase.number} ('{phase.name}') declares no Test command"
                )
            expected += 1
        # reject duplicate phase names (ambiguous plan)
        names = [p.name for p in phases]
        if len(set(names)) != len(names):
            raise ValueError("plan.md declared duplicate phase names")

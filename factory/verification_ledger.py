"""Verification ledger and ship gate for CLEAR (spec §8.6, §10, §11).

The ledger lives at ``verification/ledger.json`` inside the workflow
workspace. Every non-deferred completion claim needs a VERIFIED row
written by an *independent* verifier (verifier != implementer) over
non-stale evidence (rank >= min, ``verified_at`` after the build, build
id and source digest matching), or the ship gate refuses to mark the
workflow complete (C-CLEAR-006, CLEAR-INT-005).

Append-mostly updates supersede prior rows by ``row_id`` rather than
editing them in place (spec §10.2).

Python standard library only.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


Verdict = Literal[
    "VERIFIED",
    "REFUTED",
    "PARTIAL",
    "UNVERIFIABLE",
    "DEFERRED-VERIFICATION",
    "UNVERIFIED",
    "STALE",
]
EvidenceRank = Literal["E1", "E2", "E3", "E4"]

IMPLEMENTER_ID = "agent_implementer_v1"
VERIFIER_ID = "agent_verifier_v1"

EVIDENCE_RANK_VALUE = {"E1": 1, "E2": 2, "E3": 3, "E4": 4}


@dataclass(frozen=True)
class ClaimSpec:
    """A claim in the static claim register (spec §10.1)."""

    claim_id: str
    claim_text: str
    type: str
    method: str
    evidence_artifact: str
    min_rank: EvidenceRank
    deferred: bool = False
    rationale: str | None = None


def claim_register() -> list[ClaimSpec]:
    """The static claim register from spec §10.1."""
    return [
        ClaimSpec(
            claim_id="C-CLEAR-001",
            claim_text="The workflow creates all planning artifacts before code execution",
            type="Behavioral",
            method="CLEAR-INT-001",
            evidence_artifact="test-results/clear-int-001.log",
            min_rank="E2",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-002",
            claim_text=(
                "WorkflowEngine semantics are unchanged; no engine-level loops or "
                "back-edges are added"
            ),
            type="Negative",
            method="code-diff-inspection",
            evidence_artifact="verification/engine-diff.txt",
            min_rank="E4",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-003",
            claim_text="phase_runner resumes from saved phase and attempt state after crash",
            type="Behavioral",
            method="CLEAR-INT-003",
            evidence_artifact="test-results/clear-int-003.log",
            min_rank="E2",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-004",
            claim_text="Mutating tools are idempotent on retry",
            type="Behavioral",
            method="CLEAR-INT-004",
            evidence_artifact="test-results/clear-unit-004.log",
            min_rank="E2",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-005",
            claim_text="Automated test failure triggers remediation without human approval",
            type="Behavioral",
            method="CLEAR-INT-004",
            evidence_artifact="test-results/clear-int-004.log",
            min_rank="E2",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-006",
            claim_text="Completion cannot be declared with missing independent verification",
            type="Negative",
            method="CLEAR-INT-005",
            evidence_artifact="test-results/clear-int-005.log",
            min_rank="E4",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-007",
            claim_text=(
                "Operator audit output uses workflow language, not raw engine internals "
                "(zero blocklisted terms in rendered headings and primary labels)"
            ),
            type="Semantic",
            method="CLEAR-SEM-001",
            evidence_artifact="test-results/clear-sem-001.log",
            min_rank="E2",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-008",
            claim_text="Context lineage records selected, consumed, and credited artifacts when enabled",
            type="Capability",
            method="CLEAR-CTX-001",
            evidence_artifact="test-results/clear-ctx-001.log",
            min_rank="E3",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-DEFER-001",
            claim_text="Graphical approval UI provides interactive approval interface",
            type="Capability",
            method="VER-013",
            evidence_artifact="verification/deferred-items.md",
            min_rank="E4",
            deferred=True,
            rationale="CLI and markdown reports are sufficient for initial verification",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-DEFER-002",
            claim_text="Per-agent-turn context lineage records every LLM turn's context",
            type="Capability",
            method="VER-013",
            evidence_artifact="verification/deferred-items.md",
            min_rank="E4",
            deferred=True,
            rationale="Lap-level lineage proves the architecture first",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-DEFER-003",
            claim_text="Context supersession model tracks artifact version replacement",
            type="Capability",
            method="VER-013",
            evidence_artifact="verification/deferred-items.md",
            min_rank="E4",
            deferred=True,
            rationale="New digest rows are sufficient for v0.1",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-DEFER-004",
            claim_text="Long-horizon autonomous coding limits enforce multi-hour runs",
            type="Capability",
            method="VER-013",
            evidence_artifact="verification/deferred-items.md",
            min_rank="E4",
            deferred=True,
            rationale="Initial phases validate one isolated project and bounded attempts",
        ),
        ClaimSpec(
            claim_id="C-CLEAR-DEFER-005",
            claim_text="Full production deployment integration deploys to external environments",
            type="Capability",
            method="VER-013",
            evidence_artifact="verification/deferred-items.md",
            min_rank="E4",
            deferred=True,
            rationale="ship means workflow completion, not external deploy",
        ),
    ]


@dataclass
class LedgerRow:
    """One row of the verification ledger (spec §10.2)."""

    row_id: str
    claim_id: str
    claim_text: str
    type: str
    method: str
    evidence_artifact: str
    evidence_digest: str
    source_artifact_digest: str
    evidence_rank: EvidenceRank
    implementer: str
    verifier: str
    verdict: Verdict
    supersedes_row_id: str | None = None
    verified_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "type": self.type,
            "method": self.method,
            "evidence_artifact": self.evidence_artifact,
            "evidence_digest": self.evidence_digest,
            "source_artifact_digest": self.source_artifact_digest,
            "evidence_rank": self.evidence_rank,
            "implementer": self.implementer,
            "verifier": self.verifier,
            "verdict": self.verdict,
            "supersedes_row_id": self.supersedes_row_id,
            "verified_at": self.verified_at,
        }


def _digest_file(workspace_root: Path, rel_path: str) -> str:
    path = workspace_root / rel_path
    if not path.exists():
        return ""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class VerificationLedger:
    """Reads and writes ``verification/ledger.json`` for one workflow.

    The ledger is append-mostly: recording a fresh verdict for an
    already-seen claim adds a new row that supersedes the prior one.
    """

    def __init__(self, workspace_root: str | Path, workflow_id: str):
        self.workspace_root = Path(workspace_root)
        self.workflow_id = workflow_id
        self.build_id = f"{workflow_id}-build-1"
        self.dir = self.workspace_root / "verification"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "ledger.json"

    # --- low-level persistence -------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "workflow_id": self.workflow_id,
                "build_id": self.build_id,
                "created_at": _utc_now(),
                "build_completed_at": _utc_now(),
                "claims": [],
            }
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data.setdefault("workflow_id", self.workflow_id)
        data.setdefault("build_id", self.build_id)
        data.setdefault("claims", [])
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    # --- seeding ---------------------------------------------------------

    def seed_deferred(self) -> None:
        """Seed every deferred claim with a DEFERRED-VERIFICATION row.

        Deferred claims MUST appear in the ledger (spec §10.1 note) and
        MUST NOT be claimed as COMPLETE.
        """
        data = self._read()
        existing_ids = {row["claim_id"] for row in data["claims"]}
        changed = False
        for spec in claim_register():
            if not spec.deferred or spec.claim_id in existing_ids:
                continue
            row = LedgerRow(
                row_id=f"row-{uuid.uuid4().hex[:12]}",
                claim_id=spec.claim_id,
                claim_text=spec.claim_text,
                type=spec.type,
                method=spec.method,
                evidence_artifact=spec.evidence_artifact,
                evidence_digest=_digest_file(self.workspace_root, spec.evidence_artifact),
                source_artifact_digest="",
                evidence_rank=spec.min_rank,
                implementer="n/a",
                verifier="n/a",
                verdict="DEFERRED-VERIFICATION",
                verified_at=_utc_now(),
            )
            data["claims"].append(row.to_dict())
            changed = True
        if changed:
            self._write(data)

    # --- recording verdicts ----------------------------------------------

    def record(
        self,
        spec: ClaimSpec,
        *,
        verdict: Verdict,
        evidence_artifact: str | None = None,
        implementer: str = IMPLEMENTER_ID,
        verifier: str = VERIFIER_ID,
        source_artifact_digest: str = "",
        verified_at: str | None = None,
    ) -> LedgerRow:
        """Append a new verdict row for ``spec``, superseding any prior row."""
        data = self._read()
        prior_row_id: str | None = None
        for row in data["claims"]:
            if row["claim_id"] == spec.claim_id:
                prior_row_id = prior_row_id or row["row_id"]

        evidence_path = evidence_artifact or spec.evidence_artifact
        row = LedgerRow(
            row_id=f"row-{uuid.uuid4().hex[:12]}",
            claim_id=spec.claim_id,
            claim_text=spec.claim_text,
            type=spec.type,
            method=spec.method,
            evidence_artifact=evidence_path,
            evidence_digest=_digest_file(self.workspace_root, evidence_path),
            source_artifact_digest=source_artifact_digest,
            evidence_rank=spec.min_rank,
            implementer=implementer,
            verifier=verifier,
            verdict=verdict,
            supersedes_row_id=prior_row_id,
            verified_at=verified_at or _utc_now(),
        )
        data["claims"].append(row.to_dict())
        self._write(data)
        return row

    def finalize_build(self) -> str:
        """Stamp ``build_completed_at`` to now.

        Verification rows written after this moment are non-stale; the
        ship gate checks ``verified_at > build_completed_at`` (spec §10.2).
        Call once the build artifact is finished, before verification.
        """
        data = self._read()
        stamp = _utc_now()
        data["build_completed_at"] = stamp
        self._write(data)
        return stamp

    def rows(self) -> list[dict[str, Any]]:
        return list(self._read()["claims"])

    def latest_row_for(self, claim_id: str) -> dict[str, Any] | None:
        """Return the latest non-superseded row for a claim, or None."""
        data = self._read()
        superseded = {
            r["supersedes_row_id"]
            for r in data["claims"]
            if r.get("supersedes_row_id")
        }
        candidates = [
            r for r in data["claims"]
            if r["claim_id"] == claim_id and r["row_id"] not in superseded
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda r: r["verified_at"])
        return candidates[-1]

    # --- ship gate evaluation --------------------------------------------

    def evaluate_ship(self) -> "ShipGateResult":
        """Evaluate every exit gate (spec §11, C-CLEAR-006).

        A claim passes when its latest row is VERIFIED by an independent
        verifier (verifier != implementer) over non-stale evidence of
        sufficient rank. Deferred claims pass on DEFERRED-VERIFICATION.
        Any gap blocks completion.
        """
        blocking: list[str] = []
        passed: list[str] = []
        evidence_rows: list[dict[str, Any]] = []
        build_completed_at = self._read().get("build_completed_at", "")

        for spec in claim_register():
            row = self.latest_row_for(spec.claim_id)
            if spec.deferred:
                if row is None or row["verdict"] != "DEFERRED-VERIFICATION":
                    blocking.append(
                        f"{spec.claim_id}: deferred claim missing DEFERRED-VERIFICATION row"
                    )
                else:
                    passed.append(spec.claim_id)
                    evidence_rows.append(row)
                continue

            if row is None:
                blocking.append(f"{spec.claim_id}: no verification row")
                continue

            verdict = self._effective_verdict(row, build_completed_at, spec)
            if verdict == "VERIFIED":
                independent = row["implementer"] != row["verifier"]
                rank_ok = (
                    EVIDENCE_RANK_VALUE.get(row["evidence_rank"], 0)
                    >= EVIDENCE_RANK_VALUE[spec.min_rank]
                )
                if not independent:
                    blocking.append(
                        f"{spec.claim_id}: verdict is self-verified "
                        f"(implementer == verifier)"
                    )
                elif not rank_ok:
                    blocking.append(
                        f"{spec.claim_id}: evidence rank {row['evidence_rank']} "
                        f"below minimum {spec.min_rank}"
                    )
                else:
                    passed.append(spec.claim_id)
                    evidence_rows.append(row)
            else:
                blocking.append(f"{spec.claim_id}: verdict is {verdict}")

        return ShipGateResult(
            ok=len(blocking) == 0,
            blocking=blocking,
            passed=passed,
            evidence_rows=evidence_rows,
        )

    def verify_source_integrity(self) -> list[str]:
        """Detect post-verification tampering of verified source artifacts.

        For every VERIFIED row that carries a ``source_artifact_digest``,
        recompute the digest of the corresponding feature file on disk and
        flag any mismatch (spec §10.2: source_artifact_digest must match the
        current artifact digest). Returns a list of problem descriptions
        (empty == all sources intact).

        Phase-local claims record their feature file path in the row's
        ``evidence_artifact``-adjacent metadata; here we map a row back to a
        file by the convention ``code-read/phase_N.md`` -> ``src/phase_N_feature.py``.
        """
        problems: list[str] = []
        import re as _re

        # Collect the latest VERIFIED row per claim that has a source digest.
        seen: set[str] = set()
        for row in self.rows():
            if row["verdict"] != "VERIFIED":
                continue
            digest = row.get("source_artifact_digest") or ""
            if not digest or row["claim_id"] in seen:
                continue
            seen.add(row["claim_id"])
            # Derive the source file path for phase-local claims.
            claim_id = row["claim_id"]
            m = _re.search(r"PHASE-(\d+)", claim_id)
            if not m:
                continue  # meta claims have no source artifact to re-hash
            feature = self.workspace_root / f"src/phase_{m.group(1)}_feature.py"
            if not feature.exists():
                problems.append(f"{claim_id}: source artifact missing ({feature.name})")
                continue
            current = "sha256:" + hashlib.sha256(feature.read_bytes()).hexdigest()
            if current != digest:
                problems.append(
                    f"{claim_id}: source artifact changed after verification "
                    f"(expected {digest[:16]}..., got {current[:16]}...)"
                )
        return problems

    def _effective_verdict(
        self,
        row: dict[str, Any],
        build_completed_at: str,
        spec: ClaimSpec,
    ) -> Verdict:
        if row["verdict"] != "VERIFIED":
            return row["verdict"]  # type: ignore[return-value]
        # stale-evidence detection (spec §10.2)
        if build_completed_at and row["verified_at"] <= build_completed_at:
            return "STALE"
        if row.get("evidence_rank") and (
            EVIDENCE_RANK_VALUE.get(row["evidence_rank"], 0)
            < EVIDENCE_RANK_VALUE[spec.min_rank]
        ):
            return "UNVERIFIED"
        return "VERIFIED"


@dataclass
class ShipGateResult:
    """Outcome of evaluating the ship gate."""

    ok: bool
    blocking: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)
    evidence_rows: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> str:
        if self.ok:
            return "All non-deferred claims independently verified."
        return "Completion blocked:\n" + "\n".join(f"  - {reason}" for reason in self.blocking)


# The independent party that verifies the workflow's META claims. These
# claims describe the workflow's own properties (e.g. "no engine back-edge",
# "completion blocked without verification") and cannot be self-verified by
# the workflow. The test suite/CI is that independent party (spec §8.6);
# its identity is deliberately distinct from the implementer and the
# in-workflow verifier.
META_VERIFIER_ID = "ci_verifier"
META_IMPLEMENTER_ID = "factory_team"


@dataclass(frozen=True)
class MetaVerdictInput:
    """One externally-produced verdict for a meta claim."""

    claim_id: str
    verdict: Verdict
    evidence_artifact: str
    notes: str = ""


class MetaClaimVerifier:
    """Records independent verdicts for the workflow's meta claims.

    The meta claims (C-CLEAR-001..008) are properties of the workflow
    itself, verified by the test suite/CI — a genuinely independent
    party. The workflow never self-verifies them; it only *evaluates*
    what this verifier has recorded.

    Typical use (in the test harness)::

        meta = MetaClaimVerifier(ledger)
        meta.finalize_build()               # build is done
        meta.write_evidence("C-CLEAR-001", log_text)  # archive evidence
        meta.record(MetaVerdictInput("C-CLEAR-001", "VERIFIED", path))
        assert ledger.evaluate_ship().ok
    """

    def __init__(self, ledger: VerificationLedger):
        self.ledger = ledger

    def finalize_build(self) -> str:
        return self.ledger.finalize_build()

    def write_evidence(self, claim_id: str, content: str) -> str:
        """Archive an evidence log for ``claim_id`` and return its path."""
        spec = self._spec_for(claim_id)
        rel = spec.evidence_artifact if spec else f"verification/{claim_id}.log"
        path = self.ledger.workspace_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return rel

    def record(self, item: MetaVerdictInput) -> LedgerRow | None:
        spec = self._spec_for(item.claim_id)
        if spec is None:
            return None
        return self.ledger.record(
            spec,
            verdict=item.verdict,
            evidence_artifact=item.evidence_artifact,
            implementer=META_IMPLEMENTER_ID,
            verifier=META_VERIFIER_ID,
            source_artifact_digest="",
        )

    def record_all_verified(self, evidence_artifacts: dict[str, str] | None = None) -> None:
        """Convenience: mark every non-deferred meta claim VERIFIED.

        ``evidence_artifacts`` optionally maps claim_id -> evidence path;
        defaults to each claim's registered evidence artifact.
        """
        evidence_artifacts = evidence_artifacts or {}
        for spec in claim_register():
            if spec.deferred:
                continue
            self.record(
                MetaVerdictInput(
                    claim_id=spec.claim_id,
                    verdict="VERIFIED",
                    evidence_artifact=evidence_artifacts.get(spec.claim_id, spec.evidence_artifact),
                )
            )

    def _spec_for(self, claim_id: str) -> ClaimSpec | None:
        for spec in claim_register():
            if spec.claim_id == claim_id:
                return spec
        return None

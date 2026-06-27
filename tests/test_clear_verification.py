"""CLEAR verification + ship gate tests.

Covers CLEAR-INT-005 (completion refused when any non-deferred claim
lacks a current VERIFIED ledger row with an independent verifier) and
CLEAR-VER-001 (capability claims require executed evidence, not
implementer assertion).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from factory import ShipBlockedError, claim_register
from factory.verification_ledger import (
    IMPLEMENTER_ID,
    META_IMPLEMENTER_ID,
    META_VERIFIER_ID,
    ClaimSpec,
    MetaClaimVerifier,
    VerificationLedger,
)
from src.store import WorkflowStatus
from tests.clear_conftest import make_engine


def _build_ledger(tmp_path: Path) -> VerificationLedger:
    return VerificationLedger(tmp_path / "ws", "wf-v")


def test_verification_ledger_seeds_deferred_claims(tmp_path: Path) -> None:
    ledger = _build_ledger(tmp_path)
    ledger.seed_deferred()
    rows = ledger.rows()
    deferred_ids = {r["claim_id"] for r in rows}
    expected_deferred = {c.claim_id for c in claim_register() if c.deferred}
    assert expected_deferred.issubset(deferred_ids)
    for row in rows:
        if row["claim_id"] in expected_deferred:
            assert row["verdict"] == "DEFERRED-VERIFICATION"


def test_clear_int_005_ship_refuses_without_verification(tmp_path: Path) -> None:
    """No meta verdicts recorded -> ship blocks -> workflow not completed."""
    eng, store, approval, _ws, _wf = make_engine(tmp_path)
    workflow_id = "wf-noverify"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    with pytest.raises(ShipBlockedError) as exc_info:
        eng.resume(workflow_id)

    # The workflow is NOT marked completed.
    assert store.load_workflow(workflow_id).status != WorkflowStatus.COMPLETED
    # At least one meta claim is reported as unverified.
    assert any("no verification row" in r or "UNVERIFIED" in r for r in exc_info.value.blocking)


def test_clear_int_005_ship_refuses_on_self_verified_row(tmp_path: Path) -> None:
    """A VERIFIED row where implementer == verifier does not count."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-self"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # Drive phase_runner to completion via the blocked-ship path.
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    # Overwrite every meta claim with a SELF-VERIFIED row (same party).
    ledger = VerificationLedger(ws_root, workflow_id)
    ledger.seed_deferred()
    ledger.finalize_build()
    for spec in claim_register():
        if spec.deferred:
            continue
        ledger.record(
            spec,
            verdict="VERIFIED",
            implementer=IMPLEMENTER_ID,
            verifier=IMPLEMENTER_ID,  # self-verified
        )

    gate = ledger.evaluate_ship()
    assert gate.ok is False
    assert any("self-verified" in r for r in gate.blocking)


def test_clear_int_005_ship_refuses_on_stale_evidence(tmp_path: Path) -> None:
    """A VERIFIED row whose verified_at predates the build is STALE."""
    ledger = _build_ledger(tmp_path)
    ledger.seed_deferred()
    build_at = ledger.finalize_build()
    # Write a verdict with a timestamp BEFORE the build (stale).
    stale_ts = "2000-01-01T00:00:00+00:00"
    spec = next(c for c in claim_register() if c.claim_id == "C-CLEAR-001")
    ledger.record(
        spec,
        verdict="VERIFIED",
        implementer=META_IMPLEMENTER_ID,
        verifier=META_VERIFIER_ID,
        verified_at=stale_ts,
    )
    gate = ledger.evaluate_ship()
    assert gate.ok is False
    assert any("STALE" in r or "C-CLEAR-001" in r for r in gate.blocking)


def test_clear_int_005_ship_passes_when_all_independently_verified(
    tmp_path: Path,
) -> None:
    """Full golden path: independent meta verdicts let ship complete."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-gold"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)

    # First resume: phase_runner runs, ship blocks on meta claims.
    with pytest.raises(ShipBlockedError):
        eng.resume(workflow_id)

    # Independent test-harness party records verdicts over real evidence.
    ledger = VerificationLedger(ws_root, workflow_id)
    meta = MetaClaimVerifier(ledger)
    meta.finalize_build()
    for spec in claim_register():
        if spec.deferred:
            continue
        meta.write_evidence(spec.claim_id, f"PASS: {spec.claim_id}")
    meta.record_all_verified()

    # Second resume: ship passes, workflow completes.
    state = eng.resume(workflow_id)
    assert state.status == WorkflowStatus.COMPLETED
    ship_out = store.load_workflow(workflow_id).step_data["ship"]
    assert ship_out["shipped"] is True
    assert "audit_path" in ship_out


def test_clear_ver_001_capability_claim_requires_executed_evidence(
    tmp_path: Path,
) -> None:
    """CLEAR-VER-001: a capability claim with implementer-only evidence is refused.

    The implementer writing 'I made it' (E5) is never sufficient; the
    gate requires an independent verifier and admissible evidence.
    """
    ledger = _build_ledger(tmp_path)
    ledger.seed_deferred()
    ledger.finalize_build()
    spec = ClaimSpec(
        claim_id="C-CLEAR-008",
        claim_text="Context lineage records selected/consumed/credited",
        type="Capability",
        method="CLEAR-CTX-001",
        evidence_artifact="test-results/clear-ctx-001.log",
        min_rank="E3",
    )
    # Implementer-only verdict: same party produced and verified.
    ledger.record(
        spec,
        verdict="VERIFIED",
        implementer=IMPLEMENTER_ID,
        verifier=IMPLEMENTER_ID,
    )
    gate = ledger.evaluate_ship()
    c8 = [r for r in gate.blocking if r.startswith("C-CLEAR-008")]
    assert c8, "self-verified capability claim should block ship"


def test_verification_ledger_is_append_mostly(tmp_path: Path) -> None:
    """Re-recording a claim supersedes the prior row without editing it."""
    ledger = _build_ledger(tmp_path)
    ledger.seed_deferred()
    ledger.finalize_build()
    spec = next(c for c in claim_register() if c.claim_id == "C-CLEAR-001")
    first = ledger.record(spec, verdict="REFUTED", verifier=META_VERIFIER_ID)
    second = ledger.record(spec, verdict="VERIFIED", verifier=META_VERIFIER_ID)

    assert second.supersedes_row_id == first.row_id
    rows_for_claim = [r for r in ledger.rows() if r["claim_id"] == "C-CLEAR-001"]
    assert len(rows_for_claim) == 2  # both rows preserved
    assert ledger.latest_row_for("C-CLEAR-001")["verdict"] == "VERIFIED"


def test_source_integrity_detects_post_verification_tampering(tmp_path: Path) -> None:
    """Spec §10.2: changing a verified source artifact after verification blocks ship."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-tamper"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)  # phase_runner records a VERIFIED source digest
    except ShipBlockedError:
        pass

    ledger = VerificationLedger(ws_root, workflow_id)
    # No tampering yet -> no problems.
    assert ledger.verify_source_integrity() == []

    # Tamper with the verified feature source AFTER verification.
    feature = ws_root / "src" / "phase_1_feature.py"
    assert feature.exists()
    feature.write_text("# tampered\n", encoding="utf-8")

    problems = ledger.verify_source_integrity()
    assert problems, "expected a source-integrity problem after tampering"
    assert any("phase_1" in p.lower() or "PHASE-1" in p for p in problems)


def test_phase_claims_carry_real_source_digest(tmp_path: Path) -> None:
    """source_artifact_digest is the real SHA-256 of the feature, not empty."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-digest"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    ledger = VerificationLedger(ws_root, workflow_id)
    phase_rows = [
        r for r in ledger.rows()
        if "PHASE-" in r["claim_id"] and r["source_artifact_digest"]
    ]
    assert phase_rows, "expected phase-local claims with a source digest"
    import hashlib

    feature = (ws_root / "src" / "phase_1_feature.py").read_bytes()
    expected = "sha256:" + hashlib.sha256(feature).hexdigest()
    assert any(r["source_artifact_digest"] == expected for r in phase_rows)


def test_verifier_records_code_read_evidence(tmp_path: Path) -> None:
    """VER-001: the verifier leaves an independent code-read note on disk."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-coderead"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    note = ws_root / "code-read" / "phase_1.md"
    assert note.exists()
    text = note.read_text()
    # The note records an independent read of the actual source, not just a
    # test-name mention.
    assert "Independent verifier" in text
    assert "phase_1_feature" in text or "def greet" in text or "Behavior observed" in text


def test_finalize_build_precedes_phase_verdicts(tmp_path: Path) -> None:
    """Phase verdicts' verified_at strictly post-date build_completed_at."""
    eng, store, approval, ws_root, _wf = make_engine(tmp_path)
    workflow_id = "wf-order"
    state = store.create_workflow("clear", workflow_id=workflow_id)
    eng.execute(state.workflow_id)
    approval.approve(approval.get_for_workflow(workflow_id, "plan_approval").gate_id)
    try:
        eng.resume(workflow_id)
    except ShipBlockedError:
        pass

    import json as _json

    data = _json.loads((ws_root / "verification" / "ledger.json").read_text())
    build_at = data["build_completed_at"]
    for row in data["claims"]:
        if "PHASE-" in row["claim_id"] and row["verdict"] == "VERIFIED":
            assert row["verified_at"] > build_at, (
                f"{row['claim_id']} verified_at {row['verified_at']} "
                f"not after build_completed_at {build_at}"
            )

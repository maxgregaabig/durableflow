"""Golden-set manifest loading, validation, and mutation (spec §6.2, Phase 1).

A manifest names its eval cases by relative path, declares required scorers,
and records thresholds per scorer. Gate validation (§6.5 rules 5-6) lives in
``gate.py``; this module owns the manifest shape and load/append behavior.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .io import load_json, write_json_with_digest


@dataclass(frozen=True)
class EvalManifest:
    """Versioned collection of eval cases + required scorers + thresholds."""

    manifest_id: str
    version: int
    cases: list[str] = field(default_factory=list)
    required_scorers: list[str] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestValidation:
    """Result of validating a manifest for gate use."""

    ok: bool
    reasons: list[str]


def new_manifest(
    *,
    manifest_id: str | None = None,
    required_scorers: list[str] | None = None,
    thresholds: dict[str, float] | None = None,
) -> EvalManifest:
    """Create a fresh empty manifest."""
    return EvalManifest(
        manifest_id=manifest_id or f"manifest-{uuid.uuid4().hex[:12]}",
        version=1,
        cases=[],
        required_scorers=list(required_scorers or []),
        thresholds=dict(thresholds or {}),
    )


def load_eval_manifest(path: str | Path) -> EvalManifest:
    """Load a manifest from disk (tolerant of missing top-level digest)."""
    data = load_json(path)
    return EvalManifest(
        manifest_id=str(data.get("manifest_id") or Path(path).stem),
        version=int(data.get("version", 1)),
        cases=list(data.get("cases", [])),
        required_scorers=list(data.get("required_scorers", [])),
        thresholds={str(k): float(v) for k, v in dict(data.get("thresholds", {})).items()},
    )


def save_eval_manifest(manifest: EvalManifest, path: str | Path) -> str:
    """Persist a manifest with digest anchoring."""
    return write_json_with_digest(manifest, path)


def append_case_to_manifest(manifest_path: str | Path, eval_case_path: str) -> EvalManifest:
    """Append a case path to a manifest file, creating it if absent (spec §5).

    Returns the updated manifest. Paths are stored as given so callers control
    absolute vs relative conventions.
    """
    mpath = Path(manifest_path)
    if mpath.exists():
        manifest = load_eval_manifest(mpath)
    else:
        manifest = new_manifest()
    if eval_case_path not in manifest.cases:
        manifest = EvalManifest(
            manifest_id=manifest.manifest_id,
            version=manifest.version,
            cases=[*manifest.cases, eval_case_path],
            required_scorers=manifest.required_scorers,
            thresholds=manifest.thresholds,
        )
    save_eval_manifest(manifest, mpath)
    return manifest


def validate_for_gate(manifest: EvalManifest) -> ManifestValidation:
    """Apply §6.5 rules 5 and 6 (zero cases / zero required scorers -> incomplete)."""
    reasons: list[str] = []
    if not manifest.cases:
        reasons.append("manifest has no eval cases (rule §6.5.5: zero cases -> incomplete)")
    if not manifest.required_scorers:
        reasons.append(
            "manifest declares no required scorers (rule §6.5.6: no required scorers -> incomplete)"
        )
    return ManifestValidation(ok=not reasons, reasons=reasons)


def manifest_to_json(manifest: EvalManifest) -> dict[str, Any]:
    """Return the dict form of a manifest (handy for tests/CLI)."""
    return json.loads(json.dumps(_dataclass_to_dict(manifest), default=str, sort_keys=True))


def _dataclass_to_dict(obj: Any) -> Any:
    from dataclasses import asdict, is_dataclass

    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj


__all__ = [
    "EvalManifest",
    "ManifestValidation",
    "append_case_to_manifest",
    "load_eval_manifest",
    "manifest_to_json",
    "new_manifest",
    "save_eval_manifest",
    "validate_for_gate",
]

"""Deterministic JSON read/write with digest anchoring for eval gate artifacts.

Every artifact (eval case, manifest, gate report) is written as a JSON object
with stable key ordering plus a ``digest`` field holding the SHA-256 digest of
the canonical (sorted, no-digest, no-whitespace) payload. The digest is the
tamper-evidence anchor cited by gate evidence records (spec §10.1).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

# Top-level keys excluded from the digest so a digest change always reflects a
# payload change, never the digest field itself.
_META_KEYS = frozenset({"digest"})


def canonical_payload(obj: Any) -> str:
    """Canonical JSON (sorted keys, no extra whitespace) for ``obj``."""
    return json.dumps(_to_serializable(obj), sort_keys=True, separators=(",", ":"))


def payload_digest(obj: Any) -> str:
    """SHA-256 digest of the canonical payload, ``sha256:`` prefixed."""
    return "sha256:" + hashlib.sha256(canonical_payload(obj).encode("utf-8")).hexdigest()


def write_json_with_digest(obj: Any, output_path: str | Path) -> str:
    """Write ``obj`` as pretty JSON + digest, return the absolute path.

    The digest is computed over the canonical payload and stored under the
    top-level ``digest`` key. The on-disk document is human-readable
    (indent=2, sorted keys).
    """
    serializable = _to_serializable(obj)
    if not isinstance(serializable, dict):
        raise TypeError("eval artifacts must serialize to a JSON object")
    digest = payload_digest({k: v for k, v in serializable.items() if k not in _META_KEYS})
    serializable = {**serializable, "digest": digest}
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(serializable, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return str(path.resolve())


def write_artifact(obj: Any, output_path: str | Path) -> tuple[str, str]:
    """Write artifact and return ``(resolved_path, digest)``."""
    digest = payload_digest(obj)
    path = write_json_with_digest(obj, output_path)
    return path, digest


def load_json(path: str | Path) -> dict[str, Any]:
    """Load a JSON artifact from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def verify_digest(path: str | Path) -> bool:
    """Return True if the stored digest matches the recomputed payload digest."""
    data = load_json(path)
    stored = data.get("digest")
    if not isinstance(stored, str):
        return False
    recomputed = payload_digest({k: v for k, v in data.items() if k not in _META_KEYS})
    return stored == recomputed


def _to_serializable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_serializable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(item) for item in obj]
    return obj


__all__ = [
    "canonical_payload",
    "load_json",
    "payload_digest",
    "verify_digest",
    "write_artifact",
    "write_json_with_digest",
]

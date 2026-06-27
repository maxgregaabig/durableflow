"""Redaction for eval gate artifacts (spec §6.4).

Default export mode is ``digest_only``. Raw prompts and raw model responses are
represented by SHA-256 digests and byte lengths; unknown metadata keys are
dropped; oversized strings are replaced by a digest + truncated marker. Raw
export is DEFERRED (C-EVAL-DEFER-001) and not implemented here.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Default size cap for a single string value before it is replaced by a digest.
DEFAULT_MAX_STRING_BYTES = 512


def digest_value(value: str) -> str:
    """SHA-256 digest of ``value`` with the ``sha256:`` prefix convention."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_payloads(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace raw payload fields with digest + byte length (spec §6.4).

    Recognized raw fields (``raw_prompt``, ``raw_response``) become digest
    records. Every string value is size-capped; oversized strings become a
    digest + truncated marker.
    """
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in ("raw_prompt", "raw_response"):
            out[key] = _digest_record(value)
        else:
            out[key] = redact_value(value)
    return out


def _digest_record(value: Any) -> dict[str, Any]:
    if value is None:
        return {"digest": None, "bytes": 0}
    text = value if isinstance(value, str) else str(value)
    return {"digest": digest_value(text), "bytes": len(text.encode("utf-8"))}


def redact_value(value: Any, *, max_bytes: int = DEFAULT_MAX_STRING_BYTES) -> Any:
    """Recursively redact one value: cap strings, recurse into lists/dicts."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) <= max_bytes:
            return value
        return {
            "digest": digest_value(value),
            "truncated": True,
            "original_bytes": len(encoded),
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item, max_bytes=max_bytes) for item in list(value)[:64]]
    if isinstance(value, dict):
        return {
            str(k): redact_value(v, max_bytes=max_bytes)
            for k, v in list(value.items())[:64]
            if isinstance(k, str)
        }
    # Unknown types: digest of repr to avoid leaking arbitrary objects.
    return {"digest": digest_value(repr(value))}


def filter_allowlist(
    metadata: dict[str, Any], allowlist: frozenset[str]
) -> dict[str, Any]:
    """Drop any metadata keys not in ``allowlist`` (spec §6.4 tool args rule)."""
    return {key: redact_value(value) for key, value in metadata.items() if key in allowlist}


__all__ = [
    "DEFAULT_MAX_STRING_BYTES",
    "digest_payloads",
    "digest_value",
    "filter_allowlist",
    "redact_value",
]

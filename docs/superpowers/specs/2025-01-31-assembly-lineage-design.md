# Assembly Lineage Design Document

**Date:** 2025-01-31
**Author:** Marcos Polanco (with Claude)
**Status:** DRAFT
**Applies:** DurableFlow Context Extension v0.2 evolution
**Depends:** Context Extension v0.1 (complete)

---

## 1. Problem Statement

The v0.1 context ledger records `observed → selected → consumed → influential` events. This leaves a blind spot:

- What retrieval method produced the candidate set?
- What were the candidates that were NOT selected?
- What scores and ranks determined selection?
- Why was artifact A chosen over artifact B?

The missing primitive is **assembly lineage** — durable events that record how candidate information competed for limited context budget before model consumption.

---

## 2. Proposed Solution

Add two new artifact lifecycle event types to the existing context ledger:

- **`retrieved`**: Artifact returned by a retrieval step (search, index lookup, memory fetch)
- **`rejected`**: Artifact retrieved but explicitly excluded from selection

The extended lifecycle:

```
observed → retrieved → {selected, rejected} → consumed → influential
```

This is an additive change. No schema migration, no new tables, no framework behavior. The workflow drives retrieval and selection, then explicitly records events.

---

## 3. Event Metadata Contracts

Metadata is **contracted JSON** with strict validation. Unknown keys are rejected.

### `retrieved` Event

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `retrieval_method` | string | Yes | Non-empty string |
| `retrieval_score` | int/float | No | Numeric value |
| `rank_position` | int | No | Positive integer (≥1) |
| `retrieval_query_digest` | string | No | Non-empty string |

Only these four keys are allowed. Any other key in metadata causes rejection.

Example:
```json
{
  "retrieval_method": "bm25",
  "retrieval_score": 0.82,
  "rank_position": 4
}
```

### `rejected` Event

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| `rejection_reason` | string | Yes | Non-empty string |
| `retrieval_method` | string | No | Non-empty string |
| `retrieval_score` | int/float | No | Numeric value |
| `rank_position` | int | No | Positive integer (≥1) |

Only these four keys are allowed. Any other key in metadata causes rejection.

Example:
```json
{
  "rejection_reason": "token_budget",
  "retrieval_method": "bm25",
  "retrieval_score": 0.12,
  "rank_position": 37
}
```

---

## 4. Implementation Changes

### 4.1 `context/ledger.py`

Add new event types to the `ARTIFACT_EVENTS` set:

```python
ARTIFACT_EVENTS = {
    "observed",
    "retrieved",      # NEW
    "selected",
    "rejected",       # NEW
    "consumed",
}
```

Add metadata contracts with strict key validation:

```python
METADATA_CONTRACTS = {
    "retrieved": {
        "required": ["retrieval_method"],
        "optional": ["retrieval_score", "rank_position", "retrieval_query_digest"],
    },
    "rejected": {
        "required": ["rejection_reason"],
        "optional": ["retrieval_method", "retrieval_score", "rank_position"],
    },
}

TYPE_VALIDATORS = {
    "retrieval_method": lambda v: isinstance(v, str) and v,
    "rejection_reason": lambda v: isinstance(v, str) and v,
    "retrieval_score": lambda v: isinstance(v, (int, float)),
    "rank_position": lambda v: isinstance(v, int) and v >= 1,
    "retrieval_query_digest": lambda v: isinstance(v, str) and v,
}

def _validate_event_metadata(event_type: str, metadata: dict[str, Any]) -> None:
    if event_type not in METADATA_CONTRACTS:
        return
    contract = METADATA_CONTRACTS[event_type]
    allowed_keys = set(contract["required"]) | set(contract["optional"])

    # Reject unknown keys
    unknown = set(metadata.keys()) - allowed_keys
    if unknown:
        raise ValueError(f"metadata contains unknown keys: {unknown}")

    # Check required keys
    missing = set(contract["required"]) - set(metadata.keys())
    if missing:
        raise ValueError(f"metadata missing required keys: {missing}")

    # Validate types for present keys
    for key, value in metadata.items():
        if key in TYPE_VALIDATORS:
            if not TYPE_VALIDATORS[key](value):
                raise ValueError(f"metadata key '{key}' failed type validation")
```

Integrate validation into `record_event()`:

```python
def record_event(
    self,
    workflow_id: str,
    step_name: str,
    artifact_id: str | None,
    event_type: str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ContextLedgerEvent:
    event_scope = "artifact" if artifact_id is not None else "system"
    _validate("event_scope", event_scope, EVENT_SCOPES)
    if event_scope == "artifact":
        _validate("event_type", event_type, ARTIFACT_EVENTS)
        # Validate metadata contracts for retrieved/rejected
        if metadata and event_type in ("retrieved", "rejected"):
            _validate_event_metadata(event_type, metadata)
    else:
        _validate("event_type", event_type, SYSTEM_EVENTS)
    # ... rest of existing implementation
```

**Idempotency:** `retrieved` and `rejected` events follow the same idempotency pattern as `selected` and `consumed`. The unique constraint on `(workflow_id, step_name, artifact_id, event_type)` prevents duplicate lifecycle events. A retrieval step that re-runs after crash/resume will not emit duplicate events for the same artifact.

### 4.2 `context/models.py`

Add count properties to `ContextAudit`:

```python
@property
def observed_count(self) -> int:
    return _count_events(self.events, "observed")

@property
def retrieved_count(self) -> int:
    return _count_events(self.events, "retrieved")

@property
def rejected_count(self) -> int:
    return _count_events(self.events, "rejected")
```

**Count semantics:** These properties count **unique artifacts** per event type, deduplicated by `(workflow_id, step_name, artifact_id, event_type)`. This matches the existing v0.1 pattern for `selected_count` and `consumed_count`. The workflow headline shows unique artifact counts; detailed event logging can expose repeated events in a future pass.

### 4.3 `context/audit_view.py`

Add `assembly_summary` field to `ContextAuditView`:

```python
@dataclass(frozen=True)
class ContextAuditView:
    workflow_id: str
    headline: str
    lineage_summary: str
    assembly_summary: str  # NEW
    steps: list[ContextAuditStepView]
    claim_boundary_footer: str
    roadmap_notice: str
```

Build assembly summary in `build_context_audit_view()`:

```python
assembly_summary = (
    f"Assembly: {audit.observed_count} observed, {audit.retrieved_count} retrieved, "
    f"{audit.selected_count} selected, {audit.rejected_count} rejected"
)
```

Update renderer to show two-line header:

```
Context audit: 9 selected, 7 consumed, 3 influential sources, 2 decisions
Assembly: 500 observed, 37 retrieved, 9 selected, 28 rejected
```

**Step-level visibility:** `retrieved` and `rejected` artifacts are **not** shown in step `mounted_context` by default. The existing filter in `audit_view.py` (line 86) includes only `observed`, `selected`, and `consumed` events. `retrieved`/`rejected` artifacts are audit-only for the assembly summary line. Future passes can add detailed retrieval views if needed.

### 4.4 Tests

Add tests in `tests/test_context_ledger.py`:

- Test `retrieved` event with valid metadata
- Test `retrieved` event rejected when missing `retrieval_method`
- Test `retrieved` event rejected when unknown key present
- Test `retrieved` event rejected with invalid `rank_position` (zero or negative)
- Test `rejected` event with valid metadata
- Test `rejected` event rejected when missing `rejection_reason`
- Test `rejected` event rejected when unknown key present
- Test type validation for `retrieval_score` (int/float accepted)
- Test audit counts include retrieved/rejected events
- Test audit counts deduplicate artifacts (same artifact retrieved twice in different steps counts once)
- Test backward compatibility: existing v0.1 workflows without retrieval instrumentation still pass

**Count semantics tests:**
- `test_audit_counts_unique_artifacts`: Verify that `observed_count`, `retrieved_count`, and `rejected_count` deduplicate by `(workflow_id, step_name, artifact_id, event_type)`
- `test_assembly_summary_format`: Verify the assembly summary string format matches expected output

---

## 5. No Schema Changes

The existing `context_ledger_events` table already supports:

- Storing any `event_type` string
- Storing JSON in `metadata` column

No migration, no new tables, no framework behavior.

---

## 6. Deferred to v0.2

The following are explicitly NOT in this implementation pass:

- `superseded` event type (supersession semantics)
- Supersession resolver
- Current-state read model
- Retrieval table normalization

These will enter the codebase only when the full supersession feature is implemented.

---

## 7. Exit Gates

Before claiming assembly lineage is implemented:

- [ ] `retrieved` and `rejected` are valid `event_type` values in `ARTIFACT_EVENTS`
- [ ] Metadata validation enforces required keys
- [ ] Metadata validation rejects unknown keys
- [ ] Metadata validation enforces type constraints (non-empty strings, positive ints, numeric scores)
- [ ] Audit summary exposes observed/retrieved/selected/rejected counts
- [ ] Audit counts deduplicate artifacts (unique per event type)
- [ ] Renderer shows two-line header
- [ ] Tests cover metadata validation contracts (required keys, unknown keys, type constraints)
- [ ] Tests cover count semantics (unique artifacts)
- [ ] Existing v0.1 workflows continue to work without retrieval instrumentation
- [ ] Idempotency preserved: duplicate (workflow_id, step_name, artifact_id, event_type) rejected

---

## 8. Philosophy

Events first. Schema stable. Primitive visible. No platform creep.

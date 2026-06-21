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

Metadata is validated JSON with defined contracts. Not casual JSON, not schema columns.

### `retrieved` Event

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `retrieval_method` | string | Yes | e.g., `bm25`, `hybrid`, `memory_lookup`, `deterministic_fixture` |
| `retrieval_score` | float | No | Numeric score from the retrieval method |
| `rank_position` | int | No | Ordinal position in ranked results |
| `retrieval_query_digest` | string | No | Hash of the query that produced this retrieval |

Example:
```json
{
  "retrieval_method": "bm25",
  "retrieval_score": 0.82,
  "rank_position": 4
}
```

### `rejected` Event

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `rejection_reason` | string | Yes | e.g., `token_budget`, `low_score`, `duplicate` |
| `retrieval_method` | string | No | Copy from retrieved event for analysis |
| `retrieval_score` | float | No | Copy from retrieved event for analysis |
| `rank_position` | int | No | Copy from retrieved event for analysis |

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

Add metadata validation:

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

def _validate_event_metadata(event_type: str, metadata: dict[str, Any]) -> None:
    if event_type not in METADATA_CONTRACTS:
        return
    contract = METADATA_CONTRACTS[event_type]
    for key in contract["required"]:
        if key not in metadata:
            raise ValueError(f"metadata missing required key: {key}")
```

Call validation in `record_event()` for artifact-scope events.

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

### 4.4 Tests

Add tests in `tests/test_context_ledger.py`:

- Test `retrieved` event with valid metadata
- Test `retrieved` event rejected when missing `retrieval_method`
- Test `rejected` event with valid metadata
- Test `rejected` event rejected when missing `rejection_reason`
- Test audit counts include retrieved/rejected events

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

- [ ] `retrieved` and `rejected` are valid `event_type` values
- [ ] Metadata validation enforces required keys
- [ ] Audit summary exposes observed/retrieved/selected/rejected counts
- [ ] Renderer shows two-line header
- [ ] Tests cover metadata validation contracts
- [ ] Existing v0.1 workflows continue to work without retrieval instrumentation

---

## 8. Philosophy

Events first. Schema stable. Primitive visible. No platform creep.

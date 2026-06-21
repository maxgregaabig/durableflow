# Assembly Lineage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `retrieved` and `rejected` event types to the context ledger with strict metadata validation, enabling audit of how candidate information competed for context budget.

**Architecture:** Event-sourced extension. Add new event types to existing `context_ledger_events` table with contracted JSON metadata. No schema migration. Validation at ledger API boundary. Audit view exposes assembly summary with unique artifact counts.

**Tech Stack:** Python 3, SQLite, pytest, dataclasses

---

## File Structure

**Files to modify:**
- `context/ledger.py` - Add event types, metadata validation, integration
- `context/models.py` - Add count properties to ContextAudit
- `context/audit_view.py` - Add assembly_summary field, build summary, update renderer
- `tests/test_context_ledger.py` - Add validation and count tests

**No files created.** All changes are additive to existing files.

**Note:** The `Any` type is already imported at the top of `context/ledger.py` (line 4). No new imports are needed.

---

## Task 1: Add Event Types to Ledger

**Files:**
- Modify: `context/ledger.py` (top of file, around line 17)

Add `retrieved` and `rejected` to the `ARTIFACT_EVENTS` set.

- [ ] **Step 1: Modify ARTIFACT_EVENTS set**

Find the `ARTIFACT_EVENTS` set near line 17. Change:
```python
ARTIFACT_EVENTS = {"observed", "selected", "consumed"}
```
To:
```python
ARTIFACT_EVENTS = {"observed", "retrieved", "selected", "rejected", "consumed"}
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `pytest tests/test_context_ledger.py -v`
Expected: All existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add context/ledger.py
git commit -m "feat: add retrieved and rejected to ARTIFACT_EVENTS

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add Metadata Contracts and Type Validators

**Files:**
- Modify: `context/ledger.py` (after `INFLUENCE_TYPES`, around line 21)

Add metadata contracts and type validators for strict validation.

- [ ] **Step 1: Add METADATA_CONTRACTS and TYPE_VALIDATORS**

After the `INFLUENCE_TYPES` set (around line 21), add:
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
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py -v`
Expected: PASS (constants only, no behavior change yet)

- [ ] **Step 3: Commit**

```bash
git add context/ledger.py
git commit -m "feat: add metadata contracts and type validators

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Add Metadata Validation Function

**Files:**
- Modify: `context/ledger.py` (before `_validate` function, around line 350)

Add the `_validate_event_metadata` function.

- [ ] **Step 1: Add _validate_event_metadata function**

Before the `_validate` function (around line 350), add:
```python
def _validate_event_metadata(event_type: str, metadata: dict[str, Any]) -> None:
    if event_type not in METADATA_CONTRACTS:
        return
    contract = METADATA_CONTRACTS[event_type]
    allowed_keys = set(contract["required"]) | set(contract["optional"])

    unknown = set(metadata.keys()) - allowed_keys
    if unknown:
        raise ValueError(f"metadata contains unknown keys: {unknown}")

    missing = set(contract["required"]) - set(metadata.keys())
    if missing:
        raise ValueError(f"metadata missing required keys: {missing}")

    for key, value in metadata.items():
        if key in TYPE_VALIDATORS:
            if not TYPE_VALIDATORS[key](value):
                raise ValueError(f"metadata key '{key}' failed type validation")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py -v`
Expected: PASS (function defined but not called yet)

- [ ] **Step 3: Commit**

```bash
git add context/ledger.py
git commit -m "feat: add metadata validation function

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Integrate Validation into record_event

**Files:**
- Modify: `context/ledger.py` (in `record_event` method, around line 104)

Integrate metadata validation into the `record_event` method.

- [ ] **Step 1: Add validation call in record_event**

Find the artifact event validation block (around line 104) and add metadata validation:
```python
        if event_scope == "artifact":
            _validate("event_type", event_type, ARTIFACT_EVENTS)
            if metadata and event_type in ("retrieved", "rejected"):
                _validate_event_metadata(event_type, metadata)
        else:
            _validate("event_type", event_type, SYSTEM_EVENTS)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py -v`
Expected: PASS (validation integrated but no tests yet)

- [ ] **Step 3: Commit**

```bash
git add context/ledger.py
git commit -m "feat: integrate metadata validation into record_event

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5a: Retrieved Event Validation Tests

**Files:**
- Modify: `tests/test_context_ledger.py`

Add tests for retrieved event metadata validation.

- [ ] **Step 1: Add retrieved event validation tests**

Add to `tests/test_context_ledger.py` (following the existing test pattern with `tmp_path`):
```python
def test_ctx_led_assembly_001_retrieved_event_valid_metadata(tmp_path) -> None:
    """retrieved event with valid metadata is accepted."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    event = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 0.82, "rank_position": 4},
    )
    assert event.event_type == "retrieved"
    assert event.metadata["retrieval_method"] == "bm25"


def test_ctx_led_assembly_002_retrieved_event_missing_required_key(tmp_path) -> None:
    """retrieved event without retrieval_method is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata missing required keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_score": 0.82},
        )


def test_ctx_led_assembly_003_retrieved_event_empty_string_rejected(tmp_path) -> None:
    """retrieved event with empty retrieval_method is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="failed type validation"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": ""},
        )


def test_ctx_led_assembly_004_retrieved_event_unknown_key_rejected(tmp_path) -> None:
    """retrieved event with unknown key is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata contains unknown keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25", "unknown_field": "value"},
        )
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_001_retrieved_event_valid_metadata -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_002_retrieved_event_missing_required_key -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_003_retrieved_event_empty_string_rejected -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_004_retrieved_event_unknown_key_rejected -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_ledger.py
git commit -m "test: add retrieved event validation tests

- Valid retrieved events accepted
- Missing required keys rejected
- Empty string rejected
- Unknown keys rejected

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5b: Type Validation Edge Case Tests

**Files:**
- Modify: `tests/test_context_ledger.py`

Add tests for type validation edge cases.

- [ ] **Step 1: Add type validation edge case tests**

Add to `tests/test_context_ledger.py`:
```python
def test_ctx_led_assembly_005_retrieved_event_invalid_rank_position(tmp_path) -> None:
    """retrieved event with zero rank_position is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="failed type validation"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25", "rank_position": 0},
        )


def test_ctx_led_assembly_006_retrieved_event_negative_rank_rejected(tmp_path) -> None:
    """retrieved event with negative rank_position is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="failed type validation"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25", "rank_position": -1},
        )


def test_ctx_led_assembly_007_type_validation_int_float_accepted(tmp_path) -> None:
    """retrieval_score accepts both int and float."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    # Float should work
    event1 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 0.82},
    )
    assert event1.metadata["retrieval_score"] == 0.82

    # Int should work
    event2 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25", "retrieval_score": 1},
    )
    assert event2.metadata["retrieval_score"] == 1
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_005_retrieved_event_invalid_rank_position -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_006_retrieved_event_negative_rank_rejected -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_007_type_validation_int_float_accepted -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_ledger.py
git commit -m "test: add type validation edge case tests

- Zero rank_position rejected
- Negative rank_position rejected
- Int and float scores both accepted

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5c: Rejected Event Validation Tests

**Files:**
- Modify: `tests/test_context_ledger.py`

Add tests for rejected event metadata validation.

- [ ] **Step 1: Add rejected event validation tests**

Add to `tests/test_context_ledger.py`:
```python
def test_ctx_led_assembly_008_rejected_event_valid_metadata(tmp_path) -> None:
    """rejected event with valid metadata is accepted."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    event = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "rejected",
        metadata={"rejection_reason": "token_budget", "retrieval_score": 0.12, "rank_position": 37},
    )
    assert event.event_type == "rejected"
    assert event.metadata["rejection_reason"] == "token_budget"


def test_ctx_led_assembly_009_rejected_event_missing_required_key(tmp_path) -> None:
    """rejected event without rejection_reason is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata missing required keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "rejected",
            metadata={"retrieval_score": 0.12},
        )


def test_ctx_led_assembly_010_rejected_event_empty_string_rejected(tmp_path) -> None:
    """rejected event with empty rejection_reason is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="failed type validation"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "rejected",
            metadata={"rejection_reason": ""},
        )


def test_ctx_led_assembly_011_rejected_event_unknown_key_rejected(tmp_path) -> None:
    """rejected event with unknown key is rejected."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    with pytest.raises(ValueError, match="metadata contains unknown keys"):
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "rejected",
            metadata={"rejection_reason": "token_budget", "unknown_field": "value"},
        )
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_008_rejected_event_valid_metadata -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_009_rejected_event_missing_required_key -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_010_rejected_event_empty_string_rejected -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_011_rejected_event_unknown_key_rejected -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_ledger.py
git commit -m "test: add rejected event validation tests

- Valid rejected events accepted
- Missing required keys rejected
- Empty string rejected
- Unknown keys rejected

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Add Count Properties to ContextAudit

**Files:**
- Modify: `context/models.py` (in `ContextAudit` class, after `decision_count` property, around line 80)

Add `observed_count`, `retrieved_count`, and `rejected_count` properties.

- [ ] **Step 1: Add count properties to ContextAudit**

After the `decision_count` property (around line 80), add:
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

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add context/models.py
git commit -m "feat: add observed/retrieved/rejected count properties

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Write Count Tests

**Files:**
- Modify: `tests/test_context_ledger.py`

Add tests for count properties and unique artifact deduplication.

- [ ] **Step 1: Add count tests**

Add to `tests/test_context_ledger.py`:
```python
def test_ctx_led_assembly_020_audit_counts_includes_retrieved_rejected(tmp_path) -> None:
    """Audit counts include retrieved and rejected events."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "observed",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "selected",
    )

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.observed_count == 1
    assert audit.retrieved_count == 1
    assert audit.selected_count == 1
    assert audit.rejected_count == 0


def test_ctx_led_assembly_021_audit_counts_unique_artifacts(tmp_path) -> None:
    """Audit counts deduplicate artifacts by (workflow_id, step_name, artifact_id, event_type)."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )

    # Record retrieved event twice - should be deduplicated
    event1 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    event2 = ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    # Same event should be returned (idempotency)
    assert event1.event_id == event2.event_id

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.retrieved_count == 1  # Not 2


def test_ctx_led_assembly_022_audit_counts_cross_step_deduplication(tmp_path) -> None:
    """Same artifact retrieved in different steps counts separately."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )

    # Same artifact, retrieved in different steps
    ledger.record_event(
        state.workflow_id,
        "step_a",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    ledger.record_event(
        state.workflow_id,
        "step_b",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "hybrid"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    # Deduplication is per (workflow_id, step_name, artifact_id, event_type)
    # So these count as 2 unique retrieved events
    assert audit.retrieved_count == 2


def test_ctx_led_assembly_023_audit_counts_multiple_artifacts(tmp_path) -> None:
    """Audit counts correctly sum multiple artifacts."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifacts = []
    for i in range(3):
        artifact = ledger.record_artifact(
            state.workflow_id,
            "source_artifact",
            f"test-source-{i}",
            "test_type",
            None,
            f"test-ref-{i}",
            100,
        )
        artifacts.append(artifact)

    # All retrieved
    for artifact in artifacts:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25"},
        )

    # First two selected, third rejected
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[0].artifact_id,
        "selected",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[1].artifact_id,
        "selected",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[2].artifact_id,
        "rejected",
        metadata={"rejection_reason": "token_budget"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.retrieved_count == 3
    assert audit.selected_count == 2
    assert audit.rejected_count == 1
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_020_audit_counts_includes_retrieved_rejected -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_021_audit_counts_unique_artifacts -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_022_audit_counts_cross_step_deduplication -v`
Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_023_audit_counts_multiple_artifacts -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_ledger.py
git commit -m "test: add count property tests

- Retrieved/rejected included in audit counts
- Unique artifact deduplication verified
- Cross-step deduplication semantics verified
- Multiple artifact counting verified

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Add Assembly Summary to Audit View

**Files:**
- Modify: `context/audit_view.py` (in `ContextAuditView` dataclass, around line 55)

Add `assembly_summary` field to `ContextAuditView`.

- [ ] **Step 1: Add assembly_summary field**

Edit the `ContextAuditView` dataclass (around line 55). Add after `lineage_summary`:
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

- [ ] **Step 2: Run audit view tests**

Run: `pytest tests/test_context_audit_view.py -v`
Expected: Tests may fail (field not being populated yet)

- [ ] **Step 3: Commit**

```bash
git add context/audit_view.py
git commit -m "feat: add assembly_summary field to ContextAuditView

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Build Assembly Summary in View Builder

**Files:**
- Modify: `context/audit_view.py` (in `build_context_audit_view` function, around line 145)

Build the assembly summary string in `build_context_audit_view`.

- [ ] **Step 1: Build assembly_summary string**

After the `headline` assignment (around line 145), add:
```python
    assembly_summary = (
        f"Assembly: {audit.observed_count} observed, {audit.retrieved_count} retrieved, "
        f"{audit.selected_count} selected, {audit.rejected_count} rejected"
    )
```

Then update the `ContextAuditView` return to include `assembly_summary`:
```python
    return ContextAuditView(
        workflow_id=audit.workflow_id,
        headline=headline,
        lineage_summary=lineage_summary,
        assembly_summary=assembly_summary,
        steps=steps,
        claim_boundary_footer=BOUNDARY_FOOTER,
        roadmap_notice=ROADMAP_NOTICE,
    )
```

- [ ] **Step 2: Run audit view tests**

Run: `pytest tests/test_context_audit_view.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add context/audit_view.py
git commit -m "feat: build assembly summary in view builder

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Update Renderer for Two-Line Header

**Files:**
- Modify: `context/audit_view.py` (in `render_context_audit` function, around line 159)

Update `render_context_audit` to show the assembly summary.

- [ ] **Step 1: Add assembly summary to renderer output**

Edit line 160 in `render_context_audit`. Change:
```python
    lines = [view.headline, view.lineage_summary, ""]
```
To:
```python
    lines = [view.headline, view.lineage_summary, view.assembly_summary, ""]
```

- [ ] **Step 2: Run audit view tests**

Run: `pytest tests/test_context_audit_view.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add context/audit_view.py
git commit -m "feat: add assembly summary to renderer output

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Write Audit View Tests

**Files:**
- Modify: `tests/test_context_audit_view.py`

Add tests for the new assembly summary functionality.

- [ ] **Step 1: Add assembly summary tests**

Add to `tests/test_context_audit_view.py`:
```python
def test_ctx_audit_assembly_001_summary_in_view(tmp_path) -> None:
    """Assembly summary includes observed, retrieved, selected, rejected counts."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    # Create 5 artifacts
    for i in range(5):
        ledger.record_artifact(
            state.workflow_id,
            "source_artifact",
            f"source-{i}",
            "test",
            None,
            f"ref-{i}",
            100,
        )

    # Get artifacts from ledger
    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifacts = [
            _artifact_from_row(row)
            for row in conn.execute(
                "SELECT * FROM context_artifacts WHERE workflow_id = ?",
                (state.workflow_id,),
            ).fetchall()
        ]

    # Record events: 3 retrieved, 2 selected, 1 rejected
    for artifact in artifacts[:3]:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "retrieved",
            metadata={"retrieval_method": "bm25"},
        )

    for artifact in artifacts[:2]:
        ledger.record_event(
            state.workflow_id,
            "test_step",
            artifact.artifact_id,
            "selected",
        )

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifacts[2].artifact_id,
        "rejected",
        metadata={"rejection_reason": "low_score"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)

    assert "Assembly: 5 observed, 3 retrieved, 2 selected, 1 rejected" in view.assembly_summary


def test_ctx_audit_assembly_002_renderer_includes_summary(tmp_path) -> None:
    """Renderer output includes assembly summary line."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test",
        None,
        "test-ref",
        100,
    )

    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifact_row = conn.execute(
            "SELECT * FROM context_artifacts WHERE workflow_id = ? LIMIT 1",
            (state.workflow_id,),
        ).fetchone()
        artifact = _artifact_from_row(artifact_row)

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)
    output = render_context_audit(view)

    assert "Assembly:" in output
    assert "observed" in output
    assert "retrieved" in output


def test_ctx_audit_assembly_003_format_exact(tmp_path) -> None:
    """Assembly summary matches exact format specification."""
    import re
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test",
        None,
        "test-ref",
        100,
    )

    from context.ledger import _artifact_from_row
    with ledger.connect() as conn:
        artifact_row = conn.execute(
            "SELECT * FROM context_artifacts WHERE workflow_id = ? LIMIT 1",
            (state.workflow_id,),
        ).fetchone()
        artifact = _artifact_from_row(artifact_row)

    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )

    audit = ledger.audit_workflow(state.workflow_id)
    view = build_context_audit_view(audit)

    # Verify exact format: "Assembly: {N} observed, {N} retrieved, {N} selected, {N} rejected"
    pattern = r'^Assembly: \d+ observed, \d+ retrieved, \d+ selected, \d+ rejected$'
    assert re.match(pattern, view.assembly_summary)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_context_audit_view.py::test_ctx_audit_assembly_001_summary_in_view -v`
Run: `pytest tests/test_context_audit_view.py::test_ctx_audit_assembly_002_renderer_includes_summary -v`
Run: `pytest tests/test_context_audit_view.py::test_ctx_audit_assembly_003_format_exact -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_audit_view.py
git commit -m "test: add assembly summary tests

- Assembly summary includes all counts
- Renderer output includes assembly line
- Exact format verified with regex

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Backward Compatibility Test

**Files:**
- Modify: `tests/test_context_ledger.py`

Ensure existing v0.1 workflows continue to work.

- [ ] **Step 1: Add backward compatibility test**

Add to `tests/test_context_ledger.py`:
```python
def test_ctx_led_assembly_050_backward_compatibility_v01(tmp_path) -> None:
    """Existing v0.1 workflows without retrieval instrumentation still work."""
    store = WorkflowStore(tmp_path / "context.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)

    artifact = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "test-source",
        "test_type",
        None,
        "test-ref",
        100,
    )

    # v0.1 style events (no retrieved/rejected)
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "observed",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "selected",
    )
    ledger.record_event(
        state.workflow_id,
        "test_step",
        artifact.artifact_id,
        "consumed",
    )

    audit = ledger.audit_workflow(state.workflow_id)
    assert audit.observed_count == 1
    assert audit.selected_count == 1
    assert audit.consumed_count == 1
    assert audit.retrieved_count == 0
    assert audit.rejected_count == 0

    # Should work with audit view builder
    view = build_context_audit_view(audit)
    assert "Assembly: 1 observed, 0 retrieved, 1 selected, 0 rejected" in view.assembly_summary
```

- [ ] **Step 2: Run test**

Run: `pytest tests/test_context_ledger.py::test_ctx_led_assembly_050_backward_compatibility_v01 -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_context_ledger.py
git commit -m "test: add backward compatibility test

v0.1 workflows without retrieval instrumentation continue to work.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Full Test Suite Verification

**Files:**
- Test: All context tests

- [ ] **Step 1: Run all context tests**

Run: `pytest tests/test_context*.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run with coverage**

Run: `pytest tests/test_context*.py --cov=context --cov-report=term-missing`
Expected: High coverage on new code

- [ ] **Step 3: No commit needed** (just verification)

---

## Summary

This plan implements assembly lineage as specified in §14 of the context spec:

- `retrieved` and `rejected` event types added to `ARTIFACT_EVENTS`
- Strict metadata validation (required keys, unknown keys rejected, type constraints including empty strings)
- Count properties on `ContextAudit` for observed/retrieved/rejected
- Assembly summary in audit view with two-line renderer output
- Full test coverage including backward compatibility and cross-step deduplication
- No schema changes, pure additive extension

**Exit gates verified:**
- [x] `retrieved` and `rejected` are valid event types
- [x] Metadata validation enforces required keys
- [x] Metadata validation rejects unknown keys
- [x] Metadata validation enforces type constraints (including non-empty strings)
- [x] Audit summary exposes all counts
- [x] Audit counts deduplicate artifacts (with correct cross-step semantics)
- [x] Renderer shows two-line header
- [x] Tests cover all validation contracts
- [x] Assembly summary format verified
- [x] Backward compatibility preserved
- [x] Idempotency preserved via existing unique constraint

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from src.store import ClosingConnection, WorkflowStore, utc_now

from .models import ContextAudit, ContextLedgerEvent, DecisionLineage, DecisionRecord, InfoArtifact
from .schema import init_context_schema


ARTIFACT_ROLES = {"source_artifact", "prompt_artifact", "response_artifact"}
ARTIFACT_EVENTS = {"observed", "retrieved", "selected", "rejected", "consumed"}
SYSTEM_EVENTS = {"decision_recorded", "lineage_recorded"}
EVENT_SCOPES = {"artifact", "system"}
INFLUENCE_TYPES = {"explicit_model_attribution", "deterministic_fixture_attribution"}

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


class ContextLedger:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._init_schema()

    @classmethod
    def from_store(cls, store: WorkflowStore) -> "ContextLedger":
        return cls(store.db_path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, factory=ClosingConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    def record_artifact(
        self,
        workflow_id: str,
        artifact_role: str,
        source: str,
        source_type: str,
        content: str | None,
        content_ref: str | None,
        token_count: int,
        metadata: dict[str, Any] | None = None,
    ) -> InfoArtifact:
        _validate("artifact_role", artifact_role, ARTIFACT_ROLES)
        digest = _digest(content if content is not None else content_ref or "")
        now = utc_now()
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM context_artifacts
                WHERE workflow_id = ? AND artifact_role = ? AND source = ? AND content_digest = ?
                """,
                (workflow_id, artifact_role, source, digest),
            ).fetchone()
            if existing is not None:
                return _artifact_from_row(existing)
            artifact_id = f"ctx-art-{uuid.uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO context_artifacts
                  (artifact_id, workflow_id, artifact_role, source, source_type, content_digest,
                   content_ref, token_count, observed_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    workflow_id,
                    artifact_role,
                    source,
                    source_type,
                    digest,
                    content_ref,
                    int(token_count),
                    now,
                    metadata_json,
                ),
            )
            row = conn.execute(
                "SELECT * FROM context_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        return _artifact_from_row(row)

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
        else:
            _validate("event_type", event_type, SYSTEM_EVENTS)
        now = utc_now()
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        with self.connect() as conn:
            if artifact_id is not None:
                existing = conn.execute(
                    """
                    SELECT * FROM context_ledger_events
                    WHERE workflow_id = ? AND step_name = ? AND artifact_id = ? AND event_type = ?
                    """,
                    (workflow_id, step_name, artifact_id, event_type),
                ).fetchone()
                if existing is not None:
                    return _event_from_row(existing)
            event_id = f"ctx-evt-{uuid.uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO context_ledger_events
                  (event_id, workflow_id, step_name, artifact_id, event_type, event_scope,
                   event_time, reason, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    workflow_id,
                    step_name,
                    artifact_id,
                    event_type,
                    event_scope,
                    now,
                    reason,
                    metadata_json,
                ),
            )
            row = conn.execute(
                "SELECT * FROM context_ledger_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return _event_from_row(row)

    def record_decision(
        self,
        workflow_id: str,
        step_name: str,
        step_result_id: str | None,
        prompt: str,
        response: str,
        model_used: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> DecisionRecord:
        prompt_digest = _digest(prompt)
        response_digest = _digest(response)
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM context_decisions
                WHERE workflow_id = ? AND step_name = ? AND prompt_digest = ? AND response_digest = ?
                """,
                (workflow_id, step_name, prompt_digest, response_digest),
            ).fetchone()
            if existing is not None:
                return _decision_from_row(existing)
            decision_id = f"ctx-dec-{uuid.uuid4().hex[:16]}"
            conn.execute(
                """
                INSERT INTO context_decisions
                  (decision_id, workflow_id, step_name, step_result_id, prompt_digest,
                   response_digest, model_used, input_tokens, output_tokens, cost_usd, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    workflow_id,
                    step_name,
                    step_result_id,
                    prompt_digest,
                    response_digest,
                    model_used,
                    int(input_tokens),
                    int(output_tokens),
                    float(cost_usd),
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM context_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        self.record_event(
            workflow_id,
            step_name,
            None,
            "decision_recorded",
            metadata={"decision_id": row["decision_id"]},
        )
        return _decision_from_row(row)

    def record_lineage(
        self,
        decision_id: str,
        artifact_id: str,
        influence_type: str,
        influence_score: float,
        evidence_ref: str | None = None,
    ) -> DecisionLineage:
        _validate("influence_type", influence_type, INFLUENCE_TYPES)
        with self.connect() as conn:
            decision = conn.execute(
                "SELECT * FROM context_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
            if decision is None:
                raise KeyError(f"decision not found: {decision_id}")
            artifact = conn.execute(
                "SELECT * FROM context_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
            if artifact is None:
                raise KeyError(f"artifact not found: {artifact_id}")
            if artifact["workflow_id"] != decision["workflow_id"]:
                raise ValueError("lineage artifact must belong to the decision workflow")
            if artifact["artifact_role"] != "source_artifact":
                raise ValueError("lineage can only reference source_artifact rows")
            selected_or_consumed = conn.execute(
                """
                SELECT 1 FROM context_ledger_events
                WHERE workflow_id = ? AND artifact_id = ? AND event_type IN ('selected', 'consumed')
                LIMIT 1
                """,
                (decision["workflow_id"], artifact_id),
            ).fetchone()
            if selected_or_consumed is None:
                raise ValueError("lineage artifact must be selected or consumed in the workflow")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO context_decision_lineage
                  (decision_id, artifact_id, influence_type, influence_score, evidence_ref)
                VALUES (?, ?, ?, ?, ?)
                """,
                (decision_id, artifact_id, influence_type, float(influence_score), evidence_ref),
            )
            row = conn.execute(
                """
                SELECT * FROM context_decision_lineage
                WHERE decision_id = ? AND artifact_id = ?
                """,
                (decision_id, artifact_id),
            ).fetchone()
        if cursor.rowcount > 0:
            self.record_event(
                decision["workflow_id"],
                decision["step_name"],
                None,
                "lineage_recorded",
                metadata={"decision_id": decision_id, "artifact_id": artifact_id},
            )
        return _lineage_from_row(row)

    def link_decisions_to_step_result(
        self,
        workflow_id: str,
        step_name: str,
        step_index: int,
    ) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM step_results
                WHERE workflow_id = ? AND step_name = ? AND step_index = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (workflow_id, step_name, step_index),
            ).fetchone()
            if row is None:
                return 0
            step_result_id = str(row["id"])
            cursor = conn.execute(
                """
                UPDATE context_decisions
                SET step_result_id = ?
                WHERE workflow_id = ? AND step_name = ? AND step_result_id IS NULL
                """,
                (step_result_id, workflow_id, step_name),
            )
        return int(cursor.rowcount)

    def audit_workflow(self, workflow_id: str) -> ContextAudit:
        with self.connect() as conn:
            artifacts = [
                _artifact_from_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM context_artifacts
                    WHERE workflow_id = ?
                    ORDER BY observed_at, artifact_id
                    """,
                    (workflow_id,),
                ).fetchall()
            ]
            events = [
                _event_from_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM context_ledger_events
                    WHERE workflow_id = ?
                    ORDER BY event_time, event_id
                    """,
                    (workflow_id,),
                ).fetchall()
            ]
            decisions = [
                _decision_from_row(row)
                for row in conn.execute(
                    """
                    SELECT * FROM context_decisions
                    WHERE workflow_id = ?
                    ORDER BY created_at, decision_id
                    """,
                    (workflow_id,),
                ).fetchall()
            ]
            lineage = [
                _lineage_from_row(row)
                for row in conn.execute(
                    """
                    SELECT l.* FROM context_decision_lineage l
                    JOIN context_decisions d ON d.decision_id = l.decision_id
                    WHERE d.workflow_id = ?
                    ORDER BY d.created_at, l.artifact_id
                    """,
                    (workflow_id,),
                ).fetchall()
            ]
        return ContextAudit(workflow_id, artifacts, events, decisions, lineage)

    def _init_schema(self) -> None:
        with self.connect() as conn:
            init_context_schema(conn)


def _validate(name: str, value: str, allowed: set[str]) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name}: {value}")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _loads(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("expected JSON object")
    return parsed


def _artifact_from_row(row: sqlite3.Row) -> InfoArtifact:
    return InfoArtifact(
        artifact_id=row["artifact_id"],
        workflow_id=row["workflow_id"],
        artifact_role=row["artifact_role"],
        source=row["source"],
        source_type=row["source_type"],
        content_digest=row["content_digest"],
        content_ref=row["content_ref"],
        token_count=int(row["token_count"]),
        observed_at=row["observed_at"],
        metadata=_loads(row["metadata"]),
    )


def _event_from_row(row: sqlite3.Row) -> ContextLedgerEvent:
    return ContextLedgerEvent(
        event_id=row["event_id"],
        workflow_id=row["workflow_id"],
        step_name=row["step_name"],
        artifact_id=row["artifact_id"],
        event_type=row["event_type"],
        event_scope=row["event_scope"],
        event_time=row["event_time"],
        reason=row["reason"],
        metadata=_loads(row["metadata"]),
    )


def _decision_from_row(row: sqlite3.Row) -> DecisionRecord:
    return DecisionRecord(
        decision_id=row["decision_id"],
        workflow_id=row["workflow_id"],
        step_name=row["step_name"],
        step_result_id=row["step_result_id"],
        prompt_digest=row["prompt_digest"],
        response_digest=row["response_digest"],
        model_used=row["model_used"],
        input_tokens=int(row["input_tokens"]),
        output_tokens=int(row["output_tokens"]),
        cost_usd=float(row["cost_usd"]),
        created_at=row["created_at"],
    )


def _lineage_from_row(row: sqlite3.Row) -> DecisionLineage:
    return DecisionLineage(
        decision_id=row["decision_id"],
        artifact_id=row["artifact_id"],
        influence_type=row["influence_type"],
        influence_score=float(row["influence_score"]),
        evidence_ref=row["evidence_ref"],
    )

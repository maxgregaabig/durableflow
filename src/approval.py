from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from .store import WorkflowStore, utc_now


@dataclass(frozen=True)
class ApprovalRequest:
    gate_id: str
    workflow_id: str
    step_name: str
    payload: dict[str, Any]
    requested_at: str
    status: str
    decided_at: str | None
    decided_by: str | None
    rejection_reason: str | None


class ApprovalGate:
    def __init__(self, store: WorkflowStore):
        self.store = store

    def request_approval(
        self,
        workflow_id: str,
        step_name: str,
        payload: dict[str, Any],
    ) -> str:
        existing = self.get_for_workflow(workflow_id, step_name)
        if existing:
            return existing.gate_id
        gate_id = f"gate-{uuid.uuid4().hex[:12]}"
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_queue
                  (gate_id, workflow_id, step_name, payload, status, requested_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (
                    gate_id,
                    workflow_id,
                    step_name,
                    json.dumps(payload, sort_keys=True),
                    utc_now(),
                ),
            )
        return gate_id

    def check_approval(self, gate_id: str) -> ApprovalRequest | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE gate_id = ?",
                (gate_id,),
            ).fetchone()
        return self._row_to_request(row) if row else None

    def get_for_workflow(self, workflow_id: str, step_name: str) -> ApprovalRequest | None:
        with self.store.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM approval_queue
                WHERE workflow_id = ? AND step_name = ?
                ORDER BY requested_at DESC
                LIMIT 1
                """,
                (workflow_id, step_name),
            ).fetchone()
        return self._row_to_request(row) if row else None

    def approve(self, gate_id: str, decided_by: str = "operator") -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE approval_queue
                SET status = 'approved', decided_at = ?, decided_by = ?
                WHERE gate_id = ?
                """,
                (utc_now(), decided_by, gate_id),
            )

    def reject(
        self,
        gate_id: str,
        rejection_reason: str,
        decided_by: str = "operator",
    ) -> None:
        with self.store.connect() as conn:
            conn.execute(
                """
                UPDATE approval_queue
                SET status = 'rejected', decided_at = ?, decided_by = ?, rejection_reason = ?
                WHERE gate_id = ?
                """,
                (utc_now(), decided_by, rejection_reason, gate_id),
            )

    def list_pending(self) -> list[ApprovalRequest]:
        with self.store.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approval_queue WHERE status = 'pending' ORDER BY requested_at ASC"
            ).fetchall()
        return [self._row_to_request(row) for row in rows]

    def _row_to_request(self, row: Any) -> ApprovalRequest:
        return ApprovalRequest(
            gate_id=row["gate_id"],
            workflow_id=row["workflow_id"],
            step_name=row["step_name"],
            payload=json.loads(row["payload"]),
            requested_at=row["requested_at"],
            status=row["status"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
            rejection_reason=row["rejection_reason"],
        )


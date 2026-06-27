"""Durable store for the phase runner micro state.

``WorkflowStore.save_checkpoint`` runs only after a macro step returns
its ``StepResult``. ``phase_runner`` runs many laps inside one macro
step, so it cannot rely on its own ``StepResult.output`` for mid-lap
crash recovery: if the process dies between laps, no checkpoint has been
written and the engine would re-enter ``phase_runner`` from scratch.

The fix is this dedicated ``clear_phase_state`` table, written
*directly* between laps (the same pattern ``send_reply`` uses to write
``side_effect_log`` directly from inside a step). ``phase_runner`` reads
prior progress on entry and skips laps already completed, so a resume
continues on the correct phase and attempt without duplicating writes
(spec §6.2, §6.4; CLEAR-INT-003).

Python standard library only.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.store import WorkflowStore

from .phase_state import ClearPhaseState


class ClearPhaseStore:
    """Owns the ``clear_phase_state`` table inside the workflow database.

    The table is additive (spec §6.2 sanctions this) and never touches
    ``WorkflowEngine`` semantics. ``save`` upserts one row per workflow;
    ``load`` returns the latest checkpoint or ``None``.
    """

    def __init__(self, store: "WorkflowStore"):
        self.store = store
        self._init_schema()

    def _init_schema(self) -> None:
        with self.store.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS clear_phase_state (
                    workflow_id TEXT PRIMARY KEY,
                    state       TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );
                """
            )

    def save(self, workflow_id: str, state: ClearPhaseState) -> None:
        from src.store import utc_now

        payload = json.dumps(state.to_dict(), sort_keys=True)
        with self.store.connect() as conn:
            conn.execute(
                """
                INSERT INTO clear_phase_state (workflow_id, state, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at
                """,
                (workflow_id, payload, utc_now()),
            )

    def load(self, workflow_id: str) -> ClearPhaseState | None:
        with self.store.connect() as conn:
            row = conn.execute(
                "SELECT state FROM clear_phase_state WHERE workflow_id = ?",
                (workflow_id,),
            ).fetchone()
        if row is None:
            return None
        data: dict[str, Any] = json.loads(row["state"])
        return ClearPhaseState.from_dict(data)

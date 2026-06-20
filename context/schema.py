from __future__ import annotations

import sqlite3


def init_context_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS context_artifacts (
            artifact_id     TEXT PRIMARY KEY,
            workflow_id     TEXT NOT NULL,
            artifact_role   TEXT NOT NULL,
            source          TEXT NOT NULL,
            source_type     TEXT NOT NULL,
            content_digest  TEXT NOT NULL,
            content_ref     TEXT,
            token_count     INTEGER NOT NULL,
            observed_at     TEXT NOT NULL,
            metadata        TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id),
            UNIQUE (workflow_id, artifact_role, source, content_digest)
        );

        CREATE TABLE IF NOT EXISTS context_ledger_events (
            event_id        TEXT PRIMARY KEY,
            workflow_id     TEXT NOT NULL,
            step_name       TEXT NOT NULL,
            artifact_id     TEXT,
            event_type      TEXT NOT NULL,
            event_scope     TEXT NOT NULL,
            event_time      TEXT NOT NULL,
            reason          TEXT,
            metadata        TEXT NOT NULL DEFAULT '{}',
            FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id),
            FOREIGN KEY (artifact_id) REFERENCES context_artifacts(artifact_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_context_event_lifecycle_once
        ON context_ledger_events(workflow_id, step_name, artifact_id, event_type)
        WHERE event_scope = 'artifact';

        CREATE TABLE IF NOT EXISTS context_decisions (
            decision_id     TEXT PRIMARY KEY,
            workflow_id     TEXT NOT NULL,
            step_name       TEXT NOT NULL,
            step_result_id  TEXT,
            prompt_digest   TEXT NOT NULL,
            response_digest TEXT NOT NULL,
            model_used      TEXT NOT NULL,
            input_tokens    INTEGER NOT NULL,
            output_tokens   INTEGER NOT NULL,
            cost_usd        REAL NOT NULL,
            created_at      TEXT NOT NULL,
            FOREIGN KEY (workflow_id) REFERENCES workflows(workflow_id),
            UNIQUE (workflow_id, step_name, prompt_digest, response_digest)
        );

        CREATE TABLE IF NOT EXISTS context_decision_lineage (
            decision_id     TEXT NOT NULL,
            artifact_id     TEXT NOT NULL,
            influence_type  TEXT NOT NULL,
            influence_score REAL NOT NULL,
            evidence_ref    TEXT,
            PRIMARY KEY (decision_id, artifact_id),
            FOREIGN KEY (decision_id) REFERENCES context_decisions(decision_id),
            FOREIGN KEY (artifact_id) REFERENCES context_artifacts(artifact_id)
        );

        CREATE INDEX IF NOT EXISTS idx_context_artifacts_workflow
        ON context_artifacts(workflow_id);

        CREATE INDEX IF NOT EXISTS idx_context_events_workflow
        ON context_ledger_events(workflow_id, event_time);

        CREATE INDEX IF NOT EXISTS idx_context_decisions_workflow
        ON context_decisions(workflow_id, created_at);
        """
    )

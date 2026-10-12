from __future__ import annotations

import argparse
import json
import os
import sys

from .audit_view import build_context_audit_view, render_context_audit
from .ledger import ContextLedger


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m context.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="render a workflow context audit trace")
    audit.add_argument("--db", required=True, help="SQLite database path")
    audit.add_argument("--workflow-id", required=True, help="workflow id to inspect")

    dataset = subparsers.add_parser(
        "export-langsmith-dataset",
        help="emit LangSmith-eval dataset rows (redacted) from a workflow context audit",
    )
    dataset.add_argument("--db", required=True, help="SQLite database path")
    dataset.add_argument("--workflow-id", required=True, help="workflow id to export")
    dataset.add_argument("--dataset", required=True, help="target LangSmith dataset name")
    dataset.add_argument(
        "--out",
        default="-",
        help="output path for JSON rows ('-' for stdout, the default)",
    )
    dataset.add_argument(
        "--seed",
        type=int,
        default=None,
        help="fixture seed to record in row metadata",
    )

    args = parser.parse_args()

    if args.command == "audit":
        ledger = ContextLedger(args.db)
        view = build_context_audit_view(ledger.audit_workflow(args.workflow_id))
        print(render_context_audit(view))
        return

    if args.command == "export-langsmith-dataset":
        _run_export_dataset(args)


def _run_export_dataset(args: argparse.Namespace) -> None:
    # Lazy import: the dataset builder lives behind the optional integration
    # surface. Importing it here (not at module load) keeps the CLI usable with
    # no LangSmith SDK installed.
    from integrations.langsmith_adapter import build_dataset_rows

    ledger = ContextLedger(args.db)
    audit = ledger.audit_workflow(args.workflow_id)
    rows = build_dataset_rows(audit, seed=args.seed)

    payload = {
        "dataset": args.dataset,
        "workflow_id": args.workflow_id,
        "row_count": len(rows),
        "rows": rows,
    }

    if os.environ.get("DURABLEFLOW_LANGSMITH_INTEGRATION", "").lower() in {"1", "true", "yes"}:
        # Live upload is gated; the default path only emits deterministic rows.
        _upload_to_langsmith(args.dataset, rows)

    out = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if args.out == "-":
        print(out)
    else:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(out + "\n")
        print(f"wrote {len(rows)} rows to {args.out}", file=sys.stderr)


def _upload_to_langsmith(dataset_name: str, rows: list[dict]) -> None:
    """Gated live upload; only reached when DURABLEFLOW_LANGSMITH_INTEGRATION is set.

    Best-effort: failures print a warning and do not abort row emission.
    Real-API conformance is DEFERRED-VERIFICATION (C-LSMITH-DEFER-001).
    """
    try:
        from integrations.langsmith_adapter import LangSmithConfig, langsmith_enabled_from_env

        if not langsmith_enabled_from_env():
            print("[langsmith-dataset] enabled but LANGSMITH_API_KEY missing; skipping upload", file=sys.stderr)
            return
        config = LangSmithConfig.from_env()
        try:
            from langsmith import Client  # type: ignore[import-not-found]
        except ImportError:
            print("[langsmith-dataset] langsmith SDK not installed; skipping upload", file=sys.stderr)
            return
        client = Client(api_key=os.environ["LANGSMITH_API_KEY"])
        for row in rows:
            client.create_example(
                inputs=row["inputs"],
                outputs=row["outputs"],
                metadata=row.get("metadata", {}),
                dataset_name=dataset_name,
            )
        print(f"[langsmith-dataset] uploaded {len(rows)} examples to {dataset_name}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - best-effort upload
        print(f"[langsmith-dataset] upload failed (rows still emitted): {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()

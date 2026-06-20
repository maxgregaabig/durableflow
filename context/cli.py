from __future__ import annotations

import argparse

from .audit_view import build_context_audit_view, render_context_audit
from .ledger import ContextLedger


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m context.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit", help="render a workflow context audit trace")
    audit.add_argument("--db", required=True, help="SQLite database path")
    audit.add_argument("--workflow-id", required=True, help="workflow id to inspect")
    args = parser.parse_args()

    if args.command == "audit":
        ledger = ContextLedger(args.db)
        view = build_context_audit_view(ledger.audit_workflow(args.workflow_id))
        print(render_context_audit(view))


if __name__ == "__main__":
    main()

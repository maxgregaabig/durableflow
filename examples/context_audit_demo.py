from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from context import ContextLedger, build_context_audit_view, render_context_audit


def main() -> None:
    db_path = ROOT / "examples" / "inbox_triage_context_demo.sqlite"
    if not db_path.exists():
        subprocess.run(
            [sys.executable, str(ROOT / "examples" / "inbox_triage_context_demo.py")],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    ledger = ContextLedger(db_path)
    audit = ledger.audit_workflow("wf-context-demo")
    print(render_context_audit(build_context_audit_view(audit)))


if __name__ == "__main__":
    main()

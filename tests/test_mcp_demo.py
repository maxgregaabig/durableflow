from __future__ import annotations

import subprocess
import sys


def test_mcp_demo_runs_end_to_end() -> None:
    result = subprocess.run(
        [sys.executable, "examples/mcp_demo.py"],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )

    assert "approval_requests=1" in result.stdout
    assert "side_effects=1" in result.stdout

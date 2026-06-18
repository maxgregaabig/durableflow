"""MCP demo: Gated writes over a legacy CRM MCP server.

This demo shows DurableFlow's write gating working across an MCP protocol
boundary. Read tools execute without approval; write tools pause at the gate.

When mcp package is installed, uses the official MCP protocol.
Otherwise, uses a lightweight stdio client that keeps the demo dependency-free.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.mcp_client import get_mcp_tools, StdioMCPToolClient
from agent.mini_react import MiniReActAgent
from agent.runner import AgentRunner


def main() -> None:
    server_path = ROOT / "mcp_server" / "legacy_crm.py"

    # Get tools - will use official MCP if available, fallback otherwise
    tools = get_mcp_tools(server_path)

    # Create and run the agent
    runner = AgentRunner(
        MiniReActAgent(),
        tools,
        db_path=Path(tempfile.mkdtemp(prefix="readiness-mcp-")) / "mcp.sqlite",
    )
    result = runner.run({"ticket_id": "T-100", "customer_id": "cust-1"})
    print(
        "mcp gated write:",
        f"status={result.status}",
        f"approval_requests={result.approval_requests}",
        f"side_effects={result.side_effect_count}",
    )


if __name__ == "__main__":
    main()

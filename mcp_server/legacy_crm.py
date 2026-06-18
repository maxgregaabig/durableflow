"""MCP server exposing a mock legacy CRM system.

Supports two modes:
1. FastMCP protocol when mcp package is installed
2. Simple stdio JSON-RPC for fallback compatibility

Run with: python -m mcp_server.legacy_crm
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools import MockCRM

# Seed the mock CRM with test data
crm = MockCRM.seeded()


def main() -> None:
    # Check if we should run in FastMCP mode or fallback mode
    use_fastmcp = "--fastmcp" in sys.argv

    if use_fastmcp:
        _run_fastmcp()
    else:
        _run_fallback()


def _run_fastmcp() -> None:
    """Run the server using FastMCP (official MCP protocol)."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        print("MCP package not installed. Install with: pip install mcp==1.13.1", file=sys.stderr)
        sys.exit(1)

    # Create the MCP server using FastMCP
    mcp = FastMCP("Legacy CRM", json_response=True)

    @mcp.tool()
    def search_customer(customer_id: str) -> dict[str, Any]:
        """Search for a customer profile by ID."""
        return crm.search_customer({"customer_id": customer_id})

    @mcp.tool()
    def get_ticket_history(ticket_id: str) -> dict[str, Any]:
        """Retrieve the full history of a support ticket."""
        return crm.get_ticket_history({"ticket_id": ticket_id})

    @mcp.tool()
    def lookup_kb(query: str) -> dict[str, Any]:
        """Search the knowledge base for troubleshooting information."""
        return crm.lookup_kb({"query": query})

    @mcp.tool()
    def update_ticket(ticket_id: str, status: str, note: str) -> dict[str, Any]:
        """Update a support ticket with new status and notes."""
        return crm.update_ticket({"ticket_id": ticket_id, "status": status, "note": note})

    @mcp.tool()
    def escalate(ticket_id: str, reason: str, to_tier: str = "senior") -> dict[str, Any]:
        """Escalate a ticket to a higher support tier."""
        return crm.escalate({"ticket_id": ticket_id, "reason": reason, "to_tier": to_tier})

    # Run the server
    mcp.run()


def _run_fallback() -> None:
    """Run the server using simple stdio JSON-RPC (fallback mode).

    This mode is used when the mcp package is not installed, allowing
    the demo to work without external dependencies.
    """
    tools = {
        "search_customer": crm.search_customer,
        "get_ticket_history": crm.get_ticket_history,
        "lookup_kb": crm.lookup_kb,
        "update_ticket": crm.update_ticket,
        "escalate": crm.escalate,
    }

    for line in sys.stdin:
        try:
            request = json.loads(line)
            tool = tools.get(str(request.get("tool")))
            if tool is None:
                print(json.dumps({"error": f"Unknown tool: {request.get('tool')}"}, sort_keys=True), flush=True)
                continue
            result = tool(dict(request.get("args", {})))
            print(json.dumps({"result": result}, sort_keys=True), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}, sort_keys=True), flush=True)
        except Exception as exc:
            print(json.dumps({"error": str(exc)}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()

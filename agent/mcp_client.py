"""MCP client for connecting to the legacy CRM server.

Provides two implementations:
1. Official MCP client using mcp package (async)
2. Fallback stdio JSON-RPC client (sync, dependency-free)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from .protocol import ToolSpec

try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore
    stdio_client = None  # type: ignore


def _ensure_mcp_available() -> None:
    """Check that the mcp package is installed."""
    if not MCP_AVAILABLE:
        raise ImportError(
            "MCP package not installed. Install with: pip install 'durableflow[mcp]'"
        )


class MCPToolClient:
    """Client for connecting to an MCP server using the official mcp package.

    This wraps the official MCP package's ClientSession and provides
    a simple interface for tool calls compatible with DurableFlow's
    ToolSpec protocol.
    """

    def __init__(self, server_path: Path) -> None:
        """Initialize the MCP client.

        Args:
            server_path: Path to the MCP server script.
        """
        _ensure_mcp_available()

        self.server_path = server_path
        self._session: ClientSession | None = None
        self._read_stream = None
        self._write_stream = None
        self._client_ctx = None
        self._initialized = False

    async def _initialize(self) -> None:
        """Initialize the MCP session."""
        if self._initialized:
            return

        # Create server parameters for stdio connection
        # Pass --fastmcp flag to tell server to use FastMCP protocol
        server_params = StdioServerParameters(
            command=sys.executable,
            args=[str(self.server_path), "--fastmcp"],
        )

        # Connect using stdio transport
        self._client_ctx = stdio_client(server_params)
        self._read_stream, self._write_stream = await self._client_ctx.__aenter__()

        # Create and initialize session
        self._session = ClientSession(self._read_stream, self._write_stream)
        await self._session.initialize()
        self._initialized = True

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call.
            args: Arguments to pass to the tool.

        Returns:
            The tool's result.
        """
        await self._initialize()
        assert self._session is not None

        result = await self._session.call_tool(tool_name, arguments=args)

        # Parse structured output if available
        if hasattr(result, 'structuredContent') and result.structuredContent:
            return result.structuredContent

        # Fall back to text content
        if result.content and len(result.content) > 0:
            content = result.content[0]
            if hasattr(content, 'text'):
                return content.text

        return str(result)

    async def close(self) -> None:
        """Close the MCP session."""
        if self._session:
            await self._session.close()
            self._session = None
        if self._client_ctx:
            await self._client_ctx.__aexit__(None, None, None)
            self._client_ctx = None
        self._initialized = False


def _run_async(coro) -> Any:
    """Run an async coroutine in a new event loop.

    This allows async MCP tool handlers to be called from sync code.
    Each call gets its own event loop to avoid context issues.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def mcp_tools(server_path: Path) -> list[ToolSpec]:
    """Create ToolSpecs for the MCP CRM tools using the official mcp package.

    Args:
        server_path: Path to the MCP server script.

    Returns:
        List of ToolSpec objects for use with DurableFlow.

    Note:
        Tool handlers are async (return coroutines) when mcp is installed.
        AgentRunner will automatically run them synchronously using _run_async.
    """
    _ensure_mcp_available()

    # Helper to create async wrappers that handle session lifecycle
    def make_async_wrapper(tool_name: str, is_write: bool = False) -> callable:
        async def wrapper(args: dict[str, Any]) -> Any:
            client = MCPToolClient(server_path)
            try:
                result = await client.call_tool(tool_name, args)
                return result
            finally:
                await client.close()
        return wrapper

    return [
        ToolSpec(
            "search_customer",
            "Search customer profile over MCP",
            False,
            2.0,
            make_async_wrapper("search_customer", is_write=False),
        ),
        ToolSpec(
            "get_ticket_history",
            "Read ticket history over MCP",
            False,
            2.0,
            make_async_wrapper("get_ticket_history", is_write=False),
        ),
        ToolSpec(
            "lookup_kb",
            "Read KB over MCP",
            False,
            2.0,
            make_async_wrapper("lookup_kb", is_write=False),
        ),
        ToolSpec(
            "update_ticket",
            "Update ticket over MCP",
            True,
            2.0,
            make_async_wrapper("update_ticket", is_write=True),
        ),
        ToolSpec(
            "escalate",
            "Escalate ticket over MCP",
            True,
            2.0,
            make_async_wrapper("escalate", is_write=True),
        ),
    ]


# Fallback: lightweight stdio client when mcp is not installed
class StdioMCPToolClient:
    """Tiny stdio JSON-RPC-style client for the demo legacy CRM server.

    This fallback is used when the official mcp package is not installed.
    It keeps the repository demo dependency-free while demonstrating
    the architectural pattern of gated writes across a process boundary.

    For production use with the official MCP protocol, install the mcp package:
        pip install 'durableflow[mcp]'
    """

    def __init__(self, server_path: Path) -> None:
        import subprocess
        import time
        self.server_path = server_path
        self.process = subprocess.Popen(
            [sys.executable, str(server_path)],  # No --fastmcp flag for fallback
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Give the server time to start
        time.sleep(0.1)

    def call(self, tool_name: str, args: dict[str, Any]) -> Any:
        import json
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("MCP server process is not connected")
        self.process.stdin.write(json.dumps({"tool": tool_name, "args": args}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        payload = json.loads(line)
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload["result"]

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except BrokenPipeError:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=2)


def mcp_tools_fallback(server_path: Path) -> list[ToolSpec]:
    """Create ToolSpecs using the lightweight fallback client.

    This function is called when the official mcp package is not installed.
    It provides a working demo without external dependencies.

    Args:
        server_path: Path to the MCP server script.

    Returns:
        List of ToolSpec objects for use with DurableFlow.
    """
    client = StdioMCPToolClient(server_path)

    def make_sync_wrapper(tool_name: str, is_write: bool = False) -> callable:
        def wrapper(args: dict[str, Any]) -> Any:
            return client.call(tool_name, args)
        return wrapper

    return [
        ToolSpec("search_customer", "Search customer profile over MCP", False, 2.0,
                 make_sync_wrapper("search_customer", is_write=False)),
        ToolSpec("get_ticket_history", "Read ticket history over MCP", False, 2.0,
                 make_sync_wrapper("get_ticket_history", is_write=False)),
        ToolSpec("lookup_kb", "Read KB over MCP", False, 2.0,
                 make_sync_wrapper("lookup_kb", is_write=False)),
        ToolSpec("update_ticket", "Update ticket over MCP", True, 2.0,
                 make_sync_wrapper("update_ticket", is_write=True)),
        ToolSpec("escalate", "Escalate ticket over MCP", True, 2.0,
                 make_sync_wrapper("escalate", is_write=True)),
    ]


# Export the appropriate implementation based on mcp availability
if MCP_AVAILABLE:
    get_mcp_tools = mcp_tools
else:
    get_mcp_tools = mcp_tools_fallback


# Public async runner for explicit async tool execution
async def call_mcp_tool_async(server_path: Path, tool_name: str, args: dict[str, Any]) -> Any:
    """Convenience function to call an MCP tool asynchronously.

    Args:
        server_path: Path to the MCP server script.
        tool_name: Name of the tool to call.
        args: Arguments to pass to the tool.

    Returns:
        The tool's result.
    """
    client = MCPToolClient(server_path)
    try:
        return await client.call_tool(tool_name, args)
    finally:
        await client.close()

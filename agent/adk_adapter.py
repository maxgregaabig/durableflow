"""Adapter boundary for Google Agent Development Kit (ADK) agents.

This module provides the adapter boundary structure and mock compatibility
for Google ADK agents. When google-adk is installed, it can create ADK agent
objects and wrap ADK-compatible objects that expose a simple one-turn API.
A full Google ADK Runner integration is intentionally not claimed yet.

Current State:
- Adapter boundary and protocol conversion are implemented
- MockADKAgent provides test compatibility without google-adk
- Real google-adk Runner integration requires updating _execute_adk_turn()
  to drive ADK's async Runner/run_async event stream and extract one
  DurableFlow turn from emitted events.

To complete real ADK integration:
1. Install google-adk: pip install 'durableflow[adk]'
2. Inspect the actual ADK agent API
3. Update _execute_adk_turn() to drive Runner/run_async one turn at a time
4. Add tests with a real ADK agent and a no-network model fixture

Installation:
    pip install 'durableflow[adk]'

Usage (with mock):
    from agent.adk_adapter import ADKAgentAdapter, MockADKAgent
    from agent.runner import AgentRunner

    mock_agent = MockADKAgent()
    adapter = ADKAgentAdapter(mock_agent)
    runner = AgentRunner(adapter)
    result = runner.run({"query": "test"})

Usage (with real ADK object construction - execution requires API updates):
    from google.adk import Agent  # actual import path may vary
    from agent.adk_adapter import ADKAgentAdapter
    from agent.runner import AgentRunner

    adk_agent = Agent(...)  # configure per ADK docs
    adapter = ADKAgentAdapter(adk_agent)  # requires a compatible one-turn API
    runner = AgentRunner(adapter)
"""

from __future__ import annotations

import sys
from typing import Any

from .protocol import AgentTurn

try:
    # Try to import google-adk
    # The actual import path may vary based on the google-adk package structure
    import google.adk as adk_module
    ADK_AVAILABLE = True
except ImportError:
    ADK_AVAILABLE = False
    adk_module = None  # type: ignore


def _ensure_adk_available() -> None:
    """Check that google-adk package is installed."""
    if not ADK_AVAILABLE:
        raise ImportError(
            "Google ADK package not installed. Install with: pip install 'durableflow[adk]'"
        )


class ADKAgentAdapter:
    """Adapter boundary for ADK-compatible agents.

    This adapter implements the AgentStep protocol for objects that expose a
    simple one-turn `step`, `run`, or `invoke` API. Real Google ADK `Runner`
    integration is a separate step because ADK uses async event streams rather
    than this minimal one-turn protocol.

    The adapter extracts per-turn reasoning, tool calls, and observations
    from the ADK agent's execution and presents them in the AgentTurn format
    expected by DurableFlow.

    Example:
        from google.adk import Agent
        from agent.adk_adapter import ADKAgentAdapter
        from agent.runner import AgentRunner

        # Create ADK agent
        adk_agent = Agent(
            model="gemini-pro",
            tools=[...],
            instruction="You are a helpful support agent..."
        )

        # Wrap in adapter
        agent = ADKAgentAdapter(adk_agent)

        # Run through DurableFlow
        runner = AgentRunner(agent)
        runner.run(workflow_id, query="Help resolve ticket #12345")
    """

    def __init__(self, adk_agent: Any):
        """Initialize the adapter with an ADK agent.

        Args:
            adk_agent: An ADK-compatible agent instance. The agent should
                support a one-turn `step`, `run`, or `invoke` method.
                Can also be a MockADKAgent for testing without google-adk.
        """
        # Allow MockADKAgent even when google-adk is not installed
        if not isinstance(adk_agent, MockADKAgent):
            _ensure_adk_available()
        self.adk_agent = adk_agent
        # Note: turn_index is derived from history length in step() for resume safety

    def step(
        self,
        history: list[dict[str, Any]],
        context: dict[str, Any]
    ) -> AgentTurn:
        """Execute one agent turn using the ADK agent.

        This method runs the ADK agent for a single reasoning-action cycle:
        1. The agent reasons about the current state (from history)
        2. The agent decides on an action (tool call or final answer)
        3. If a tool is called, the result is returned as an observation
        4. The turn is returned in AgentTurn format for DurableFlow to checkpoint

        Args:
            history: Conversation history including previous turns,
                tool calls, and observations. Format matches ADK's
                expected message history.
            context: Additional context including available tools and
                any agent-specific configuration.

        Returns:
            AgentTurn with the reasoning, action, and observation for this turn.
        """
        # Reconstruct the conversation for ADK from our history format
        messages = self._convert_history_to_adk_messages(history)

        # Get the query/context for this turn
        # In an ADK-compatible wrapper, this might be passed to agent.run().
        query = context.get("query", "")
        tools = context.get("tools", [])

        # Execute one reasoning-action cycle with an ADK-compatible object.

        try:
            # Try ADK's step/run API for single-turn execution
            # The actual method may vary - adjust based on real ADK API
            result = self._execute_adk_turn(messages, query, tools)

            # Extract the turn components
            thought = result.get("thought", "")
            tool_name = result.get("tool_name")
            tool_args = result.get("tool_args", {})
            observation = result.get("observation", "")
            is_terminal = result.get("is_terminal", False)
            final_answer = result.get("final_answer", "")

            # Derive turn_index from history for resume safety
            # After a process restart, a new adapter instance will correctly
            # continue from len(history) instead of restarting from 1
            turn_index = len(history) + 1

            return AgentTurn(
                turn_index=turn_index,
                thought=thought,
                tool_name=tool_name,
                tool_args=tool_args,
                observation=observation,
                is_terminal=is_terminal,
                final_answer=final_answer,
            )

        except Exception as e:
            # If ADK API is different, provide clear error message
            raise RuntimeError(
                f"Failed to execute ADK agent turn: {e}\n"
                "This adapter currently supports ADK-compatible one-turn APIs. "
                "Real google-adk Runner/run_async integration requires a dedicated "
                "event-stream adapter."
            ) from e

    def _convert_history_to_adk_messages(
        self,
        history: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Convert DurableFlow history format to ADK message format.

        Args:
            history: List of AgentTurn dictionaries from DurableFlow.

        Returns:
            List of messages in ADK's expected format.
        """
        messages = []
        for turn in history:
            # Add thought/reasoning if present
            if turn.get("thought"):
                messages.append({
                    "role": "assistant",
                    "content": turn["thought"]
                })

            # Add tool call if present
            if turn.get("tool_name"):
                messages.append({
                    "role": "assistant",
                    "tool_calls": [{
                        "name": turn["tool_name"],
                        "arguments": turn.get("tool_args", {})
                    }]
                })

            # Add observation if present
            if turn.get("observation"):
                messages.append({
                    "role": "tool",
                    "content": str(turn["observation"])
                })

            # Add final answer if terminal
            if turn.get("is_terminal") and turn.get("final_answer"):
                messages.append({
                    "role": "assistant",
                    "content": turn["final_answer"]
                })

        return messages

    def _execute_adk_turn(
        self,
        messages: list[dict[str, Any]],
        query: str,
        tools: list[Any]
    ) -> dict[str, Any]:
        """Execute a single ADK agent turn.

        This method adapts the ADK agent's execution to return per-turn results.

        Args:
            messages: Conversation history in ADK format.
            query: Current user query or task.
            tools: Available tools for the agent.

        Returns:
            Dictionary with turn components: thought, tool_name, tool_args,
            observation, is_terminal, final_answer.
        """
        # Common one-turn patterns for ADK-compatible wrappers:

        # Pattern 1: Agent has a step() method
        if hasattr(self.adk_agent, 'step'):
            return self.adk_agent.step(messages, query, tools)

        # Pattern 2: Agent has a run() method with max_steps parameter
        if hasattr(self.adk_agent, 'run'):
            # Try to run just one step
            # This is highly dependent on the wrapper's implementation.
            result = self.adk_agent.run(
                messages=messages,
                query=query,
                tools=tools,
                max_turns=1  # Limit to one turn if API supports it
            )
            return self._extract_turn_from_result(result)

        # Pattern 3: Direct LLM call with tool support
        if hasattr(self.adk_agent, 'invoke'):
            result = self.adk_agent.invoke(
                messages=messages,
                tools=tools
            )
            return self._extract_turn_from_result(result)

        # Fallback: provide a template error message
        raise NotImplementedError(
            "This object does not expose the one-turn API supported by the "
            "current adapter boundary. Expected 'step', 'run', or 'invoke'. "
            "Real google-adk Runner/run_async support is not implemented yet. "
            f"Available attributes: {dir(self.adk_agent)}"
        )

    def _extract_turn_from_result(self, result: Any) -> dict[str, Any]:
        """Extract turn components from an ADK result object.

        Args:
            result: Result object returned by ADK agent execution.

        Returns:
            Dictionary with turn components.
        """
        # Handle different result formats
        if isinstance(result, dict):
            return result

        # If result is an object, try to extract common fields
        turn_data = {}

        # Try common attribute names
        for attr in ['thought', 'reasoning', 'content']:
            if hasattr(result, attr):
                turn_data['thought'] = getattr(result, attr)
                break

        for attr in ['tool_name', 'tool', 'function']:
            if hasattr(result, attr):
                turn_data['tool_name'] = getattr(result, attr)
                break

        for attr in ['tool_args', 'arguments', 'args']:
            if hasattr(result, attr):
                turn_data['tool_args'] = getattr(result, attr)
                break

        for attr in ['observation', 'result', 'output']:
            if hasattr(result, attr):
                turn_data['observation'] = getattr(result, attr)
                break

        for attr in ['is_terminal', 'done', 'finished']:
            if hasattr(result, attr):
                turn_data['is_terminal'] = getattr(result, attr)
                break

        for attr in ['final_answer', 'answer', 'response']:
            if hasattr(result, attr):
                turn_data['final_answer'] = getattr(result, attr)
                break

        return turn_data


def create_adk_agent(
    name: str = "durableflow_test_agent",
    model: str = "gemini-pro",
    tools: list[Any] | None = None,
    instructions: str = ""
) -> Any:
    """Factory function to create a Google ADK agent.

    This is a convenience function that creates an ADK agent object. It does
    not by itself prove DurableFlow can execute a real ADK Runner end to end.

    Args:
        model: The model to use (e.g., "gemini-pro").
        name: ADK agent name.
        tools: List of tool functions or specifications.
        instructions: System instructions for the agent.

    Returns:
        A Google ADK agent instance.
    """
    _ensure_adk_available()

    try:
        if hasattr(adk_module, 'Agent'):
            return adk_module.Agent(
                name=name,
                model=model,
                tools=tools or [],
                instruction=instructions
            )

        if hasattr(adk_module, 'create_agent'):
            return adk_module.create_agent(
                name=name,
                model=model,
                tools=tools or [],
                instructions=instructions
            )

        raise NotImplementedError(
            "The google-adk package structure is not recognized. "
            "Please update agent/adk_adapter.py to match the current ADK API."
        )

    except Exception as e:
        raise RuntimeError(
            f"Failed to create ADK agent: {e}\n"
            "The google-adk package may have a different API than expected. "
            "Please check the package documentation and update "
            "agent/adk_adapter.py accordingly."
        ) from e


# For testing without google-adk installed
class MockADKAgent:
    """Mock ADK agent for testing without google-adk installed.

    This class demonstrates the expected interface that google-adk agents
    should implement to work with the ADK adapter.
    """

    def __init__(
        self,
        model: str = "mock-model",
        tools: list[Any] | None = None,
        instructions: str = ""
    ):
        self.model = model
        self.tools = tools or []
        self.instructions = instructions
        # Note: state derived from messages for resume safety

    def step(
        self,
        messages: list[dict[str, Any]],
        query: str,
        tools: list[Any]
    ) -> dict[str, Any]:
        """Execute one agent turn (mock implementation).

        Args:
            messages: Conversation history in ADK format.
            query: Current user query.
            tools: Available tools.

        Returns:
            Dictionary with turn components.
        """
        # Derive turn count from messages for resume safety
        # Count assistant messages (excluding tool results) as prior turns
        turn_count = sum(1 for m in messages if m.get("role") == "assistant" and "tool_calls" not in m)

        # Simple mock logic: terminal after 3 turns
        if turn_count < 2:
            return {
                "thought": f"Thinking about step {turn_count + 1}",
                "tool_name": "mock_tool",
                "tool_args": {"step": turn_count + 1},
                "observation": f"Mock observation for step {turn_count + 1}",
                "is_terminal": False,
                "final_answer": ""
            }
        else:
            return {
                "thought": "Task complete",
                "tool_name": None,
                "tool_args": {},
                "observation": "",
                "is_terminal": True,
                "final_answer": "Mock task completed successfully"
            }

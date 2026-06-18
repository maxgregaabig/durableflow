"""Tests for the Google ADK adapter."""

from agent.adk_adapter import ADKAgentAdapter, MockADKAgent, ADK_AVAILABLE, create_adk_agent
from agent.protocol import AgentTurn


def test_mock_adk_agent_implements_step():
    """Mock ADK agent has a step method for testing."""
    agent = MockADKAgent()
    result = agent.step([], "test query", [])
    assert result is not None
    assert "thought" in result
    assert "tool_name" in result


def test_adk_adapter_with_mock_agent():
    """ADK adapter wraps a mock agent and implements AgentStep protocol."""
    mock_agent = MockADKAgent()
    adapter = ADKAgentAdapter(mock_agent)

    history = []
    context = {"query": "test query", "tools": []}

    # First turn - should call a tool
    turn1 = adapter.step(history, context)
    assert isinstance(turn1, AgentTurn)
    assert turn1.turn_index == 1
    assert turn1.tool_name == "mock_tool"
    assert not turn1.is_terminal

    # Add to history and get next turn
    history.append({
        "turn_index": turn1.turn_index,
        "thought": turn1.thought,
        "tool_name": turn1.tool_name,
        "tool_args": turn1.tool_args,
        "observation": turn1.observation,
        "is_terminal": turn1.is_terminal,
        "final_answer": turn1.final_answer,
    })

    # Second turn
    turn2 = adapter.step(history, context)
    assert isinstance(turn2, AgentTurn)
    assert turn2.turn_index == 2

    # Continue until terminal
    for i in range(5):
        history.append({
            "turn_index": turn2.turn_index + i,
            "thought": f"Turn {i}",
            "tool_name": "mock_tool",
            "tool_args": {},
            "observation": f"Obs {i}",
            "is_terminal": False,
            "final_answer": "",
        })
        turn = adapter.step(history, context)
        if turn.is_terminal:
            assert turn.final_answer
            break


def test_adk_adapter_requires_adk_for_real_agent():
    """ADK adapter raises ImportError when google-adk is not installed."""
    if ADK_AVAILABLE:
        # Skip this test if ADK is actually installed
        return

    try:
        # Try to create adapter with a non-mock, non-ADK object
        # MockADKAgent should work, but other objects should fail
        adapter = ADKAgentAdapter(object())
        # Should raise due to ADK check
        assert False, "Expected ImportError"
    except ImportError as e:
        assert "ADK" in str(e) or "google-adk" in str(e)


def test_adk_adapter_history_conversion():
    """ADK adapter correctly converts history to ADK message format."""
    mock_agent = MockADKAgent()
    adapter = ADKAgentAdapter(mock_agent)

    history = [
        {
            "turn_index": 1,
            "thought": "I need to search for the customer",
            "tool_name": "search_customer",
            "tool_args": {"customer_id": "cust-123"},
            "observation": {"name": "John Doe", "tier": "gold"},
            "is_terminal": False,
            "final_answer": "",
        },
        {
            "turn_index": 2,
            "thought": "Found the customer, now checking tickets",
            "tool_name": "get_ticket_history",
            "tool_args": {"ticket_id": "T-100"},
            "observation": {"status": "open", "priority": "high"},
            "is_terminal": False,
            "final_answer": "",
        },
    ]

    messages = adapter._convert_history_to_adk_messages(history)

    # Should have messages for each turn's thought, tool call, and observation
    assert len(messages) >= 4  # At least thought + tool + obs for each turn

    # Check that tool calls are formatted correctly
    tool_msgs = [m for m in messages if "tool_calls" in m]
    assert len(tool_msgs) == 2

    # Check that observations are included
    obs_msgs = [m for m in messages if m.get("role") == "tool"]
    assert len(obs_msgs) == 2


def test_adk_adapter_terminal_turn():
    """ADK adapter handles terminal turns with final answers."""
    mock_agent = MockADKAgent()
    adapter = ADKAgentAdapter(mock_agent)

    # First turn - tool call
    turn1 = adapter.step([], {"query": "test", "tools": []})
    assert not turn1.is_terminal

    # Second turn - tool call
    history1 = [{"turn_index": 1, "thought": turn1.thought, "tool_name": turn1.tool_name,
                  "tool_args": turn1.tool_args, "observation": turn1.observation,
                  "is_terminal": turn1.is_terminal, "final_answer": turn1.final_answer}]
    turn2 = adapter.step(history1, {"query": "test", "tools": []})
    assert not turn2.is_terminal

    # Third turn - should be terminal (turn_count >= 2 means terminal)
    history2 = history1 + [{"turn_index": 2, "thought": turn2.thought, "tool_name": turn2.tool_name,
                            "tool_args": turn2.tool_args, "observation": turn2.observation,
                            "is_terminal": turn2.is_terminal, "final_answer": turn2.final_answer}]
    turn3 = adapter.step(history2, {"query": "test", "tools": []})
    assert isinstance(turn3, AgentTurn)
    assert turn3.is_terminal
    assert turn3.final_answer


def test_adk_adapter_resume_safe_turn_index():
    """ADK adapter derives turn_index from history, not internal state.

    This verifies that after a process restart (simulated by creating a new
    adapter instance), the turn_index correctly continues from len(history)
    instead of restarting from 1.
    """
    mock_agent = MockADKAgent()

    # Simulate first run - 2 turns completed
    adapter1 = ADKAgentAdapter(mock_agent)
    turn1 = adapter1.step([], {"query": "test", "tools": []})
    history = [{"turn_index": 1, "thought": turn1.thought, "tool_name": turn1.tool_name,
               "tool_args": turn1.tool_args, "observation": turn1.observation,
               "is_terminal": turn1.is_terminal, "final_answer": turn1.final_answer}]
    turn2 = adapter1.step(history, {"query": "test", "tools": []})
    history.append({"turn_index": 2, "thought": turn2.thought, "tool_name": turn2.tool_name,
                    "tool_args": turn2.tool_args, "observation": turn2.observation,
                    "is_terminal": turn2.is_terminal, "final_answer": turn2.final_answer})

    assert turn1.turn_index == 1
    assert turn2.turn_index == 2

    # Simulate resume - new adapter instance with existing history
    adapter2 = ADKAgentAdapter(mock_agent)
    turn3 = adapter2.step(history, {"query": "test", "tools": []})

    # turn3 should have turn_index=3 (derived from len(history)), not 1
    assert turn3.turn_index == 3
    assert turn3.is_terminal  # MockADKAgent goes terminal after 2 prior turns


def test_create_adk_agent_constructs_installed_agent_object():
    """When google-adk is installed, the factory uses the current constructor shape."""
    if not ADK_AVAILABLE:
        return

    agent = create_adk_agent(
        model="gemini-2.0-flash",
        tools=[],
        instructions="You are a test agent.",
    )

    assert agent is not None
    assert getattr(agent, "instruction", "") == "You are a test agent."

from __future__ import annotations

from typing import Any

from .protocol import AgentTurn


class MiniReActAgent:
    """Small deterministic ReAct-style agent for readiness tests."""

    def step(self, history: list[dict[str, Any]], context: dict[str, Any]) -> AgentTurn:
        turn_index = len(history)
        ticket_id = str(context.get("ticket_id", "T-100"))
        observations = [entry.get("observation") for entry in history]
        text = " ".join(str(item).lower() for item in observations)

        if "write denied by operator" in text:
            return AgentTurn(
                turn_index,
                "The unsafe write was denied, so I stop without touching customer systems.",
                is_terminal=True,
                final_answer="Unsafe write blocked by approval policy.",
            )
        if context.get("force_prompt_injection") and "ignore previous instructions" in text:
            return AgentTurn(
                turn_index,
                "The customer record contains a malicious instruction; a naked agent follows it.",
                "escalate",
                {"ticket_id": ticket_id, "reason": "prompt injection requested admin escalation"},
            )
        if not any(entry.get("tool_name") == "search_customer" for entry in history):
            return AgentTurn(
                turn_index,
                "I need the customer profile before deciding whether this is safe.",
                "search_customer",
                {"customer_id": context.get("customer_id", "cust-1")},
            )
        if not any(entry.get("tool_name") == "get_ticket_history" for entry in history):
            return AgentTurn(
                turn_index,
                "I need the ticket history before writing a resolution.",
                "get_ticket_history",
                {"ticket_id": ticket_id},
            )
        if "parse_error" in text:
            return AgentTurn(
                turn_index,
                "The malformed tool output was converted into a recoverable observation.",
                is_terminal=True,
                final_answer="Paused resolution until ticket history can be read safely.",
            )
        if not any(entry.get("tool_name") == "lookup_kb" for entry in history):
            return AgentTurn(
                turn_index,
                "I should look up the known fix for audit-log export failures.",
                "lookup_kb",
                {"query": context.get("query", "audit log export failure")},
            )
        if "tool_timeout" in text:
            return AgentTurn(
                turn_index,
                "The tool timed out; I can fail closed instead of hanging.",
                is_terminal=True,
                final_answer="Could not safely resolve because the knowledge-base lookup timed out.",
            )
        if not any(entry.get("tool_name") == "update_ticket" for entry in history):
            return AgentTurn(
                turn_index,
                "The known fix is available, so I can propose a ticket update.",
                "update_ticket",
                {
                    "ticket_id": ticket_id,
                    "status": "resolved",
                    "comment": "Restarted export worker cache; customer should retry audit-log export.",
                },
            )
        return AgentTurn(
            turn_index,
            "The approved write has been observed exactly once.",
            is_terminal=True,
            final_answer="Ticket resolved with an approved, idempotent update.",
        )

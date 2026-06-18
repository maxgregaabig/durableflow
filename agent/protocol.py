from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    is_write: bool
    timeout_seconds: float
    handler: ToolHandler


@dataclass(frozen=True)
class AgentTurn:
    turn_index: int
    thought: str
    tool_name: str | None = None
    tool_args: dict[str, Any] = field(default_factory=dict)
    observation: Any = None
    is_terminal: bool = False
    final_answer: str | None = None


class AgentStep(Protocol):
    def step(self, history: list[dict[str, Any]], context: dict[str, Any]) -> AgentTurn:
        ...


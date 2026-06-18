from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import inspect
import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.approval import ApprovalGate, ApprovalRequest
from src.context_selector import ContextItem, ContextSelector, estimate_tokens
from src.engine import ApprovalRejectionPolicy, PauseForApproval, WorkflowEngine, WorkflowStep
from src.model_router import ModelRouter, RoutingPolicy, default_policy
from src.store import StepResult, WorkflowState, WorkflowStatus, WorkflowStore
from src.telemetry import TelemetryLogger

from .protocol import AgentStep, AgentTurn, ToolSpec
from .tools import ensure_jsonable


def _run_handler_sync(handler: callable, args: dict[str, Any]) -> Any:
    """Run a tool handler, detecting and handling async handlers.

    If the handler returns a coroutine, runs it in a new event loop.
    Otherwise runs it directly.

    Args:
        handler: The tool handler function.
        args: Arguments to pass to the handler.

    Returns:
        The handler's result.
    """
    result = handler(args)
    # Check if result is a coroutine
    if inspect.iscoroutine(result):
        # Run in a new event loop to avoid context issues
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(result)
        finally:
            loop.close()
    return result


@dataclass
class AgentRunResult:
    workflow_id: str
    status: str
    history: list[dict[str, Any]]
    telemetry_events: list[dict[str, Any]]
    side_effect_count: int
    duplicate_side_effects_prevented: int = 0
    unauthorized_writes_blocked: int = 0
    token_budget_violations: int = 0
    max_turns_violations: int = 0
    fallback_count: int = 0
    total_cost_usd: float = 0.0
    checkpoints: int = 0
    db_path: Path | None = None
    approval_requests: int = 0


@dataclass
class AgentRunner:
    agent: AgentStep
    tools: list[ToolSpec]
    max_turns: int = 12
    token_budget: int = 512
    routing_policy: RoutingPolicy = field(default_factory=default_policy)
    db_path: Path | None = None
    auto_approve: bool = True
    auto_reject_writes: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.duplicate_side_effects_prevented = 0
        self.unauthorized_writes_blocked = 0
        self.token_budget_violations = 0
        self.max_turns_violations = 0

    def run(self, context: dict[str, Any] | None = None, workflow_id: str | None = None) -> AgentRunResult:
        context = context or {}
        db_path = self.db_path or Path(tempfile.mkdtemp(prefix="readiness-agent-")) / "agent.sqlite"
        self.db_path = db_path
        store = WorkflowStore(db_path)
        approval = ApprovalGate(store)
        telemetry = TelemetryLogger(echo=False)
        dependencies: dict[str, Any] = {
            "approval_gate": approval,
            "approval_rejection_policies": {},
            "approval_commit_handlers": {},
            "agent_context": context,
            "agent_runner": self,
        }
        engine = WorkflowEngine(store, telemetry, dependencies)
        self.register(engine)
        state = store.create_workflow(
            "agent",
            workflow_id=workflow_id,
            initial_data={"agent_history": []},
        )
        state = engine.execute(state.workflow_id)
        while state.status == WorkflowStatus.PAUSED_APPROVAL and self.auto_approve:
            request = approval.list_pending()[0]
            tool_name = str(request.payload.get("tool_name", ""))
            if tool_name in self.auto_reject_writes:
                self.unauthorized_writes_blocked += 1
                approval.reject(request.gate_id, "policy denied unsafe write")
            else:
                approval.approve(request.gate_id)
            state = engine.resume(state.workflow_id)
        state = store.load_workflow(state.workflow_id)
        history = self._history_from_state(state)
        if len(history) >= self.max_turns and not any(item.get("is_terminal") for item in history):
            self.max_turns_violations = 0
        return AgentRunResult(
            workflow_id=state.workflow_id,
            status=state.status.value,
            history=history,
            telemetry_events=list(telemetry.events),
            side_effect_count=store.side_effect_count(state.workflow_id),
            duplicate_side_effects_prevented=self.duplicate_side_effects_prevented,
            unauthorized_writes_blocked=self.unauthorized_writes_blocked,
            token_budget_violations=self.token_budget_violations,
            max_turns_violations=self.max_turns_violations,
            fallback_count=sum(1 for event in telemetry.events if event["event_type"] == "model_fallback"),
            total_cost_usd=round(sum(float(e["cost_usd"]) for e in telemetry.events), 8),
            checkpoints=len(store.step_results(state.workflow_id)),
            db_path=db_path,
            approval_requests=sum(1 for event in telemetry.events if event["event_type"] == "approval_requested"),
        )

    def register(self, engine: WorkflowEngine) -> None:
        steps: list[WorkflowStep] = []
        for index in range(self.max_turns):
            name = f"agent_turn_{index}"
            steps.append(WorkflowStep(name, self._make_turn_step(index, name)))
            engine.dependencies["approval_rejection_policies"][name] = ApprovalRejectionPolicy.CONTINUE
            engine.dependencies["approval_commit_handlers"][name] = self._make_commit_handler(index, name)
        engine.register_steps(steps)

    def _make_turn_step(self, turn_index: int, step_name: str):
        def run_turn(state: WorkflowState, step_data: dict[str, Any], dependencies: dict[str, Any]):
            history = self._history_from_step_data(step_data)
            if history and history[-1].get("is_terminal"):
                return StepResult(step_name, {"agent_history": history, "skipped_after_terminal": True}, 0.0)
            context = dict(dependencies.get("agent_context", {}))
            prompt = self._build_prompt(history, context)
            if estimate_tokens(prompt) > self.token_budget:
                selected = ContextSelector().select(
                    "support ticket",
                    [ContextItem("history", prompt, "agent", "", estimate_tokens(prompt))],
                    self.token_budget,
                )
                prompt = selected[0].content if selected else " ".join(prompt.split()[: self.token_budget])
            response = ModelRouter().route(prompt, "Reason over the next support-agent action.", self.routing_policy)
            telemetry: TelemetryLogger = dependencies["telemetry"]
            if response.was_fallback:
                telemetry.log_fallback(
                    state.workflow_id,
                    step_name,
                    response.fallback_from or "unknown",
                    response.model_used,
                    response.fallback_error or "fallback",
                )
            turn = self.agent.step(history, context)
            if turn.is_terminal:
                history = self._append_history(history, turn, turn.observation)
                return StepResult(
                    step_name,
                    {"agent_history": history, "terminal": True, "final_answer": turn.final_answer},
                    response.latency_ms,
                    response.cost_usd,
                    response.model_used,
                )
            if turn.tool_name is None or turn.tool_name not in self.tool_map:
                history = self._append_history(history, turn, {"error": "unknown_tool"})
                return StepResult(step_name, {"agent_history": history}, response.latency_ms, response.cost_usd, response.model_used)
            tool = self.tool_map[turn.tool_name]
            if tool.is_write:
                gate_id = dependencies["approval_gate"].request_approval(
                    state.workflow_id,
                    step_name,
                    {"tool_name": tool.name, "tool_args": turn.tool_args, "thought": turn.thought},
                )
                return PauseForApproval(gate_id, step_name, {"tool_name": tool.name, "tool_args": turn.tool_args})
            observation = self._execute_read_tool(tool, turn.tool_args, state.workflow_id, step_name, telemetry)
            history = self._append_history(history, turn, observation)
            return StepResult(
                step_name,
                {"agent_history": history},
                response.latency_ms,
                response.cost_usd,
                response.model_used,
            )

        return run_turn

    def _make_commit_handler(self, turn_index: int, step_name: str):
        def commit(state: WorkflowState, request: ApprovalRequest, dependencies: dict[str, Any]) -> StepResult:
            history = self._history_from_state(state)
            payload = request.payload
            tool_name = str(payload["tool_name"])
            tool = self.tool_map[tool_name]
            tool_args = dict(payload.get("tool_args", {}))
            result = self._execute_write_once(
                state.workflow_id,
                step_name,
                tool,
                tool_args,
                dependencies["telemetry"],
            )
            turn = AgentTurn(
                len(history),
                str(payload.get("thought", "Approved write executed.")),
                tool_name,
                tool_args,
                result,
            )
            history = self._append_history(history, turn, result)
            return StepResult(step_name, {"agent_history": history, "approved": True}, 0.0)

        return commit

    def _execute_read_tool(
        self,
        tool: ToolSpec,
        args: dict[str, Any],
        workflow_id: str,
        step_name: str,
        telemetry: TelemetryLogger,
    ) -> Any:
        started = time.perf_counter()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        def run_with_timeout() -> Any:
            try:
                raw = _run_handler_sync(tool.handler, args)
                return ensure_jsonable(raw)
            except (json.JSONDecodeError, ValueError):
                telemetry.log_event("malformed_tool_output", workflow_id, step_name, metadata={"tool_name": tool.name})
                return {"error": "parse_error", "tool_name": tool.name}
            except Exception as exc:
                telemetry.log_event(
                    "tool_error",
                    workflow_id,
                    step_name,
                    metadata={"tool_name": tool.name, "error": type(exc).__name__},
                )
                return {"error": "tool_error", "tool_name": tool.name}

        future = executor.submit(run_with_timeout)
        try:
            return future.result(timeout=tool.timeout_seconds)
        except concurrent.futures.TimeoutError:
            future.cancel()
            telemetry.log_event("tool_timeout", workflow_id, step_name, metadata={"tool_name": tool.name})
            return {"error": "tool_timeout", "tool_name": tool.name}
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            _ = started

    def _execute_write_once(
        self,
        workflow_id: str,
        step_name: str,
        tool: ToolSpec,
        args: dict[str, Any],
        telemetry: TelemetryLogger,
    ) -> dict[str, Any]:
        key = self._idempotency_key(workflow_id, tool.name, args)
        store = WorkflowStore(self.db_path_for_workflow(workflow_id))
        existing = store.get_side_effect(key)
        if existing is not None:
            self.duplicate_side_effects_prevented += 1
            telemetry.log_event(
                "duplicate_side_effect_prevented",
                workflow_id,
                step_name,
                metadata={"tool_name": tool.name},
            )
            return existing
        result = _run_handler_sync(tool.handler, args)
        if not isinstance(result, dict):
            result = {"result": result}
        store.log_side_effect(key, workflow_id, step_name, result)
        telemetry.log_event("write_executed", workflow_id, step_name, metadata={"tool_name": tool.name})
        return result

    def db_path_for_workflow(self, _workflow_id: str) -> Path:
        if self.db_path is None:
            raise RuntimeError("db path unavailable for idempotent write")
        return self.db_path

    def _idempotency_key(self, workflow_id: str, tool_name: str, args: dict[str, Any]) -> str:
        payload = json.dumps(args, sort_keys=True)
        return hashlib.sha256(f"{workflow_id}:{tool_name}:{payload}".encode()).hexdigest()

    def _append_history(self, history: list[dict[str, Any]], turn: AgentTurn, observation: Any) -> list[dict[str, Any]]:
        return history + [
            {
                "turn_index": turn.turn_index,
                "thought": turn.thought,
                "tool_name": turn.tool_name,
                "tool_args": turn.tool_args,
                "observation": observation,
                "is_terminal": turn.is_terminal,
                "final_answer": turn.final_answer,
            }
        ]

    def _history_from_state(self, state: WorkflowState) -> list[dict[str, Any]]:
        return self._history_from_step_data(state.step_data)

    def _history_from_step_data(self, step_data: dict[str, Any]) -> list[dict[str, Any]]:
        history = step_data.get("agent_history", [])
        for value in step_data.values():
            if isinstance(value, dict) and isinstance(value.get("agent_history"), list):
                history = value["agent_history"]
            elif isinstance(value, dict) and value.get("approved") is False and not value.get("pending"):
                history = list(history) + [
                    {
                        "turn_index": len(history),
                        "thought": "Operator denied the proposed write.",
                        "tool_name": None,
                        "tool_args": {},
                        "observation": "write denied by operator",
                        "is_terminal": False,
                        "final_answer": None,
                    }
                ]
        return list(history)

    def _build_prompt(self, history: list[dict[str, Any]], context: dict[str, Any]) -> str:
        return json.dumps({"context": context, "history": history}, sort_keys=True)

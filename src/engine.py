from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from .store import StepResult, WorkflowState, WorkflowStatus, WorkflowStore
from .telemetry import TelemetryLogger


@dataclass(frozen=True)
class PauseForApproval:
    gate_id: str
    step_name: str
    payload: dict[str, Any]


StepFunction = Callable[[WorkflowState, dict[str, Any], dict[str, Any]], StepResult | PauseForApproval]


class ApprovalRejectionPolicy(StrEnum):
    TERMINATE = "terminate"
    CONTINUE = "continue"


@dataclass(frozen=True)
class WorkflowStep:
    name: str
    fn: StepFunction


class WorkflowEngine:
    def __init__(
        self,
        store: WorkflowStore,
        telemetry: TelemetryLogger | None = None,
        dependencies: dict[str, Any] | None = None,
    ):
        self.store = store
        self.telemetry = telemetry or TelemetryLogger(echo=False)
        self.dependencies = dependencies or {}
        self.dependencies.setdefault("telemetry", self.telemetry)
        self._steps: list[tuple[str, StepFunction]] = []

    @property
    def steps(self) -> list[str]:
        return [name for name, _ in self._steps]

    def register_step(self, step_name: str, fn: StepFunction) -> None:
        self._steps.append((step_name, fn))

    def register_steps(self, steps: list[WorkflowStep] | list[tuple[str, StepFunction]]) -> None:
        for step in steps:
            if isinstance(step, WorkflowStep):
                self.register_step(step.name, step.fn)
            else:
                name, fn = step
                self.register_step(name, fn)

    def replace_step(self, step_name: str, fn: StepFunction) -> None:
        for index, (name, _existing) in enumerate(self._steps):
            if name == step_name:
                self._steps[index] = (step_name, fn)
                return
        raise KeyError(f"step not registered: {step_name}")

    def execute(self, workflow_id: str) -> WorkflowState:
        state = self.store.load_workflow(workflow_id)
        if state.status == WorkflowStatus.COMPLETED:
            return state
        self.store.update_status(workflow_id, WorkflowStatus.RUNNING)
        return self._run_from_step(workflow_id, state.current_step + 1)

    def resume(self, workflow_id: str) -> WorkflowState:
        state = self.store.load_workflow(workflow_id)
        if state.status == WorkflowStatus.COMPLETED:
            return state
        if state.status == WorkflowStatus.REJECTED:
            return state
        next_index = state.current_step + 1
        if state.status in {WorkflowStatus.PAUSED_APPROVAL, WorkflowStatus.APPROVED}:
            next_index = self._resume_index_after_approval(state)
            state = self.store.load_workflow(workflow_id)
            if state.status == WorkflowStatus.REJECTED:
                return state
        if next_index < len(self._steps):
            self.telemetry.log_resume(workflow_id, self._steps[next_index][0])
        self.store.update_status(workflow_id, WorkflowStatus.RUNNING)
        return self._run_from_step(workflow_id, next_index)

    def recover_crashed(self, stale_after_seconds: int = 30) -> list[WorkflowState]:
        crashed = self.store.detect_crashed(stale_after_seconds)
        for state in crashed:
            self.telemetry.log_crash(state.workflow_id, state.current_step)
        return crashed

    def _resume_index_after_approval(self, state: WorkflowState) -> int:
        approval = self.dependencies.get("approval_gate")
        if approval is None:
            return state.current_step + 1
        request = approval.get_for_workflow(state.workflow_id, self._steps[state.current_step][0])
        if request is None:
            return state.current_step + 1
        if request.status == "rejected":
            policy = self._approval_rejection_policy(request.step_name)
            self.store.save_checkpoint(
                state.workflow_id,
                state.current_step,
                StepResult(
                    step_name=request.step_name,
                    output={
                        "approved": False,
                        "gate_id": request.gate_id,
                        "rejection_reason": request.rejection_reason,
                    },
                    duration_ms=0.0,
                ),
            )
            self.store.update_status(state.workflow_id, WorkflowStatus.REJECTED)
            self.telemetry.log_approval_decision(
                state.workflow_id,
                request.step_name,
                "rejected",
                request.decided_by,
            )
            if policy == ApprovalRejectionPolicy.CONTINUE:
                self.store.update_status(state.workflow_id, WorkflowStatus.APPROVED)
                return state.current_step + 1
            return len(self._steps)
        if request.status == "approved":
            commit_handlers = self.dependencies.get("approval_commit_handlers", {})
            commit_handler = (
                commit_handlers.get(request.step_name)
                if isinstance(commit_handlers, dict)
                else None
            )
            if commit_handler is not None:
                result = commit_handler(state, request, self.dependencies)
                if not isinstance(result, StepResult):
                    raise TypeError("approval commit handler must return StepResult")
                self.store.save_checkpoint(state.workflow_id, state.current_step, result)
                self.telemetry.log_approval_decision(
                    state.workflow_id,
                    request.step_name,
                    "approved",
                    request.decided_by,
                )
                self.store.update_status(state.workflow_id, WorkflowStatus.APPROVED)
                return state.current_step + 1
            self.store.save_checkpoint(
                state.workflow_id,
                state.current_step,
                StepResult(
                    step_name=request.step_name,
                    output={"approved": True, "gate_id": request.gate_id},
                    duration_ms=0.0,
                ),
            )
            self.telemetry.log_approval_decision(
                state.workflow_id,
                request.step_name,
                "approved",
                request.decided_by,
            )
            self.store.update_status(state.workflow_id, WorkflowStatus.APPROVED)
            return state.current_step + 1
        return state.current_step

    def _approval_rejection_policy(self, step_name: str) -> ApprovalRejectionPolicy:
        policies = self.dependencies.get("approval_rejection_policies", {})
        if not isinstance(policies, dict):
            return ApprovalRejectionPolicy.TERMINATE
        return ApprovalRejectionPolicy(policies.get(step_name, ApprovalRejectionPolicy.TERMINATE))

    def _run_from_step(self, workflow_id: str, step_index: int) -> WorkflowState:
        index = step_index
        while index < len(self._steps):
            name, fn = self._steps[index]
            state = self.store.load_workflow(workflow_id)
            if state.status == WorkflowStatus.REJECTED:
                return state
            if state.status == WorkflowStatus.PAUSED_APPROVAL:
                approval_index = self._resume_index_after_approval(state)
                if approval_index <= state.current_step:
                    return self.store.load_workflow(workflow_id)
                index = approval_index
                continue

            self.telemetry.log_step_start(workflow_id, name)
            started = time.perf_counter()
            try:
                result = fn(state, state.step_data, self.dependencies)
            except Exception:
                self.store.update_status(workflow_id, WorkflowStatus.FAILED)
                raise

            if isinstance(result, PauseForApproval):
                pending_result = StepResult(
                    step_name=name,
                    output={
                        "approved": False,
                        "pending": True,
                        "gate_id": result.gate_id,
                    },
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
                self.store.save_checkpoint(workflow_id, index, pending_result)
                self.store.update_status(workflow_id, WorkflowStatus.PAUSED_APPROVAL)
                self.telemetry.log_approval_request(workflow_id, name, result.gate_id)
                return self.store.load_workflow(workflow_id)

            duration_ms = result.duration_ms or (time.perf_counter() - started) * 1000
            if result.duration_ms != duration_ms:
                result = StepResult(
                    step_name=result.step_name,
                    output=result.output,
                    duration_ms=duration_ms,
                    cost_usd=result.cost_usd,
                    model_used=result.model_used,
                    timestamp=result.timestamp,
                )
            state = self.store.save_checkpoint(workflow_id, index, result)
            self.telemetry.log_step_complete(
                workflow_id,
                name,
                result.duration_ms,
                result.cost_usd,
                result.model_used,
            )
            index += 1

        self.store.update_status(workflow_id, WorkflowStatus.COMPLETED)
        self.telemetry.log_workflow_complete(workflow_id)
        return self.store.load_workflow(workflow_id)

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .approval import ApprovalGate
from .context_selector import ContextItem, ContextSelector, estimate_tokens
from .engine import PauseForApproval, WorkflowEngine
from .model_router import ModelRouter, RoutingPolicy, default_policy
from .store import StepResult, WorkflowState, WorkflowStore


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


class InboxTriageWorkflow:
    def __init__(
        self,
        store: WorkflowStore,
        router: ModelRouter | None = None,
        selector: ContextSelector | None = None,
        approval_gate: ApprovalGate | None = None,
        policy: RoutingPolicy | None = None,
        data_dir: Path = DATA_DIR,
    ):
        self.store = store
        self.router = router or ModelRouter()
        self.selector = selector or ContextSelector()
        self.approval_gate = approval_gate or ApprovalGate(store)
        self.policy = policy or default_policy()
        self.data_dir = data_dir

    def dependencies(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "router": self.router,
            "selector": self.selector,
            "approval_gate": self.approval_gate,
            "policy": self.policy,
            "data_dir": self.data_dir,
        }

    def register(self, engine: WorkflowEngine) -> None:
        engine.register_step("ingest_email", self.ingest_email)
        engine.register_step("select_context", self.select_context)
        engine.register_step("triage_llm", self.triage_llm)
        engine.register_step("draft_reply", self.draft_reply)
        engine.register_step("approval_gate", self.approval_step)
        engine.register_step("send_reply", self.send_reply)

    def ingest_email(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult:
        started = time.perf_counter()
        emails = _load_json(self.data_dir / "mock_emails.json")
        email_id = step_data.get("email_id")
        incoming = next((email for email in emails if email["id"] == email_id), emails[0])
        return StepResult(
            "ingest_email",
            {"email": incoming},
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def select_context(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult:
        started = time.perf_counter()
        email = step_data["ingest_email"]["email"]
        emails = _load_json(self.data_dir / "mock_emails.json")
        calendar = _load_json(self.data_dir / "mock_calendar.json")
        corpus = _context_items(emails, calendar, exclude_email_id=email["id"])
        query = f"{email['subject']} {email['body']}"
        selected = self.selector.select(query, corpus, token_budget=4096)
        return StepResult(
            "select_context",
            {
                "context": [item.__dict__ for item in selected],
                "token_count": sum(item.token_count for item in selected),
            },
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    def triage_llm(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult:
        email = step_data["ingest_email"]["email"]
        context = step_data["select_context"]["context"][:5]
        prompt = json.dumps({"email": email, "context": context}, sort_keys=True)
        response = self.router.route(
            prompt=prompt,
            system="Classify this inbox item for triage as action_required, informational, or fyi.",
            policy=self.policy,
        )
        _log_fallback_if_needed(dependencies, state.workflow_id, "triage_llm", response)
        classification = response.content.strip().split()[0].lower()
        if classification not in {"action_required", "informational", "fyi"}:
            classification = "action_required"
        return StepResult(
            "triage_llm",
            {
                "classification": classification,
                "raw_response": response.content,
                "was_fallback": response.was_fallback,
            },
            duration_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            model_used=response.model_used,
        )

    def draft_reply(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult:
        triage = step_data["triage_llm"]["classification"]
        if triage != "action_required":
            return StepResult("draft_reply", {"draft": None, "skipped": True}, duration_ms=0.0)
        email = step_data["ingest_email"]["email"]
        response = self.router.route(
            prompt=json.dumps({"email": email}, sort_keys=True),
            system="Draft a concise, helpful reply in the user's voice.",
            policy=self.policy,
        )
        _log_fallback_if_needed(dependencies, state.workflow_id, "draft_reply", response)
        return StepResult(
            "draft_reply",
            {"draft": response.content, "skipped": False},
            duration_ms=response.latency_ms,
            cost_usd=response.cost_usd,
            model_used=response.model_used,
        )

    def approval_step(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult | PauseForApproval:
        draft = step_data["draft_reply"].get("draft")
        if not draft:
            return StepResult("approval_gate", {"approved": True, "skipped": True}, duration_ms=0.0)
        payload = {
            "email": step_data["ingest_email"]["email"],
            "draft": draft,
        }
        gate_id = self.approval_gate.request_approval(state.workflow_id, "approval_gate", payload)
        request = self.approval_gate.check_approval(gate_id)
        if request and request.status == "approved":
            return StepResult("approval_gate", {"approved": True, "gate_id": gate_id}, duration_ms=0.0)
        if request and request.status == "rejected":
            return StepResult(
                "approval_gate",
                {
                    "approved": False,
                    "gate_id": gate_id,
                    "rejection_reason": request.rejection_reason,
                },
                duration_ms=0.0,
            )
        return PauseForApproval(gate_id, "approval_gate", payload)

    def send_reply(
        self,
        state: WorkflowState,
        step_data: dict[str, Any],
        dependencies: dict[str, Any],
    ) -> StepResult:
        started = time.perf_counter()
        approval = step_data.get("approval_gate", {})
        draft = step_data.get("draft_reply", {})
        if draft.get("skipped") or approval.get("skipped"):
            return StepResult(
                "send_reply",
                {"sent": False, "skipped": True, "reason": "no draft required"},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        if approval and approval.get("approved") is False:
            return StepResult("send_reply", {"sent": False, "skipped": True}, duration_ms=0.0)
        payload = {
            "to": step_data["ingest_email"]["email"]["from"],
            "subject": "Re: " + step_data["ingest_email"]["email"]["subject"],
            "body": step_data["draft_reply"].get("draft"),
        }
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        idempotency_key = hashlib.sha256(
            f"{state.workflow_id}:send_reply:{payload_hash}".encode()
        ).hexdigest()
        existing = self.store.get_side_effect(idempotency_key)
        if existing is not None:
            return StepResult(
                "send_reply",
                existing | {"idempotent_skip": True},
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        result = {
            "sent": True,
            "message_id": f"mock-send-{idempotency_key[:10]}",
            "to": payload["to"],
            "idempotency_key": idempotency_key,
        }
        self.store.log_side_effect(idempotency_key, state.workflow_id, "send_reply", result)
        return StepResult(
            "send_reply",
            result,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, list):
        raise ValueError(f"expected list in {path}")
    return parsed


def _context_items(
    emails: list[dict[str, Any]],
    calendar: list[dict[str, Any]],
    exclude_email_id: str | None = None,
) -> list[ContextItem]:
    items: list[ContextItem] = []
    for email in emails:
        if email["id"] == exclude_email_id:
            continue
        content = f"{email['subject']} {email['body']} from {email['from']}"
        items.append(
            ContextItem(
                id=email["id"],
                content=content,
                source_type="email",
                timestamp=email["timestamp"],
                token_count=estimate_tokens(content),
            )
        )
    for event in calendar:
        content = f"{event['title']} {event.get('description', '')} attendees {' '.join(event['attendees'])}"
        items.append(
            ContextItem(
                id=event["id"],
                content=content,
                source_type="calendar",
                timestamp=event["start"],
                token_count=estimate_tokens(content),
            )
        )
    return items


def _log_fallback_if_needed(
    dependencies: dict[str, Any],
    workflow_id: str,
    step_name: str,
    response: Any,
) -> None:
    telemetry = dependencies.get("telemetry")
    if not telemetry or not response.was_fallback:
        return
    telemetry.log_fallback(
        workflow_id,
        step_name,
        response.fallback_from or "unknown",
        response.model_used,
        response.fallback_error or "provider fallback",
    )

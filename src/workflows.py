from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .approval import ApprovalGate
from .context_selector import ContextItem, ContextSelector, SelectionResult, estimate_tokens
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
        context_ledger: Any | None = None,
    ):
        self.store = store
        self.router = router or ModelRouter()
        self.selector = selector or ContextSelector()
        self.approval_gate = approval_gate or ApprovalGate(store)
        self.policy = policy or default_policy()
        self.data_dir = data_dir
        self.context_ledger = context_ledger

    def dependencies(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "router": self.router,
            "selector": self.selector,
            "approval_gate": self.approval_gate,
            "policy": self.policy,
            "data_dir": self.data_dir,
            "context_ledger": self.context_ledger,
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
        ledger = dependencies.get("context_ledger")
        if ledger is not None:
            artifact = ledger.record_artifact(
                state.workflow_id,
                artifact_role="source_artifact",
                source=incoming["id"],
                source_type="incoming_email",
                content=json.dumps(incoming, sort_keys=True),
                content_ref=f"mock_emails:{incoming['id']}",
                token_count=estimate_tokens(f"{incoming['subject']} {incoming['body']}"),
                metadata={"thread_id": incoming.get("thread_id")},
            )
            ledger.record_event(
                state.workflow_id,
                "ingest_email",
                artifact.artifact_id,
                "observed",
                reason="incoming email loaded",
            )
            _log_context_event(
                dependencies,
                "context_artifact_observed",
                state.workflow_id,
                "ingest_email",
                artifact.artifact_id,
            )
            incoming = incoming | {"context_artifact_id": artifact.artifact_id}
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
        selection_result: SelectionResult = self.selector.select(query, corpus, token_budget=300)
        selected_items = selection_result.selected_items
        selected_payloads = [item.__dict__ for item in selected_items]
        ledger = dependencies.get("context_ledger")
        if ledger is not None:
            # First, record all retrieved artifacts
            retrieved_artifact_ids: dict[str, str] = {}
            for candidate, _ in selection_result.selected:
                source_type = _ledger_source_type(candidate.item.source_type)
                artifact = ledger.record_artifact(
                    state.workflow_id,
                    artifact_role="source_artifact",
                    source=candidate.item.id,
                    source_type=source_type,
                    content=candidate.item.content,
                    content_ref=_content_ref(candidate.item),
                    token_count=candidate.item.token_count,
                    metadata={"timestamp": candidate.item.timestamp},
                )
                retrieved_artifact_ids[candidate.item.id] = artifact.artifact_id
                # Record retrieved event with score and rank
                ledger.record_event(
                    state.workflow_id,
                    "select_context",
                    artifact.artifact_id,
                    "retrieved",
                    reason="retrieved by context selector",
                    metadata={
                        "retrieval_method": selection_result.retrieval_method,
                        "retrieval_score": candidate.score,
                        "rank_position": candidate.rank,
                    },
                )
            for candidate, rejection_reason in selection_result.rejected:
                source_type = _ledger_source_type(candidate.item.source_type)
                artifact = ledger.record_artifact(
                    state.workflow_id,
                    artifact_role="source_artifact",
                    source=candidate.item.id,
                    source_type=source_type,
                    content=candidate.item.content,
                    content_ref=_content_ref(candidate.item),
                    token_count=candidate.item.token_count,
                    metadata={"timestamp": candidate.item.timestamp},
                )
                retrieved_artifact_ids[candidate.item.id] = artifact.artifact_id
                # Record retrieved event first
                ledger.record_event(
                    state.workflow_id,
                    "select_context",
                    artifact.artifact_id,
                    "retrieved",
                    reason="retrieved by context selector",
                    metadata={
                        "retrieval_method": selection_result.retrieval_method,
                        "retrieval_score": candidate.score,
                        "rank_position": candidate.rank,
                    },
                )
                # Then record rejected event
                ledger.record_event(
                    state.workflow_id,
                    "select_context",
                    artifact.artifact_id,
                    "rejected",
                    reason=f"not selected: {rejection_reason}",
                    metadata={
                        "rejection_reason": rejection_reason,
                        "retrieval_score": candidate.score,
                        "rank_position": candidate.rank,
                    },
                )
            # Now record selected events for selected items
            for budget_position, (candidate, _) in enumerate(selection_result.selected):
                artifact_id = retrieved_artifact_ids[candidate.item.id]
                ledger.record_event(
                    state.workflow_id,
                    "select_context",
                    artifact_id,
                    "selected",
                    reason="selected by context selector",
                    metadata={"source_item_id": candidate.item.id, "budget_position": budget_position},
                )
                _log_context_event(
                    dependencies,
                    "context_selected",
                    state.workflow_id,
                    "select_context",
                    artifact_id,
                )
                selected_payloads[budget_position]["artifact_id"] = artifact_id
        return StepResult(
            "select_context",
            {
                "context": selected_payloads,
                "token_count": sum(item.token_count for item in selected_items),
                "assembly_summary": {
                    "retrieved_count": selection_result.retrieved_count,
                    "selected_count": len(selection_result.selected),
                    "rejected_count": len(selection_result.rejected),
                },
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
        ledger = dependencies.get("context_ledger")
        prompt_payload: dict[str, Any] = {"email": email, "context": context}
        if ledger is not None:
            mounted_artifact_ids = _mounted_artifact_ids(email, context)
            prompt_payload["context_artifact_ids"] = mounted_artifact_ids
            _record_consumed(dependencies, state.workflow_id, "triage_llm", mounted_artifact_ids)
        prompt = json.dumps(prompt_payload, sort_keys=True)
        response = self.router.route(
            prompt=prompt,
            system="Classify this inbox item for triage as action_required, informational, or fyi.",
            policy=self.policy,
        )
        _log_fallback_if_needed(dependencies, state.workflow_id, "triage_llm", response)
        structured_response = _parse_model_json(response.content)
        if structured_response is not None:
            classification = str(structured_response.get("classification", "")).lower()
        else:
            classification = response.content.strip().split()[0].lower()
        if classification not in {"action_required", "informational", "fyi"}:
            classification = "action_required"
        if ledger is not None:
            _record_model_context(
                dependencies,
                state.workflow_id,
                "triage_llm",
                prompt,
                response,
                structured_response,
                mounted_artifact_ids,
            )
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
        context = step_data["select_context"]["context"][:5]
        ledger = dependencies.get("context_ledger")
        prompt_payload: dict[str, Any] = {"email": email}
        if ledger is not None:
            mounted_artifact_ids = _mounted_artifact_ids(email, context)
            prompt_payload["context"] = context
            prompt_payload["context_artifact_ids"] = mounted_artifact_ids
            _record_consumed(dependencies, state.workflow_id, "draft_reply", mounted_artifact_ids)
        else:
            mounted_artifact_ids = []
        response = self.router.route(
            prompt=json.dumps(prompt_payload, sort_keys=True),
            system="Draft a concise, helpful reply in the user's voice.",
            policy=self.policy,
        )
        _log_fallback_if_needed(dependencies, state.workflow_id, "draft_reply", response)
        structured_response = _parse_model_json(response.content)
        draft = (
            str(structured_response.get("draft"))
            if structured_response is not None and structured_response.get("draft") is not None
            else response.content
        )
        if ledger is not None:
            _record_model_context(
                dependencies,
                state.workflow_id,
                "draft_reply",
                json.dumps(prompt_payload, sort_keys=True),
                response,
                structured_response,
                mounted_artifact_ids,
            )
        return StepResult(
            "draft_reply",
            {"draft": draft, "skipped": False},
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


def _ledger_source_type(source_type: str) -> str:
    if source_type == "email":
        return "prior_email"
    if source_type == "calendar":
        return "calendar_event"
    return source_type


def _content_ref(item: ContextItem) -> str:
    prefix = "mock_calendar" if item.source_type == "calendar" else "mock_emails"
    return f"{prefix}:{item.id}"


def _mounted_artifact_ids(email: dict[str, Any], context: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    incoming_id = email.get("context_artifact_id")
    if isinstance(incoming_id, str):
        ids.append(incoming_id)
    for item in context:
        artifact_id = item.get("artifact_id")
        if isinstance(artifact_id, str):
            ids.append(artifact_id)
    return ids


def _record_consumed(
    dependencies: dict[str, Any],
    workflow_id: str,
    step_name: str,
    artifact_ids: list[str],
) -> None:
    ledger = dependencies.get("context_ledger")
    for artifact_id in artifact_ids:
        ledger.record_event(
            workflow_id,
            step_name,
            artifact_id,
            "consumed",
            reason="mounted into model prompt",
        )
        _log_context_event(dependencies, "context_consumed", workflow_id, step_name, artifact_id)


def _record_model_context(
    dependencies: dict[str, Any],
    workflow_id: str,
    step_name: str,
    prompt: str,
    response: Any,
    structured_response: dict[str, Any] | None,
    mounted_artifact_ids: list[str],
) -> None:
    ledger = dependencies.get("context_ledger")
    prompt_artifact = ledger.record_artifact(
        workflow_id,
        artifact_role="prompt_artifact",
        source=f"{step_name}:prompt",
        source_type="prompt",
        content=prompt,
        content_ref=f"workflow:{workflow_id}:{step_name}:prompt",
        token_count=response.input_tokens,
        metadata={},
    )
    response_artifact = ledger.record_artifact(
        workflow_id,
        artifact_role="response_artifact",
        source=f"{step_name}:response",
        source_type="model_response",
        content=response.content,
        content_ref=f"workflow:{workflow_id}:{step_name}:response",
        token_count=response.output_tokens,
        metadata={},
    )
    ledger.record_event(workflow_id, step_name, prompt_artifact.artifact_id, "consumed")
    ledger.record_event(workflow_id, step_name, response_artifact.artifact_id, "observed")
    decision = ledger.record_decision(
        workflow_id,
        step_name,
        step_result_id=None,
        prompt=prompt,
        response=response.content,
        model_used=response.model_used,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )
    _log_context_event(
        dependencies,
        "context_decision_recorded",
        workflow_id,
        step_name,
        decision_id=decision.decision_id,
    )
    influential_ids = _explicit_influential_ids(structured_response, mounted_artifact_ids)
    for artifact_id in influential_ids:
        ledger.record_lineage(
            decision.decision_id,
            artifact_id,
            _influence_type(structured_response),
            1.0,
            evidence_ref=f"model_response:{decision.response_digest}:influential_artifact_ids",
        )
        _log_context_event(
            dependencies,
            "context_lineage_recorded",
            workflow_id,
            step_name,
            artifact_id,
            decision.decision_id,
        )


def _parse_model_json(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _explicit_influential_ids(
    structured_response: dict[str, Any] | None,
    mounted_artifact_ids: list[str],
) -> list[str]:
    if structured_response is None:
        return []
    raw_ids = structured_response.get("influential_artifact_ids")
    if not isinstance(raw_ids, list):
        return []
    mounted = set(mounted_artifact_ids)
    return [
        artifact_id
        for artifact_id in raw_ids
        if isinstance(artifact_id, str) and artifact_id in mounted
    ]


def _influence_type(structured_response: dict[str, Any] | None) -> str:
    if structured_response is None:
        return "explicit_model_attribution"
    attribution_mode = structured_response.get("attribution_mode")
    if attribution_mode == "deterministic_fixture":
        return "deterministic_fixture_attribution"
    return "explicit_model_attribution"


def _log_context_event(
    dependencies: dict[str, Any],
    event_type: str,
    workflow_id: str,
    step_name: str,
    artifact_id: str | None = None,
    decision_id: str | None = None,
) -> None:
    telemetry = dependencies.get("telemetry")
    if telemetry is None:
        return
    metadata: dict[str, Any] = {}
    if artifact_id is not None:
        metadata["artifact_id"] = artifact_id
    if decision_id is not None:
        metadata["decision_id"] = decision_id
    telemetry.log_event(event_type, workflow_id, step_name, metadata=metadata)

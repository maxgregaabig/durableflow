"""Optional Aegis Gateway client for DurableFlow.

Core (`src/`) stays stdlib-only and does not import this package. Consequential
paths must not switch to it until an Aegis process can reach a verified
terminal result — otherwise a workflow sits in WAITING_EXTERNAL_ACTION with
nothing to read.

This module implements the caller protocol in
`proposals/drae-dflow-workplan.md` §5.2.3: submit under a stable
`caller_request_key`, recover the same `action_id` on replay, map public
terminal states, and refuse a receipt that does not bind this workflow.
"""

from __future__ import annotations

import json
import hashlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from src.engine import WaitForExternalAction
from src.store import ExternalActionIntent, StepResult, WorkflowState, WorkflowStore, utc_now


PUBLIC_TERMINALS = frozenset({"CONFIRMED", "DENIED", "FAILED", "CANCELLED", "UNRESOLVED"})


class GatewayError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"gateway HTTP {status}: {body}")
        self.status = status
        self.body = body


class GatewayUnavailable(RuntimeError):
    """Transport ambiguity; resume repeats only the durable request key."""


class ReceiptVerificationError(RuntimeError):
    """A receipt that must not complete a DurableFlow workflow."""


@dataclass(frozen=True)
class ActionView:
    action_id: str
    state: str
    caller_request_key: str
    caller_execution_ref: str
    terminal: bool


@dataclass(frozen=True)
class TerminalMapping:
    """One place maps Aegis public terminals onto DurableFlow step outcomes."""

    complete: bool
    success: bool
    reason: str


def map_terminal(state: str) -> TerminalMapping:
    if state == "CONFIRMED":
        return TerminalMapping(complete=True, success=True, reason="")
    if state in {"DENIED", "FAILED", "CANCELLED"}:
        return TerminalMapping(complete=True, success=False, reason=state)
    if state == "UNRESOLVED":
        return TerminalMapping(complete=False, success=False, reason="UNRESOLVED")
    return TerminalMapping(complete=False, success=False, reason=state)


class GatewayClient:
    def __init__(self, base_url: str, token: str, timeout_s: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s

    def submit(self, envelope: Mapping[str, Any]) -> ActionView:
        status, payload = self._request("POST", "/actions", envelope)
        if status not in {200, 201}:
            raise GatewayError(status, json.dumps(payload))
        return _action(payload)

    def get(self, action_id: str) -> ActionView:
        status, payload = self._request("GET", f"/actions/{action_id}")
        if status != 200:
            raise GatewayError(status, json.dumps(payload))
        return _action(payload)

    def receipt(self, action_id: str) -> dict[str, Any]:
        status, payload = self._request("GET", f"/actions/{action_id}/receipt")
        if status != 200:
            raise GatewayError(status, json.dumps(payload))
        if not isinstance(payload, dict):
            raise GatewayError(status, "receipt was not an object")
        return payload

    def events(self, action_id: str) -> list[dict[str, str]]:
        status, payload = self._request("GET", f"/actions/{action_id}/events")
        if status != 200:
            raise GatewayError(status, json.dumps(payload))
        if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
            raise GatewayError(status, "events response was not an object with an events list")
        out: list[dict[str, str]] = []
        for item in payload["events"]:
            if not isinstance(item, dict):
                raise GatewayError(status, "events list contained a non-object")
            out.append(
                {
                    "from_state": str(item.get("from_state") or ""),
                    "to_state": str(item.get("to_state") or ""),
                    "actor": str(item.get("actor") or ""),
                }
            )
        return out

    def verify_receipt(
        self,
        receipt: Mapping[str, Any],
        *,
        action_id: str,
        execution_ref: str,
        request_key: str,
    ) -> dict[str, Any]:
        if receipt.get("action_id") != action_id:
            raise ReceiptVerificationError("receipt action_id does not match the submitted action")
        if receipt.get("caller_execution_ref") != execution_ref:
            raise ReceiptVerificationError("receipt caller_execution_ref does not match this workflow")
        if receipt.get("caller_request_key") != request_key:
            raise ReceiptVerificationError("receipt caller_request_key does not match this step")
        state = str(receipt.get("state") or "")
        if state not in PUBLIC_TERMINALS:
            raise ReceiptVerificationError(f"receipt state {state!r} is not a public terminal")
        if state == "CONFIRMED" and not (receipt.get("receipt") or {}).get("observed_world_digest"):
            raise ReceiptVerificationError("confirmed receipt is missing observed_world_digest")
        return dict(receipt)

    def bundle(
        self,
        *,
        execution_ref: str,
        request_key: str,
        action: ActionView,
        events: list[Mapping[str, str]],
        receipt: Mapping[str, Any] | None,
        workflow_complete: bool,
    ) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": "1.0",
            "caller": {
                "execution_ref": execution_ref,
                "request_key": request_key,
                "workflow_complete": workflow_complete,
            },
            "action": {
                "action_id": action.action_id,
                "state": action.state,
                "caller_execution_ref": action.caller_execution_ref,
                "caller_request_key": action.caller_request_key,
            },
            "events": list(events),
        }
        if receipt is not None:
            # Preserve every field, including Aegis's optional signature. The
            # verifier must receive the Gateway response, not a locally
            # reconstructed subset of it.
            out["receipt"] = dict(receipt)
        return out

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
        )
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                payload: Any = json.loads(raw) if raw else {}
                return resp.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {"reason": raw}
            return exc.code, payload
        except urllib.error.URLError as exc:
            raise GatewayUnavailable(str(exc.reason)) from exc

    def run_action(
        self, store: WorkflowStore, state: WorkflowState, step_name: str, envelope: Mapping[str, Any] | None = None
    ) -> StepResult | WaitForExternalAction:
        """Submit/recover/poll exactly one immutable request intent.

        The local record never stores a remote receipt or resolves ambiguity; it
        only ensures that recovery resends the exact same request key and bytes.
        """
        intent = store.get_external_action_intent(state.workflow_id, step_name)
        if intent is None:
            if envelope is None:
                raise ValueError("an external action needs an envelope on its first attempt")
            encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
            key = str(envelope["caller_request_key"])
            fingerprint = "sha256:" + hashlib.sha256(encoded.encode()).hexdigest()
            intent = store.record_external_action_intent(ExternalActionIntent(
                workflow_id=state.workflow_id, step_name=step_name, caller_request_key=key,
                action_fingerprint=fingerprint, canonical_envelope=encoded,
                canonicalization_version=str(envelope.get("canonicalization_version", "")),
                definition_hash="", action_id=None, status="intent_recorded", created_at=utc_now(),
            ), state.current_step + 1)
        key = intent.caller_request_key
        if intent.action_id is None:
            try:
                action = self.submit(json.loads(intent.canonical_envelope))
            except GatewayUnavailable:
                return WaitForExternalAction(step_name)
            if action.caller_request_key != key or action.caller_execution_ref != state.workflow_id:
                raise ReceiptVerificationError("Aegis action does not bind this request intent")
            store.mark_external_action_submitted(state.workflow_id, step_name, action.action_id)
            intent = store.get_external_action_intent(state.workflow_id, step_name) or intent
        try:
            action = self.get(intent.action_id or "")
        except GatewayUnavailable:
            return WaitForExternalAction(step_name)
        if not action.terminal:
            return WaitForExternalAction(step_name)
        try:
            receipt = self.verify_receipt(self.receipt(action.action_id), action_id=action.action_id, execution_ref=state.workflow_id, request_key=key)
        except GatewayUnavailable:
            return WaitForExternalAction(step_name)
        mapped = map_terminal(str(receipt["state"]))
        if not mapped.complete:
            return WaitForExternalAction(step_name)
        store.mark_external_action_terminal_read(state.workflow_id, step_name)
        return StepResult(step_name, {"aegis_action_id": action.action_id, "aegis_state": receipt["state"], "success": mapped.success, "reason": mapped.reason}, 0.0)


def _action(payload: Any) -> ActionView:
    if not isinstance(payload, dict):
        raise GatewayError(500, "action response was not an object")
    return ActionView(
        action_id=str(payload.get("action_id") or ""),
        state=str(payload.get("state") or ""),
        caller_request_key=str(payload.get("caller_request_key") or ""),
        caller_execution_ref=str(payload.get("caller_execution_ref") or ""),
        terminal=bool(payload.get("terminal")),
    )

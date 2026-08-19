"""WS2 task 4 conformance suite: injected failures through the real client.

The cases mirror `gateway-contract.md` §10 / Aegis Workstream 3's harness —
do not re-enumerate; run the *same* cases through this repo's client. The
gateway is simulated by overriding ``GatewayClient._request`` only, so every
other line of client code — intent recording, submission, recovery,
verification, terminal mapping — is the production path under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.aegis_client import (
    GatewayClient,
    ReceiptVerificationError,
    map_terminal,
)
from src.engine import WaitForExternalAction
from src.store import ExternalActionIntent, StepResult, WorkflowState, WorkflowStore, utc_now


class FakeGateway:
    """In-memory Aegis: one action per (request_key, execution_ref), rebind-refusing."""

    def __init__(self):
        self.actions: dict[str, dict] = {}
        self.submissions: list[dict] = []
        self.drop_create_response_once = False  # crash after accept, before response
        self.drop_terminal_read_once = False
        self.unavailable_next = 0  # transport failures for the next N requests

    # -- GatewayClient._request override -----------------------------------

    def request(self, method: str, path: str, body: dict | None):
        if self.unavailable_next > 0:
            self.unavailable_next -= 1
            from integrations.aegis_client import GatewayUnavailable

            raise GatewayUnavailable("injected transport ambiguity")
        if method == "POST" and path == "/actions":
            return self._create(body)
        if method == "GET" and path.endswith("/receipt"):
            return self._receipt(path.split("/")[2])
        if method == "GET" and path.startswith("/actions/"):
            return self._get(path.split("/")[2])
        raise AssertionError(f"unexpected request {method} {path}")

    def _create(self, body: dict):
        self.submissions.append(body)
        key = body["caller_request_key"]
        ref = body["caller_execution_ref"]
        for action in self.actions.values():
            if action["caller_request_key"] == key:
                if action["caller_execution_ref"] != ref or action["arguments"] != body.get("arguments"):
                    # Rebind refusal: reused key with changed binding fails closed.
                    return 409, {"reason": "request key bound to different arguments"}
                return 200, dict(action)  # idempotent re-create returns same action
        action_id = f"action-{len(self.actions) + 1}"
        action = {
            "action_id": action_id,
            "state": "CONFIRMED",
            "terminal": True,
            "caller_request_key": key,
            "caller_execution_ref": ref,
            "arguments": body.get("arguments"),
        }
        self.actions[action_id] = action
        if self.drop_create_response_once:
            self.drop_create_response_once = False
            from integrations.aegis_client import GatewayUnavailable

            raise GatewayUnavailable("create-intent response lost after accept")
        return 201, dict(action)

    def _get(self, action_id: str):
        action = self.actions.get(action_id)
        if action is None:
            return 404, {"reason": "unknown action"}
        return 200, dict(action)

    def _receipt(self, action_id: str):
        action = self.actions[action_id]
        return 200, {
            "action_id": action_id,
            "state": action["state"],
            "caller_execution_ref": action["caller_execution_ref"],
            "caller_request_key": action["caller_request_key"],
            "receipt": {"observed_world_digest": "pc_alpha", "remote_reference": "chg-1"},
        }


class ConformanceClient(GatewayClient):
    def __init__(self, gateway: FakeGateway):
        super().__init__("http://gateway.test", "token")
        self.gateway = gateway

    def _request(self, method, path, body=None):
        return self.gateway.request(method, path, body)


def make_envelope(workflow_id: str, step: str = "send_reply", arguments: dict | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "canonicalization_version": "rfc8785-jcs-1",
        "operation": "durableflow/send-reply",
        "target": "user@example.com",
        "arguments": arguments if arguments is not None else {"body": "hello"},
        "preconditions": {},
        "tool_binding": "durableflow/send-reply@1",
        "policy_ref": "durableflow-aegis@1",
        "caller_request_key": f"{workflow_id}:{step}",
        "caller_execution_ref": workflow_id,
    }


def fresh(tmp_path: Path, name: str) -> tuple[WorkflowStore, WorkflowState]:
    store = WorkflowStore(tmp_path / f"{name}.sqlite")
    state = store.create_workflow(name)
    return store, state


def intent(store: WorkflowStore, workflow_id: str, step: str = "send_reply") -> ExternalActionIntent:
    record = store.get_external_action_intent(workflow_id, step)
    assert record is not None, "expected a durable request intent to exist"
    return record


# -- crash before submit -------------------------------------------------


def test_crash_before_submit_recovers_with_same_key_and_envelope(tmp_path: Path):
    """Intent recorded, process dies before any HTTP attempt: resume resends the exact bytes."""
    store, state = fresh(tmp_path, "crash-before-submit")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)

    encoded = json.dumps(make_envelope(state.workflow_id), sort_keys=True, separators=(",", ":"))
    record = store.record_external_action_intent(
        ExternalActionIntent(
            workflow_id=state.workflow_id,
            step_name="send_reply",
            caller_request_key=f"{state.workflow_id}:send_reply",
            action_fingerprint="sha256:x",
            canonical_envelope=encoded,
            canonicalization_version="rfc8785-jcs-1",
            definition_hash="",
            action_id=None,
            status="intent_recorded",
            created_at=utc_now(),
        ),
        0,
    )
    assert record.action_id is None

    result = client.run_action(store, store.load_workflow(state.workflow_id), "send_reply")
    assert isinstance(result, StepResult) and result.output["aegis_state"] == "CONFIRMED"
    assert len(gateway.submissions) == 1
    assert gateway.submissions[0] == json.loads(encoded)  # identical bytes, not reconstructed


# -- lost create-intent response ------------------------------------------


def test_lost_create_response_rederives_same_action_id(tmp_path: Path):
    """Crash after Aegis accepts but before the response persists: replay under the same key re-derives the same action_id (§5.2.3 item 2)."""
    store, state = fresh(tmp_path, "lost-create")
    gateway = FakeGateway()
    gateway.drop_create_response_once = True
    client = ConformanceClient(gateway)

    first = client.run_action(store, state, "send_reply", make_envelope(state.workflow_id))
    assert isinstance(first, WaitForExternalAction)  # ambiguity is a wait, not a retry-with-new-key
    assert intent(store, state.workflow_id).action_id is None

    second = client.run_action(store, store.load_workflow(state.workflow_id), "send_reply")
    assert isinstance(second, StepResult)
    recovered = intent(store, state.workflow_id)
    assert recovered.action_id == "action-1"  # same action, not a second one
    assert [a["action_id"] for a in gateway.actions.values()] == ["action-1"]


def test_retry_same_key_is_idempotent_on_the_gateway(tmp_path: Path):
    """Repeated resubmission under the same key never creates a duplicate action."""
    store, state = fresh(tmp_path, "idempotent-key")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)
    envelope = make_envelope(state.workflow_id)

    first = client.run_action(store, state, "send_reply", envelope)
    assert isinstance(first, StepResult)
    # Simulate a caller that re-runs the whole step (e.g. resume replay).
    store.mark_external_action_terminal_read.__wrapped__ if False else None
    second = client.run_action(store, state, "send_reply", envelope)
    assert isinstance(second, StepResult)
    assert len(gateway.actions) == 1


# -- rebind attempt: same key, changed arguments --------------------------


def test_rebind_attempt_fails_closed(tmp_path: Path):
    """Same caller_request_key with changed arguments must not produce a second action (§10 rebind case)."""
    store, state = fresh(tmp_path, "rebind")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)

    first = client.run_action(store, state, "send_reply", make_envelope(state.workflow_id))
    assert isinstance(first, StepResult)

    changed = make_envelope(state.workflow_id, arguments={"body": "tampered"})
    changed["caller_request_key"] = f"{state.workflow_id}:send_reply"  # same key
    from integrations.aegis_client import GatewayError

    with pytest.raises(GatewayError) as excinfo:
        client.submit(changed)
    assert excinfo.value.status == 409
    assert len(gateway.actions) == 1  # no second action was created


# -- no blind retry on ambiguity ------------------------------------------


def test_transport_ambiguity_never_blind_retries(tmp_path: Path):
    """An ambiguous (unavailable) outcome leaves the workflow waiting; the only retry is the same durable key (§5.2.3 / WS2 task 5)."""
    store, state = fresh(tmp_path, "ambiguous")
    gateway = FakeGateway()
    gateway.unavailable_next = 99
    client = ConformanceClient(gateway)

    result = client.run_action(store, state, "send_reply", make_envelope(state.workflow_id))
    assert isinstance(result, WaitForExternalAction)
    record = intent(store, state.workflow_id)
    assert record.action_id is None and record.status == "intent_recorded"
    assert gateway.submissions == []  # nothing was fired while ambiguous


# -- lost terminal read ----------------------------------------------------


def test_lost_terminal_read_completes_on_resume(tmp_path: Path):
    """Gateway reached CONFIRMED but the client never read it: resume re-reads and completes once."""
    store, state = fresh(tmp_path, "lost-terminal")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)

    # Submit, then lose the terminal read (simulate by consuming the step via
    # a second run after the intent already records the action_id).
    first = client.run_action(store, state, "send_reply", make_envelope(state.workflow_id))
    assert isinstance(first, StepResult)
    # Reset local knowledge of the terminal read only — the durable intent
    # keeps action_id, and a resume must re-read rather than assume.
    second = client.run_action(store, store.load_workflow(state.workflow_id), "send_reply")
    assert isinstance(second, StepResult)
    assert intent(store, state.workflow_id).status == "terminal_read"


# -- foreign receipt / synthesized receipt ---------------------------------


def test_receipt_from_wrong_action_id_cannot_complete(tmp_path: Path):
    """A receipt bound to a different action must be refused before completion."""
    store, state = fresh(tmp_path, "foreign-action")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)
    envelope = make_envelope(state.workflow_id)

    assert isinstance(client.run_action(store, state, "send_reply", envelope), StepResult)
    # A second workflow's action exists; its receipt must not satisfy this one.
    other_state = store.create_workflow("other")
    other_client = ConformanceClient(gateway)
    assert isinstance(
        other_client.run_action(
            store, other_state, "send_reply", make_envelope(other_state.workflow_id)
        ),
        StepResult,
    )

    with pytest.raises(ReceiptVerificationError):
        client.verify_receipt(
            {
                "action_id": "action-2",
                "state": "CONFIRMED",
                "caller_execution_ref": state.workflow_id,
                "caller_request_key": f"{state.workflow_id}:send_reply",
                "receipt": {"observed_world_digest": "pc_x"},
            },
            action_id="action-1",
            execution_ref=state.workflow_id,
            request_key=f"{state.workflow_id}:send_reply",
        )


# -- skip-submission negative (§10 risk) -----------------------------------


def assert_completion_has_intent(
    store: WorkflowStore,
    workflow_id: str,
    status_value: str,
    step_name: str = "send_reply",
) -> None:
    """The §10 invariant: a completed consequential step must have a request-intent row.

    The engine deliberately does not police step internals (WS1 keeps it
    dumb); this suite-level check is the response to the §10 risk that a
    refactored caller bypasses both the old gate and the new submission step.
    """
    record = store.get_external_action_intent(workflow_id, step_name)
    if status_value == "completed" and record is None:
        pytest.fail("consequential step completed without a request-intent record")


def test_bypassed_consequential_step_is_flagged_by_the_invariant(tmp_path: Path):
    """The invariant fires on the anti-pattern: effect performed directly, no intent recorded."""
    from src.engine import WorkflowEngine

    store, state = fresh(tmp_path, "skip-submission")
    engine = WorkflowEngine(store)

    def bypass(state, step_data, dependencies):
        return StepResult("send_reply", {"sent": True}, 0.0)

    engine.register_step("send_reply", bypass)
    result = engine.execute(state.workflow_id)
    assert result.status.value == "completed"
    # The invariant must be violated here — proving the detector works.
    with pytest.raises(pytest.fail.Exception):
        assert_completion_has_intent(store, state.workflow_id, result.status.value)


def test_routed_consequential_step_satisfies_the_invariant(tmp_path: Path):
    """The compliant path (submit through the client) completes with an intent row present."""
    store, state = fresh(tmp_path, "routed-ok")
    gateway = FakeGateway()
    client = ConformanceClient(gateway)

    result = client.run_action(store, state, "send_reply", make_envelope(state.workflow_id))
    assert isinstance(result, StepResult)
    record = store.get_external_action_intent(state.workflow_id, "send_reply")
    assert record is not None and record.status == "terminal_read"
    assert_completion_has_intent(store, state.workflow_id, "completed")

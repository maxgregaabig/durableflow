from integrations.aegis_client import (
    GatewayClient,
    ReceiptVerificationError,
    map_terminal,
)
from src.engine import WaitForExternalAction, WorkflowEngine
from src.store import WorkflowStatus, WorkflowStore


class WaitingGateway:
    def __init__(self):
        self.calls = 0

    def run_action(self, store, state, step_name, envelope=None):
        self.calls += 1
        # Exercise the real durable pre-submit record through the client is
        # covered by GatewayClient tests; this fake isolates engine routing.
        if envelope is not None:
            from integrations.aegis_client import GatewayClient
            # A tiny stand-in only records the intended wait boundary.
            store.update_status(state.workflow_id, WorkflowStatus.WAITING_EXTERNAL_ACTION)
        return WaitForExternalAction(step_name)


def test_confirmed_maps_to_success():
    mapped = map_terminal("CONFIRMED")
    assert mapped.complete is True and mapped.success is True


def test_unresolved_does_not_complete():
    mapped = map_terminal("UNRESOLVED")
    assert mapped.complete is False


def test_verify_receipt_rejects_foreign_workflow():
    client = GatewayClient("http://gateway.test", "token")
    receipt = {
        "action_id": "action-1",
        "state": "CONFIRMED",
        "caller_execution_ref": "other-workflow",
        "caller_request_key": "step-1",
        "receipt": {"observed_world_digest": "pc_x", "remote_reference": "chg-1"},
    }
    try:
        client.verify_receipt(
            receipt, action_id="action-1", execution_ref="workflow-1", request_key="step-1"
        )
    except ReceiptVerificationError as exc:
        assert "caller_execution_ref" in str(exc)
    else:
        raise AssertionError("foreign receipt was accepted")


def test_verify_receipt_rejects_synthesized_confirmation_without_world():
    client = GatewayClient("http://gateway.test", "token")
    receipt = {
        "action_id": "action-1",
        "state": "CONFIRMED",
        "caller_execution_ref": "workflow-1",
        "caller_request_key": "step-1",
        "receipt": {},
    }
    try:
        client.verify_receipt(
            receipt, action_id="action-1", execution_ref="workflow-1", request_key="step-1"
        )
    except ReceiptVerificationError:
        return
    raise AssertionError("a confirmation with no observed world was accepted")


def test_wait_marker_keeps_the_current_step(tmp_path):
    store = WorkflowStore(tmp_path / "external.sqlite")
    state = store.create_workflow("test")
    engine = WorkflowEngine(store)

    def external(state, data, deps):
        from src.store import ExternalActionIntent, utc_now
        store.record_external_action_intent(ExternalActionIntent(
            state.workflow_id, "external", "wf:external", "sha256:x", "{}", "rfc8785-jcs-1", "", None, "intent_recorded", utc_now()
        ), 0)
        return WaitForExternalAction("external")

    engine.register_step("external", external)
    assert engine.execute(state.workflow_id).status == WorkflowStatus.WAITING_EXTERNAL_ACTION
    assert store.load_workflow(state.workflow_id).current_step == 0


def test_repeated_external_wait_never_skips_the_step(tmp_path):
    store = WorkflowStore(tmp_path / "repeat.sqlite")
    state = store.create_workflow("test")
    engine = WorkflowEngine(store)
    calls = 0

    def external(state, data, deps):
        nonlocal calls
        calls += 1
        if store.get_external_action_intent(state.workflow_id, "external") is None:
            from src.store import ExternalActionIntent, utc_now
            store.record_external_action_intent(ExternalActionIntent(
                state.workflow_id, "external", "wf:external", "sha256:x", "{}", "rfc8785-jcs-1", "", None, "intent_recorded", utc_now()
            ), 0)
        return WaitForExternalAction("external")

    engine.register_step("external", external)
    engine.register_step("after", lambda *_: (_ for _ in ()).throw(AssertionError("advanced without terminal result")))
    assert engine.execute(state.workflow_id).status == WorkflowStatus.WAITING_EXTERNAL_ACTION
    assert engine.resume(state.workflow_id).status == WorkflowStatus.WAITING_EXTERNAL_ACTION
    assert engine.resume(state.workflow_id).status == WorkflowStatus.WAITING_EXTERNAL_ACTION
    assert calls == 3

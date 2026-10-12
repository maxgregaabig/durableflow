from __future__ import annotations

from context.ledger import ContextLedger
from context.measurement import (
    ContextEvalCase,
    evaluate_context_selection,
    measure_audit_completeness,
    render_measurement_report,
)
from src.context_selector import ContextItem
from src.store import WorkflowStore


def item(item_id: str, content: str, tokens: int = 10) -> ContextItem:
    return ContextItem(item_id, content, "email", "2026-06-17T00:00:00Z", tokens)


def test_context_measurement_reports_ranked_quality_budget_and_latency() -> None:
    case = ContextEvalCase(
        case_id="same-thread-follow-up",
        workflow_type="inbox_triage",
        step_name="select_context",
        query="sarah board deck feedback",
        corpus=[
            item("generic", "office lunch board games", tokens=5),
            item("deck", "sarah q3 board deck feedback", tokens=5),
            item("billing", "invoice payment receipt", tokens=5),
        ],
        token_budget=10,
        relevant_artifact_ids={"deck": 3},
        must_include_artifact_ids=frozenset({"deck"}),
        metadata={"scenario": "same_thread"},
    )

    run = evaluate_context_selection(
        [case],
        known_caveats=["fixture labels; local latency only"],
    )

    assert run.case_count == 1
    assert run.nDCG_at_5 == 1.0
    assert run.recall_at_10 == 1.0
    assert run.must_include_at_10 == 1.0
    assert run.budget_utilization == 1.0
    assert run.p95_latency_ms >= 0.0
    assert run.case_metrics[0].selected_count == 2


def test_context_measurement_tracks_budget_rejection_false_negatives() -> None:
    case = ContextEvalCase(
        case_id="budget-pressure",
        workflow_type="inbox_triage",
        step_name="select_context",
        query="approval board budget",
        corpus=[
            item("long", "approval board budget background " * 20, tokens=50),
            item("decisive", "approval board budget policy", tokens=10),
            item("other", "lunch menu", tokens=10),
        ],
        token_budget=10,
        relevant_artifact_ids={"long": 2, "decisive": 3},
    )

    metric = evaluate_context_selection([case]).case_metrics[0]

    assert metric.selected_token_count <= case.token_budget
    assert metric.rejection_false_negative_rate == 0.5
    assert metric.selected_relevant_rate == 1.0


def test_context_measurement_leaves_empty_label_metrics_undefined() -> None:
    case = ContextEvalCase(
        case_id="empty-or-low-context",
        workflow_type="inbox_triage",
        step_name="select_context",
        query="no real match",
        corpus=[item("noise", "lunch menu")],
        token_budget=20,
        relevant_artifact_ids=set(),
    )

    metric = evaluate_context_selection([case]).case_metrics[0]

    assert metric.nDCG_at_5 is None
    assert metric.recall_at_10 is None
    assert metric.rejection_false_negative_rate is None
    assert metric.budget_utilization > 0


def test_measurement_report_uses_ids_and_omits_raw_corpus_content() -> None:
    case = ContextEvalCase(
        case_id="privacy-check",
        workflow_type="inbox_triage",
        step_name="select_context",
        query="secret board deck",
        corpus=[item("secret-source", "sensitive raw board deck body")],
        token_budget=20,
        relevant_artifact_ids={"secret-source"},
    )

    report = render_measurement_report(evaluate_context_selection([case]))

    assert "privacy-check" in report
    assert "nDCG@5" in report
    assert "sensitive raw board deck body" not in report


def test_audit_completeness_measures_event_and_influence_coverage(tmp_path) -> None:
    store = WorkflowStore(tmp_path / "measurement.sqlite")
    state = store.create_workflow("test")
    ledger = ContextLedger.from_store(store)
    retrieved = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-001",
        "prior_email",
        "content",
        "mock_emails:email-001",
        5,
    )
    selected = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-002",
        "prior_email",
        "content two",
        "mock_emails:email-002",
        5,
    )
    missing = ledger.record_artifact(
        state.workflow_id,
        "source_artifact",
        "email-003",
        "prior_email",
        "content three",
        "mock_emails:email-003",
        5,
    )

    ledger.record_event(
        state.workflow_id,
        "select_context",
        retrieved.artifact_id,
        "retrieved",
        metadata={"retrieval_method": "bm25"},
    )
    ledger.record_event(
        state.workflow_id,
        "select_context",
        selected.artifact_id,
        "selected",
    )
    ledger.record_event(state.workflow_id, "triage_llm", selected.artifact_id, "consumed")
    decision = ledger.record_decision(
        state.workflow_id,
        "triage_llm",
        None,
        "prompt",
        '{"influential_artifact_ids": ["email-002"]}',
        "mock-fast",
        10,
        3,
        0.01,
    )
    ledger.record_lineage(
        decision.decision_id,
        selected.artifact_id,
        "deterministic_fixture_attribution",
        1.0,
    )

    metrics = measure_audit_completeness(
        ledger.audit_workflow(state.workflow_id),
        retrieved_artifact_ids=[retrieved.artifact_id, missing.artifact_id],
        selected_artifact_ids=[selected.artifact_id],
        consumed_artifact_ids=[selected.artifact_id, missing.artifact_id],
        expected_influential_artifact_ids=[selected.artifact_id],
    )

    assert metrics.retrieved_event_coverage == 0.5
    assert metrics.selected_event_coverage == 1.0
    assert metrics.consumed_event_coverage == 0.5
    assert metrics.influence_coverage == 1.0

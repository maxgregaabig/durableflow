from __future__ import annotations

import json

import pytest

from src.model_router import ModelProvider, ModelRouter, ModelRoutingError, RoutingPolicy


def test_primary_provider_succeeds() -> None:
    response = ModelRouter().route(
        "please classify this",
        "Classify",
        RoutingPolicy(
            [
                ModelProvider("primary", "p", 0.01, 0.02),
                ModelProvider("secondary", "s", 0.01, 0.02),
            ]
        ),
    )
    assert response.model_used == "p"
    assert response.was_fallback is False


def test_fallback_provider_succeeds() -> None:
    response = ModelRouter().route(
        "please classify this",
        "Classify",
        RoutingPolicy(
            [
                ModelProvider("primary", "p", 0.01, 0.02, fail=True),
                ModelProvider("secondary", "s", 0.01, 0.02),
            ]
        ),
    )
    assert response.model_used == "s"
    assert response.was_fallback is True
    assert response.fallback_from == "p"


def test_all_providers_fail() -> None:
    with pytest.raises(ModelRoutingError) as exc:
        ModelRouter().route(
            "prompt",
            "system",
            RoutingPolicy(
                [
                    ModelProvider("primary", "p", 0.01, 0.02, fail=True),
                    ModelProvider("secondary", "s", 0.01, 0.02, fail=True),
                ]
            ),
        )
    assert "primary" in exc.value.attempted_providers
    assert "secondary" in exc.value.attempted_providers


def test_cost_uses_token_pricing() -> None:
    provider = ModelProvider("primary", "p", 0.5, 1.0)
    response = ModelRouter().route("short prompt", "system", RoutingPolicy([provider]))
    assert response.cost_usd == response.input_tokens * 0.5 + response.output_tokens * 1.0


def test_timeout_falls_back_to_secondary_provider() -> None:
    response = ModelRouter().route(
        "please classify this",
        "Classify",
        RoutingPolicy(
            [
                ModelProvider(
                    "primary",
                    "p",
                    0.01,
                    0.02,
                    timeout_seconds=0.001,
                    mock_delay_seconds=0.01,
                ),
                ModelProvider("secondary", "s", 0.01, 0.02),
            ]
        ),
    )
    assert response.model_used == "s"
    assert response.was_fallback is True
    assert "timed out" in (response.fallback_error or "")


def test_context_fixture_attribution_is_deterministic() -> None:
    prompt = json.dumps(
        {
            "email": {"subject": "Need deck review", "body": "Please review"},
            "context": [
                {"id": "email-012", "artifact_id": "ctx-email-012"},
                {"id": "email-999", "artifact_id": "ctx-email-999"},
                {"id": "cal-001", "artifact_id": "ctx-cal-001"},
            ],
            "context_artifact_ids": ["ctx-email-012", "ctx-email-999", "ctx-cal-001"],
        },
        sort_keys=True,
    )

    response = ModelRouter().route(
        prompt,
        "Classify this inbox item for triage.",
        RoutingPolicy([ModelProvider("primary", "p", 0.01, 0.02)]),
    )
    payload = json.loads(response.content)

    assert payload["attribution_mode"] == "deterministic_fixture"
    assert payload["influential_artifact_ids"] == ["ctx-cal-001", "ctx-email-012"]

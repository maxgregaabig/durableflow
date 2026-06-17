from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelProvider:
    name: str
    model_id: str
    cost_per_input_token: float
    cost_per_output_token: float
    timeout_seconds: float = 30
    is_mock: bool = True
    fail: bool = False
    mock_delay_seconds: float = 0.0


@dataclass(frozen=True)
class RoutingPolicy:
    providers: list[ModelProvider]
    retry_count: int = 0
    fallback_on_timeout: bool = True
    fallback_on_error: bool = True


@dataclass(frozen=True)
class ModelResponse:
    content: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    was_fallback: bool
    fallback_from: str | None = None
    fallback_error: str | None = None


class ModelRoutingError(RuntimeError):
    def __init__(self, attempted_providers: list[str]):
        super().__init__(f"all model providers failed: {', '.join(attempted_providers)}")
        self.attempted_providers = attempted_providers


class ModelRouter:
    def route(self, prompt: str, system: str, policy: RoutingPolicy) -> ModelResponse:
        attempted: list[str] = []
        last_error: Exception | None = None
        fallback_from: str | None = None
        fallback_error: str | None = None
        for provider_index, provider in enumerate(policy.providers):
            attempts = policy.retry_count + 1
            for _ in range(attempts):
                attempted.append(provider.name)
                try:
                    response = self._call_provider(provider, prompt, system)
                    return ModelResponse(
                        content=response.content,
                        model_used=response.model_used,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        cost_usd=response.cost_usd,
                        latency_ms=response.latency_ms,
                        was_fallback=provider_index > 0,
                        fallback_from=fallback_from if provider_index > 0 else None,
                        fallback_error=fallback_error if provider_index > 0 else None,
                    )
                except TimeoutError as exc:
                    last_error = exc
                    fallback_from = provider.model_id
                    fallback_error = str(exc)
                    if not policy.fallback_on_timeout:
                        raise
                except Exception as exc:
                    last_error = exc
                    fallback_from = provider.model_id
                    fallback_error = str(exc)
                    if not policy.fallback_on_error:
                        raise
        if last_error:
            attempted.append(type(last_error).__name__)
        raise ModelRoutingError(attempted)

    def _call_provider(self, provider: ModelProvider, prompt: str, system: str) -> ModelResponse:
        started = time.perf_counter()
        if provider.fail:
            raise RuntimeError(f"{provider.name} configured to fail")
        if provider.is_mock:
            if provider.mock_delay_seconds > provider.timeout_seconds:
                time.sleep(max(provider.timeout_seconds, 0))
                raise TimeoutError(
                    f"{provider.name} timed out after {provider.timeout_seconds} seconds"
                )
            if provider.mock_delay_seconds > 0:
                time.sleep(provider.mock_delay_seconds)
            content = self._mock_response(prompt, system)
        else:
            content = self._call_anthropic(provider, prompt, system)
        latency_ms = (time.perf_counter() - started) * 1000
        input_tokens = self._estimate_tokens(system + "\n" + prompt)
        output_tokens = self._estimate_tokens(content)
        cost_usd = self._estimate_cost(provider, input_tokens, output_tokens)
        return ModelResponse(
            content=content,
            model_used=provider.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            was_fallback=False,
        )

    def _call_anthropic(self, provider: ModelProvider, prompt: str, system: str) -> str:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is required for non-mock providers")
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("install optional dependency anthropic to use real providers") from exc
        client = anthropic.Anthropic(api_key=api_key, timeout=provider.timeout_seconds)
        message = client.messages.create(
            model=provider.model_id,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "\n".join(block.text for block in message.content if hasattr(block, "text"))

    def _mock_response(self, prompt: str, system: str) -> str:
        lowered = (system + "\n" + prompt).lower()
        if "classify" in lowered or "triage" in lowered:
            email_text = self._extract_email_text(prompt).lower()
            if any(
                word in email_text
                for word in ["need", "review", "approval", "reply", "feedback", "please"]
            ):
                return "action_required"
            return "informational"
        if "draft" in lowered:
            return (
                "Hi Sarah,\n\nThanks for sending this over. I can review the deck today "
                "and send concise feedback before Thursday.\n\nBest,\nMarcos"
            )
        return "acknowledged"

    def _extract_email_text(self, prompt: str) -> str:
        try:
            payload = json.loads(prompt)
        except json.JSONDecodeError:
            return prompt
        email = payload.get("email")
        if not isinstance(email, dict):
            return prompt
        return f"{email.get('subject', '')} {email.get('body', '')}"

    def _estimate_tokens(self, text: str) -> int:
        return max(1, int(len(text.split()) / 0.75))

    def _estimate_cost(
        self,
        provider: ModelProvider,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        return round(
            input_tokens * provider.cost_per_input_token
            + output_tokens * provider.cost_per_output_token,
            8,
        )


def default_policy(fail_primary: bool = False) -> RoutingPolicy:
    return RoutingPolicy(
        providers=[
            ModelProvider(
                name="mock-primary",
                model_id="mock-fast",
                cost_per_input_token=0.0000005,
                cost_per_output_token=0.0000015,
                timeout_seconds=1,
                fail=fail_primary,
            ),
            ModelProvider(
                name="mock-secondary",
                model_id="mock-reliable",
                cost_per_input_token=0.000001,
                cost_per_output_token=0.000002,
                timeout_seconds=1,
            ),
        ],
        retry_count=0,
    )

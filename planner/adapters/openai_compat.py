from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RawResponse:
    content: str
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    raw: dict[str, Any] | None = None


class OpenAICompatAdapter:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def invoke(self, step, request: Mapping[str, Any]) -> RawResponse:
        if self.base_url is None:
            return self._mock_response(step, request)
        started = time.perf_counter()
        body = dict(request) | {"model": step.model_id}
        payload = json.dumps(body).encode()
        http_request = urllib.request.Request(
            self.base_url.rstrip("/") + "/v1/chat/completions",
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        with urllib.request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            parsed = json.loads(response.read().decode())
        content = _extract_content(parsed)
        latency_ms = int((time.perf_counter() - started) * 1000.0)
        usage = parsed.get("usage") if isinstance(parsed, dict) else {}
        input_tokens = int((usage or {}).get("prompt_tokens") or _estimate_tokens(str(request)))
        output_tokens = int((usage or {}).get("completion_tokens") or _estimate_tokens(content))
        return RawResponse(
            content=content,
            model_used=step.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_cost(step, input_tokens, output_tokens),
            latency_ms=latency_ms,
            raw=parsed,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        return headers

    def _mock_response(self, step, request: Mapping[str, Any]) -> RawResponse:
        started = time.perf_counter()
        content = _mock_content(request)
        input_tokens = _estimate_tokens(str(request))
        output_tokens = _estimate_tokens(content)
        return RawResponse(
            content=content,
            model_used=step.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_cost(step, input_tokens, output_tokens),
            latency_ms=max(1, int((time.perf_counter() - started) * 1000.0)),
            raw={"mock": True},
        )


def _extract_content(parsed: dict[str, Any]) -> str:
    choices = parsed.get("choices") if isinstance(parsed, dict) else None
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            return message["content"]
        if isinstance(choices[0].get("text"), str):
            return choices[0]["text"]
    return json.dumps(parsed, sort_keys=True)


def _mock_content(request: Mapping[str, Any]) -> str:
    if isinstance(request.get("response_format"), Mapping):
        response_type = request["response_format"].get("type")
        if response_type in {"json_object", "json_schema"}:
            return '{"ok": true}'
    if isinstance(request.get("output_check"), Mapping):
        return '{"ok": true}'
    return "acknowledged"


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text.split()) / 0.75))


def _cost(step, input_tokens: int, output_tokens: int) -> float:
    return round(float(step.estimate.cost_usd), 8)

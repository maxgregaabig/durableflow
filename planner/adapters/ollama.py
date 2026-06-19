from __future__ import annotations

from typing import Any, Mapping

from .openai_compat import OpenAICompatAdapter, RawResponse


class OllamaAdapter(OpenAICompatAdapter):
    def __init__(self, base_url: str | None = None, timeout_seconds: float = 30.0) -> None:
        super().__init__(base_url=base_url, api_key=None, timeout_seconds=timeout_seconds)

    def invoke(self, step, request: Mapping[str, Any]) -> RawResponse:
        return super().invoke(step, request)

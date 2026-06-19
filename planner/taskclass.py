from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Mapping

from .constraints import OutputCheck


TASK_CLASS_TAXONOMY_VERSION = 1


class TaskClass(StrEnum):
    CHAT = "chat"
    CODE = "code"
    JSON_EXTRACTION = "json_extraction"
    SUMMARIZATION = "summarization"
    OTHER = "other"


def derive_task_class(request: Mapping[str, Any]) -> TaskClass:
    output_check = request.get("output_check")
    if isinstance(output_check, OutputCheck) and output_check.verifies_json():
        return TaskClass.JSON_EXTRACTION
    if isinstance(output_check, Mapping) and (
        "json_schema" in output_check or output_check.get("kind") in {"json", "json_schema"}
    ):
        return TaskClass.JSON_EXTRACTION
    response_format = request.get("response_format")
    if isinstance(response_format, Mapping) and response_format.get("type") in {
        "json_object",
        "json_schema",
    }:
        return TaskClass.JSON_EXTRACTION

    text = _request_text(request)
    if text is None:
        return TaskClass.OTHER
    lowered = text.lower()
    if "```" in text or any(marker in lowered for marker in _CODE_MARKERS):
        return TaskClass.CODE
    if any(marker in lowered for marker in _SUMMARIZE_MARKERS):
        return TaskClass.SUMMARIZATION
    return TaskClass.CHAT


_CODE_MARKERS = {
    "write code",
    "fix this code",
    "implement",
    "function",
    "class ",
    "stack trace",
    "typescript",
    "python",
}

_SUMMARIZE_MARKERS = {
    "summarize",
    "summary of",
    "tl;dr",
    "tldr",
    "condense",
}


def _request_text(request: Mapping[str, Any]) -> str | None:
    messages = request.get("messages")
    if isinstance(messages, list):
        parts: list[str] = []
        for message in messages:
            if not isinstance(message, Mapping):
                return None
            content = message.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                        parts.append(block["text"])
                    else:
                        return None
            else:
                return None
        return "\n".join(parts)
    prompt = request.get("prompt")
    if isinstance(prompt, str):
        return prompt
    try:
        return json.dumps(request, sort_keys=True)
    except TypeError:
        return None

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections import OrderedDict
from typing import Any, Mapping

from .constraints import ExecutionConstraints


class PlanCache:
    def __init__(self, ttl_seconds: float = 30.0, max_entries: int = 256) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, task_signature: str, constraints: ExecutionConstraints):
        key = self._key(task_signature, constraints)
        entry = self._entries.get(key)
        if entry is None:
            return None
        created_at, plan = entry
        if time.monotonic() - created_at > self.ttl_seconds:
            self._entries.pop(key, None)
            return None
        self._entries.move_to_end(key)
        return copy.deepcopy(plan)

    def put(self, task_signature: str, constraints: ExecutionConstraints, plan) -> None:
        key = self._key(task_signature, constraints)
        self._entries[key] = (time.monotonic(), copy.deepcopy(plan))
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    @staticmethod
    def _key(task_signature: str, constraints: ExecutionConstraints) -> str:
        payload = json.dumps(
            {"task_signature": task_signature, "constraints": constraints.normalized()},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def task_signature(request: Mapping[str, Any]) -> str:
    payload = {
        "messages": request.get("messages"),
        "prompt": request.get("prompt"),
        "max_tokens": request.get("max_tokens"),
        "response_format": request.get("response_format"),
        "output_check": request.get("output_check"),
    }
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()

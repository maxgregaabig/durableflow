from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping


class Privacy(StrEnum):
    LOCAL_ONLY = "local-only"
    LOCAL_OR_VPC = "local-or-vpc"
    ANY = "any"


class Tier(StrEnum):
    NONE = "none"
    LOCAL = "local"
    ECONOMY = "economy"
    FRONTIER = "frontier"


class Objective(StrEnum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    MOST_CAPABLE = "most_capable"


@dataclass(frozen=True)
class OutputCheck:
    kind: str = "json"
    json_schema: dict[str, Any] | None = None

    def verifies_json(self) -> bool:
        return self.kind in {"json", "json_schema"} or self.json_schema is not None


@dataclass(frozen=True)
class ExecutionConstraints:
    max_cost_usd: float | None = None
    max_latency_ms: int | None = None
    privacy: Privacy = Privacy.ANY
    region: str | None = None
    tier_floor: Tier = Tier.NONE
    objective: Objective = Objective.CHEAPEST
    budget_id: str | None = None
    shadow: bool = False
    output_check: OutputCheck | None = None

    def normalized(self) -> dict[str, Any]:
        return {
            "max_cost_usd": self.max_cost_usd,
            "max_latency_ms": self.max_latency_ms,
            "privacy": self.privacy.value,
            "region": self.region,
            "tier_floor": self.tier_floor.value,
            "objective": self.objective.value,
            "budget_id": self.budget_id,
            "shadow": self.shadow,
            "output_check": output_check_to_dict(self.output_check),
        }


class ConstraintParseError(ValueError):
    def __init__(self, field: str, reason: str, status_code: int = 400) -> None:
        super().__init__(f"invalid {field}: {reason}")
        self.field = field
        self.reason = reason
        self.status_code = status_code

    def to_response(self) -> dict[str, Any]:
        return {"error": {"type": "invalid_constraints", "field": self.field, "reason": self.reason}}


class ConstraintParser:
    @staticmethod
    def should_plan(body: Mapping[str, Any]) -> bool:
        return str(body.get("model", "auto")) == "auto"

    @classmethod
    def parse(cls, headers: Mapping[str, str], body: Mapping[str, Any]) -> ExecutionConstraints:
        normalized_headers = {key.lower(): value for key, value in headers.items()}
        return ExecutionConstraints(
            max_cost_usd=cls._optional_float(normalized_headers, "x-max-cost"),
            max_latency_ms=cls._optional_int(normalized_headers, "x-max-latency"),
            privacy=cls._enum(
                normalized_headers,
                "x-privacy",
                Privacy,
                default=Privacy.ANY,
                aliases={"local_only": Privacy.LOCAL_ONLY, "local-only": Privacy.LOCAL_ONLY},
            ),
            region=cls._optional_str(normalized_headers, "x-region"),
            tier_floor=cls._enum(
                normalized_headers,
                "x-tier-floor",
                Tier,
                default=Tier.NONE,
                aliases={"": Tier.NONE, "none": Tier.NONE},
                allowed={Tier.NONE, Tier.ECONOMY, Tier.FRONTIER},
            ),
            objective=cls._enum(
                normalized_headers,
                "x-objective",
                Objective,
                default=Objective.CHEAPEST,
            ),
            budget_id=cls._optional_str(normalized_headers, "x-budget-id"),
            shadow=cls._optional_bool(normalized_headers, "x-shadow"),
            output_check=cls._parse_output_check(body),
        )

    @staticmethod
    def _optional_str(headers: Mapping[str, str], key: str) -> str | None:
        value = headers.get(key)
        if value is None or str(value).strip() == "":
            return None
        return str(value).strip()

    @staticmethod
    def _optional_float(headers: Mapping[str, str], key: str) -> float | None:
        value = headers.get(key)
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = float(value)
        except ValueError as exc:
            raise ConstraintParseError(key, "must be a number") from exc
        if parsed < 0:
            raise ConstraintParseError(key, "must be non-negative")
        return parsed

    @staticmethod
    def _optional_int(headers: Mapping[str, str], key: str) -> int | None:
        value = headers.get(key)
        if value is None or str(value).strip() == "":
            return None
        try:
            parsed = int(value)
        except ValueError as exc:
            raise ConstraintParseError(key, "must be an integer number of milliseconds") from exc
        if parsed < 0:
            raise ConstraintParseError(key, "must be non-negative")
        return parsed

    @staticmethod
    def _optional_bool(headers: Mapping[str, str], key: str) -> bool:
        value = headers.get(key)
        if value is None:
            return False
        lowered = str(value).strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        raise ConstraintParseError(key, "must be a boolean")

    @staticmethod
    def _enum(
        headers: Mapping[str, str],
        key: str,
        enum_cls: type[Privacy] | type[Tier] | type[Objective],
        *,
        default: Any,
        aliases: Mapping[str, Any] | None = None,
        allowed: set[Any] | None = None,
    ) -> Any:
        raw = headers.get(key)
        if raw is None:
            return default
        normalized = str(raw).strip().lower().replace("_", "-")
        alias_map = aliases or {}
        if normalized in alias_map:
            value = alias_map[normalized]
        else:
            try:
                value = enum_cls(normalized)
            except ValueError as exc:
                expected = ", ".join(item.value for item in enum_cls)
                raise ConstraintParseError(key, f"must be one of: {expected}") from exc
        if allowed is not None and value not in allowed:
            expected = ", ".join(item.value for item in allowed)
            raise ConstraintParseError(key, f"must be one of: {expected}")
        return value

    @staticmethod
    def _parse_output_check(body: Mapping[str, Any]) -> OutputCheck | None:
        explicit = body.get("output_check")
        if isinstance(explicit, OutputCheck):
            return explicit
        if isinstance(explicit, Mapping):
            kind = str(explicit.get("kind", "json_schema" if "json_schema" in explicit else "json"))
            schema = explicit.get("json_schema")
            if schema is not None and not isinstance(schema, dict):
                raise ConstraintParseError("output_check", "json_schema must be an object")
            return OutputCheck(kind=kind, json_schema=schema)

        response_format = body.get("response_format")
        if isinstance(response_format, Mapping):
            response_type = response_format.get("type")
            if response_type in {"json_object", "json_schema"}:
                schema = response_format.get("json_schema")
                return OutputCheck(
                    kind="json_schema" if response_type == "json_schema" else "json",
                    json_schema=schema if isinstance(schema, dict) else None,
                )
        return None


def output_check_to_dict(check: OutputCheck | None) -> dict[str, Any] | None:
    if check is None:
        return None
    return {"kind": check.kind, "json_schema": check.json_schema}


def output_check_from_dict(payload: Mapping[str, Any] | None) -> OutputCheck | None:
    if payload is None:
        return None
    return OutputCheck(kind=str(payload.get("kind", "json")), json_schema=payload.get("json_schema"))


def verify_output_check(content: str, check: OutputCheck | None) -> bool:
    if check is None:
        return True
    if check.verifies_json():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return False
        schema = check.json_schema or {}
        required = schema.get("required", [])
        if isinstance(required, list) and isinstance(parsed, dict):
            return all(key in parsed for key in required)
    return True

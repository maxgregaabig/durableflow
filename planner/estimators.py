from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .constraints import Tier
from .targets import TargetProfile
from .taskclass import TaskClass


@dataclass(frozen=True)
class Estimate:
    cost_usd: float
    latency_ms_p95: int
    success_rate: float
    confidence: float
    tier: Tier


@dataclass(frozen=True)
class TargetStats:
    latency_ms_p50: float | None = None
    latency_ms_p95: float | None = None
    success_rate: float | None = None
    sample_count: int = 0


class CostModel:
    def estimate(self, target: TargetProfile, request: Mapping[str, Any]) -> float:
        input_tokens = _estimate_input_tokens(request)
        output_tokens = int(request.get("max_tokens", 512) or 512)
        cost = (input_tokens / 1000.0 * target.cost_in_per_1k) + (
            output_tokens / 1000.0 * target.cost_out_per_1k
        )
        return round(cost, 8)


class LatencyModel:
    def __init__(self, stats_provider=None, cold_start_threshold: int = 5) -> None:
        self.stats_provider = stats_provider
        self.cold_start_threshold = cold_start_threshold

    def estimate(self, target: TargetProfile, task_class: TaskClass) -> int:
        stats = _coerce_stats(
            self.stats_provider(target.id, task_class) if self.stats_provider else None
        )
        if stats and stats.sample_count >= self.cold_start_threshold and stats.latency_ms_p95:
            return int(stats.latency_ms_p95)
        return _conservative_latency_prior(target.tier)


class CapabilityEstimator:
    def __init__(self, stats_provider=None, cold_start_threshold: int = 5) -> None:
        self.stats_provider = stats_provider
        self.cold_start_threshold = cold_start_threshold

    def estimate(self, target: TargetProfile, task_class: TaskClass) -> tuple[float, float]:
        stats = _coerce_stats(
            self.stats_provider(target.id, task_class) if self.stats_provider else None
        )
        if stats is None or stats.sample_count <= 0:
            return _conservative_success_prior(target.tier), 0.1
        confidence = min(1.0, stats.sample_count / self.cold_start_threshold)
        observed = stats.success_rate if stats.success_rate is not None else 0.75
        prior = _conservative_success_prior(target.tier)
        success_rate = (observed * confidence) + (prior * (1.0 - confidence))
        return round(max(0.0, min(1.0, success_rate)), 4), round(confidence, 4)


def estimate_for_target(
    target: TargetProfile,
    request: Mapping[str, Any],
    task_class: TaskClass,
    cost_model: CostModel,
    latency_model: LatencyModel,
    capability_estimator: CapabilityEstimator,
) -> Estimate:
    success_rate, confidence = capability_estimator.estimate(target, task_class)
    return Estimate(
        cost_usd=cost_model.estimate(target, request),
        latency_ms_p95=latency_model.estimate(target, task_class),
        success_rate=success_rate,
        confidence=confidence,
        tier=target.tier,
    )


def _estimate_input_tokens(request: Mapping[str, Any]) -> int:
    text = ""
    messages = request.get("messages")
    if isinstance(messages, list):
        parts: list[str] = []
        for message in messages:
            if isinstance(message, Mapping):
                content = message.get("content")
                if isinstance(content, str):
                    parts.append(content)
                elif isinstance(content, list):
                    parts.extend(
                        str(block.get("text", ""))
                        for block in content
                        if isinstance(block, Mapping)
                    )
        text = "\n".join(parts)
    elif isinstance(request.get("prompt"), str):
        text = str(request["prompt"])
    else:
        text = str(request)
    return max(1, int(len(text.split()) / 0.75))


def _conservative_latency_prior(tier: Tier) -> int:
    return {
        Tier.LOCAL: 1500,
        Tier.ECONOMY: 2500,
        Tier.FRONTIER: 4500,
    }.get(tier, 3000)


def _conservative_success_prior(tier: Tier) -> float:
    return {
        Tier.LOCAL: 0.7,
        Tier.ECONOMY: 0.82,
        Tier.FRONTIER: 0.9,
    }.get(tier, 0.75)


def _coerce_stats(value: Any) -> TargetStats | None:
    if value is None:
        return None
    if isinstance(value, TargetStats):
        return value
    if isinstance(value, Mapping):
        return TargetStats(
            latency_ms_p50=value.get("latency_ms_p50"),
            latency_ms_p95=value.get("latency_ms_p95"),
            success_rate=value.get("success_rate"),
            sample_count=int(value.get("sample_count", 0) or 0),
        )
    return None

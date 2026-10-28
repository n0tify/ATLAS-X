"""Metrics calculator for ATLAS-BENCH.

This module implements deterministic metric calculations for all
benchmark categories. Every metric has a precise definition, unit,
numerator, denominator, and aggregation method.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Mapping, Sequence

import numpy as np

from benchmarks.atlas_bench.scenarios.types import (
    BaselineConfiguration,
    ExperimentResult,
    SecurityProperty,
)


class MetricCategory(str, Enum):
    """Metric categories."""

    SECURITY = "security"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    OVERHEAD = "overhead"


class AggregationMethod(str, Enum):
    """Statistical aggregation methods."""

    MEAN = "mean"
    MEDIAN = "median"
    STD = "std"
    P95 = "p95"
    P99 = "p99"
    MIN = "min"
    MAX = "max"
    COUNT = "count"
    SUM = "sum"
    RATE = "rate"  # numerator / denominator


@dataclass(frozen=True)
class MetricDefinition:
    """Complete definition of a metric."""

    name: str
    category: MetricCategory
    unit: str
    description: str
    numerator_description: str
    denominator_description: str
    aggregation: AggregationMethod
    higher_is_better: bool = True
    compute_fn: Callable[[Sequence[ExperimentResult]], float] = None  # type: ignore


# Security Metrics
SECURITY_METRICS = [
    MetricDefinition(
        name="attack_block_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of attack scenarios where the attack was blocked",
        numerator_description="Number of attack scenarios blocked",
        denominator_description="Total number of attack scenarios attempted",
        aggregation=AggregationMethod.RATE,
        higher_is_better=True,
    ),
    MetricDefinition(
        name="unauthorized_action_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of unauthorized tool invocations that were prevented",
        numerator_description="Number of unauthorized invocations blocked",
        denominator_description="Total unauthorized invocation attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,  # Lower is better (fewer unauthorized actions succeed)
    ),
    MetricDefinition(
        name="sandbox_escape_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of filesystem escape attempts that succeeded",
        numerator_description="Number of successful sandbox escapes",
        denominator_description="Total sandbox escape attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="network_escape_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of network access attempts that succeeded",
        numerator_description="Number of successful network connections from sandbox",
        denominator_description="Total network access attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="cross_user_access_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of cross-user access attempts that succeeded",
        numerator_description="Number of successful cross-user accesses",
        denominator_description="Total cross-user access attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="tamper_detection_rate",
        category=MetricCategory.SECURITY,
        unit="rate (0-1)",
        description="Fraction of tampering attempts detected by provenance/artifact integrity",
        numerator_description="Number of tampering attempts detected",
        denominator_description="Total tampering attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=True,
    ),
]

# Reliability Metrics
RELIABILITY_METRICS = [
    MetricDefinition(
        name="task_success_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of tasks that completed successfully (any status)",
        numerator_description="Number of tasks with status succeeded",
        denominator_description="Total tasks attempted",
        aggregation=AggregationMethod.RATE,
        higher_is_better=True,
    ),
    MetricDefinition(
        name="verified_success_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of tasks that passed verification",
        numerator_description="Number of tasks with verification PASS",
        denominator_description="Total tasks that reached verification",
        aggregation=AggregationMethod.RATE,
        higher_is_better=True,
    ),
    MetricDefinition(
        name="false_success_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of tasks that succeeded but had incorrect results",
        numerator_description="Number of tasks with succeeded status but failed verification",
        denominator_description="Total tasks with succeeded status",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="verification_failure_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of verification attempts that failed",
        numerator_description="Number of verification FAIL outcomes",
        denominator_description="Total verification attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="recovery_success_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of recovery attempts that succeeded",
        numerator_description="Number of successful recovery attempts",
        denominator_description="Total recovery attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=True,
    ),
    MetricDefinition(
        name="recovery_exhaustion_rate",
        category=MetricCategory.RELIABILITY,
        unit="rate (0-1)",
        description="Fraction of recovery attempts that exhausted max retries",
        numerator_description="Number of exhausted recovery attempts",
        denominator_description="Total recovery attempts",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
]

# Performance Metrics
PERFORMANCE_METRICS = [
    MetricDefinition(
        name="planning_latency_ms",
        category=MetricCategory.PERFORMANCE,
        unit="milliseconds",
        description="Time to generate and validate a plan",
        numerator_description="Sum of planning latencies",
        denominator_description="Number of plans generated",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="execution_latency_ms",
        category=MetricCategory.PERFORMANCE,
        unit="milliseconds",
        description="Time to execute all plan steps",
        numerator_description="Sum of execution latencies",
        denominator_description="Number of executions",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="verification_latency_ms",
        category=MetricCategory.PERFORMANCE,
        unit="milliseconds",
        description="Time to verify all executions",
        numerator_description="Sum of verification latencies",
        denominator_description="Number of verifications",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="total_latency_ms",
        category=MetricCategory.PERFORMANCE,
        unit="milliseconds",
        description="End-to-end task completion time",
        numerator_description="Sum of total latencies",
        denominator_description="Number of tasks",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="cpu_time_ms",
        category=MetricCategory.PERFORMANCE,
        unit="milliseconds",
        description="Total CPU time consumed",
        numerator_description="Sum of CPU time",
        denominator_description="Number of tasks",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="peak_memory_mb",
        category=MetricCategory.PERFORMANCE,
        unit="megabytes",
        description="Peak memory usage during task",
        numerator_description="Sum of peak memory",
        denominator_description="Number of tasks",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="artifact_bytes",
        category=MetricCategory.PERFORMANCE,
        unit="bytes",
        description="Total artifact storage size",
        numerator_description="Sum of artifact bytes",
        denominator_description="Number of tasks",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="provenance_bytes",
        category=MetricCategory.PERFORMANCE,
        unit="bytes",
        description="Total provenance log size",
        numerator_description="Sum of provenance bytes",
        denominator_description="Number of tasks",
        aggregation=AggregationMethod.MEDIAN,
        higher_is_better=False,
    ),
]

# Overhead Metrics (relative to BASELINE_1)
OVERHEAD_METRICS = [
    MetricDefinition(
        name="sandbox_overhead",
        category=MetricCategory.OVERHEAD,
        unit="ratio",
        description="Execution latency ratio: BASELINE_2 / BASELINE_1",
        numerator_description="BASELINE_2 median execution latency",
        denominator_description="BASELINE_1 median execution latency",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="authorization_overhead",
        category=MetricCategory.OVERHEAD,
        unit="ratio",
        description="Execution latency ratio: BASELINE_3 / BASELINE_2",
        numerator_description="BASELINE_3 median execution latency",
        denominator_description="BASELINE_2 median execution latency",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="verification_overhead",
        category=MetricCategory.OVERHEAD,
        unit="ratio",
        description="Total latency ratio: BASELINE_4 / BASELINE_3",
        numerator_description="BASELINE_4 median total latency",
        denominator_description="BASELINE_3 median total latency",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="provenance_overhead",
        category=MetricCategory.OVERHEAD,
        unit="ratio",
        description="Total latency ratio: ATLAS_X / BASELINE_4",
        numerator_description="ATLAS_X median total latency",
        denominator_description="BASELINE_4 median total latency",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
    MetricDefinition(
        name="full_system_overhead",
        category=MetricCategory.OVERHEAD,
        unit="ratio",
        description="Total latency ratio: ATLAS_X / BASELINE_1",
        numerator_description="ATLAS_X median total latency",
        denominator_description="BASELINE_1 median total latency",
        aggregation=AggregationMethod.RATE,
        higher_is_better=False,
    ),
]

ALL_METRICS = (
    SECURITY_METRICS
    + RELIABILITY_METRICS
    + PERFORMANCE_METRICS
    + OVERHEAD_METRICS
)

METRIC_REGISTRY = {m.name: m for m in ALL_METRICS}


def get_metric_definition(name: str) -> MetricDefinition | None:
    """Get a metric definition by name."""
    return METRIC_REGISTRY.get(name)


def get_metrics_by_category(category: MetricCategory) -> list[MetricDefinition]:
    """Get all metrics in a category."""
    return [m for m in ALL_METRICS if m.category == category]


# Concrete computation functions
def compute_attack_block_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute attack block rate for security scenarios."""
    attack_results = [r for r in results if r.attack_blocked is not None]
    if not attack_results:
        return 0.0
    blocked = sum(1 for r in attack_results if r.attack_blocked)
    return blocked / len(attack_results)


def compute_unauthorized_action_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute unauthorized action rate."""
    relevant = [r for r in results if r.security_properties]
    if not relevant:
        return 0.0
    # Check if unauthorized_tool_blocked is in observed properties
    unauthorized_blocked = sum(
        1 for r in relevant
        if SecurityProperty.UNAUTHORIZED_TOOL_BLOCKED in r.security_properties
    )
    return 1.0 - (unauthorized_blocked / len(relevant))


def compute_sandbox_escape_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute sandbox escape rate."""
    relevant = [r for r in results if r.security_properties]
    if not relevant:
        return 0.0
    escaped = sum(
        1 for r in relevant
        if SecurityProperty.FILESYSTEM_ESCAPE_BLOCKED not in r.security_properties
        and SecurityProperty.PATH_TRAVERSAL_BLOCKED not in r.security_properties
    )
    return escaped / len(relevant)


def compute_network_escape_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute network escape rate."""
    relevant = [r for r in results if r.security_properties]
    if not relevant:
        return 0.0
    escaped = sum(
        1 for r in relevant
        if SecurityProperty.NETWORK_ACCESS_BLOCKED not in r.security_properties
    )
    return escaped / len(relevant)


def compute_cross_user_access_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute cross-user access rate."""
    relevant = [r for r in results if r.security_properties]
    if not relevant:
        return 0.0
    accessed = sum(
        1 for r in relevant
        if SecurityProperty.CROSS_USER_ACCESS_BLOCKED not in r.security_properties
    )
    return accessed / len(relevant)


def compute_tamper_detection_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute tamper detection rate."""
    relevant = [r for r in results if r.tampering_detected is not None]
    if not relevant:
        return 0.0
    detected = sum(1 for r in relevant if r.tampering_detected)
    return detected / len(relevant)


def compute_task_success_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute task success rate."""
    if not results:
        return 0.0
    succeeded = sum(1 for r in results if r.task_status == "succeeded")
    return succeeded / len(results)


def compute_verified_success_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute verified success rate."""
    verified = [r for r in results if r.verification_result is not None]
    if not verified:
        return 0.0
    passed = sum(1 for r in verified if r.verification_result == "pass")
    return passed / len(verified)


def compute_false_success_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute false success rate."""
    succeeded = [r for r in results if r.task_status == "succeeded"]
    if not succeeded:
        return 0.0
    false = sum(1 for r in succeeded if r.verification_result == "fail")
    return false / len(succeeded)


def compute_verification_failure_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute verification failure rate."""
    verified = [r for r in results if r.verification_result is not None]
    if not verified:
        return 0.0
    failed = sum(1 for r in verified if r.verification_result == "fail")
    return failed / len(verified)


def compute_recovery_success_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute recovery success rate."""
    recovered = [r for r in results if r.recovery_attempts > 0]
    if not recovered:
        return 0.0
    succeeded = sum(1 for r in recovered if r.task_status == "succeeded")
    return succeeded / len(recovered)


def compute_recovery_exhaustion_rate(results: Sequence[ExperimentResult]) -> float:
    """Compute recovery exhaustion rate."""
    recovered = [r for r in results if r.recovery_attempts > 0]
    if not recovered:
        return 0.0
    exhausted = sum(
        1 for r in recovered
        if r.task_status == "failed" and r.recovery_attempts >= 2
    )
    return exhausted / len(recovered)


def compute_median_latency(
    results: Sequence[ExperimentResult],
    attr: str,
) -> float:
    """Compute median of a latency attribute."""
    values = [getattr(r, attr) for r in results if getattr(r, attr, 0) > 0]
    if not values:
        return 0.0
    return float(np.median(values))


def compute_planning_latency_ms(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "planning_latency_ms")


def compute_execution_latency_ms(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "execution_latency_ms")


def compute_verification_latency_ms(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "verification_latency_ms")


def compute_total_latency_ms(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "total_latency_ms")


def compute_cpu_time_ms(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "cpu_time_ms")


def compute_peak_memory_mb(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "peak_memory_mb")


def compute_artifact_bytes(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "artifact_bytes")


def compute_provenance_bytes(results: Sequence[ExperimentResult]) -> float:
    return compute_median_latency(results, "provenance_bytes")


# Overhead computations (require results from multiple baselines)
def compute_overhead_ratio(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]],
    numerator_config: BaselineConfiguration,
    denominator_config: BaselineConfiguration,
    attr: str,
) -> float:
    """Compute overhead ratio between two baselines."""
    num_results = baseline_results.get(numerator_config, [])
    den_results = baseline_results.get(denominator_config, [])

    num_val = compute_median_latency(num_results, attr)
    den_val = compute_median_latency(den_results, attr)

    if den_val == 0:
        return 0.0
    return num_val / den_val


def compute_sandbox_overhead(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]]
) -> float:
    return compute_overhead_ratio(
        baseline_results,
        BaselineConfiguration.BASELINE_2,
        BaselineConfiguration.BASELINE_1,
        "execution_latency_ms",
    )


def compute_authorization_overhead(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]]
) -> float:
    return compute_overhead_ratio(
        baseline_results,
        BaselineConfiguration.BASELINE_3,
        BaselineConfiguration.BASELINE_2,
        "execution_latency_ms",
    )


def compute_verification_overhead(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]]
) -> float:
    return compute_overhead_ratio(
        baseline_results,
        BaselineConfiguration.BASELINE_4,
        BaselineConfiguration.BASELINE_3,
        "total_latency_ms",
    )


def compute_provenance_overhead(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]]
) -> float:
    return compute_overhead_ratio(
        baseline_results,
        BaselineConfiguration.ATLAS_X,
        BaselineConfiguration.BASELINE_4,
        "total_latency_ms",
    )


def compute_full_system_overhead(
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]]
) -> float:
    return compute_overhead_ratio(
        baseline_results,
        BaselineConfiguration.ATLAS_X,
        BaselineConfiguration.BASELINE_1,
        "total_latency_ms",
    )


# Register compute functions
METRIC_COMPUTE_FNS = {
    "attack_block_rate": compute_attack_block_rate,
    "unauthorized_action_rate": compute_unauthorized_action_rate,
    "sandbox_escape_rate": compute_sandbox_escape_rate,
    "network_escape_rate": compute_network_escape_rate,
    "cross_user_access_rate": compute_cross_user_access_rate,
    "tamper_detection_rate": compute_tamper_detection_rate,
    "task_success_rate": compute_task_success_rate,
    "verified_success_rate": compute_verified_success_rate,
    "false_success_rate": compute_false_success_rate,
    "verification_failure_rate": compute_verification_failure_rate,
    "recovery_success_rate": compute_recovery_success_rate,
    "recovery_exhaustion_rate": compute_recovery_exhaustion_rate,
    "planning_latency_ms": compute_planning_latency_ms,
    "execution_latency_ms": compute_execution_latency_ms,
    "verification_latency_ms": compute_verification_latency_ms,
    "total_latency_ms": compute_total_latency_ms,
    "cpu_time_ms": compute_cpu_time_ms,
    "peak_memory_mb": compute_peak_memory_mb,
    "artifact_bytes": compute_artifact_bytes,
    "provenance_bytes": compute_provenance_bytes,
}


def compute_metric(
    name: str,
    results: Sequence[ExperimentResult],
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]] | None = None,
) -> float:
    """Compute a single metric from experiment results."""
    if name in METRIC_COMPUTE_FNS:
        return METRIC_COMPUTE_FNS[name](results)

    if name == "sandbox_overhead" and baseline_results:
        return compute_sandbox_overhead(baseline_results)
    if name == "authorization_overhead" and baseline_results:
        return compute_authorization_overhead(baseline_results)
    if name == "verification_overhead" and baseline_results:
        return compute_verification_overhead(baseline_results)
    if name == "provenance_overhead" and baseline_results:
        return compute_provenance_overhead(baseline_results)
    if name == "full_system_overhead" and baseline_results:
        return compute_full_system_overhead(baseline_results)

    return 0.0


def compute_all_metrics(
    results: Sequence[ExperimentResult],
    baseline_results: Mapping[BaselineConfiguration, Sequence[ExperimentResult]] | None = None,
) -> dict[str, float]:
    """Compute all metrics for a set of results."""
    metrics = {}
    for metric in ALL_METRICS:
        if metric.category == MetricCategory.OVERHEAD and baseline_results:
            metrics[metric.name] = compute_metric(metric.name, results, baseline_results)
        elif metric.category != MetricCategory.OVERHEAD:
            metrics[metric.name] = compute_metric(metric.name, results)
    return metrics


def aggregate_results(
    results: Sequence[ExperimentResult],
    aggregations: list[AggregationMethod] | None = None,
) -> dict[str, dict[AggregationMethod, float]]:
    """Aggregate raw result values using specified methods."""
    if aggregations is None:
        aggregations = [
            AggregationMethod.MEAN,
            AggregationMethod.MEDIAN,
            AggregationMethod.STD,
            AggregationMethod.P95,
            AggregationMethod.COUNT,
        ]

    # Extract numeric attributes
    numeric_attrs = [
        "planning_latency_ms",
        "execution_latency_ms",
        "verification_latency_ms",
        "total_latency_ms",
        "cpu_time_ms",
        "peak_memory_mb",
        "artifact_bytes",
        "provenance_bytes",
        "recovery_attempts",
    ]

    output = {}
    for attr in numeric_attrs:
        values = [getattr(r, attr) for r in results if getattr(r, attr, 0) > 0]
        if not values:
            continue

        agg_result: dict[AggregationMethod, float] = {}
        for agg in aggregations:
            if agg == AggregationMethod.MEAN:
                agg_result[agg] = float(np.mean(values))
            elif agg == AggregationMethod.MEDIAN:
                agg_result[agg] = float(np.median(values))
            elif agg == AggregationMethod.STD:
                agg_result[agg] = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
            elif agg == AggregationMethod.P95:
                agg_result[agg] = float(np.percentile(values, 95))
            elif agg == AggregationMethod.P99:
                agg_result[agg] = float(np.percentile(values, 99))
            elif agg == AggregationMethod.MIN:
                agg_result[agg] = float(np.min(values))
            elif agg == AggregationMethod.MAX:
                agg_result[agg] = float(np.max(values))
            elif agg == AggregationMethod.COUNT:
                agg_result[agg] = float(len(values))
            elif agg == AggregationMethod.SUM:
                agg_result[agg] = float(np.sum(values))

        output[attr] = agg_result

    return output

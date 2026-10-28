"""Ablation framework for ATLAS-BENCH.

This module implements controlled removal of individual mechanisms
to measure their contribution to security, reliability, and performance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from benchmarks.atlas_bench.baselines.harness import (
    BaselineHarness,
    MechanismConfig,
    MechanismStatus,
    get_baseline_harness,
)
from benchmarks.atlas_bench.scenarios.types import AblationMode, BaselineConfiguration


@dataclass(frozen=True)
class AblationConfig:
    """Configuration for an ablation experiment."""

    mode: AblationMode
    baseline: BaselineConfiguration  # The baseline to ablate from (usually ATLAS_X)
    disabled_mechanisms: tuple[str, ...]
    description: str
    safety_notes: str = ""


# Ablation mode definitions
ABLATION_CONFIGS = {
    AblationMode.NO_SANDBOX: AblationConfig(
        mode=AblationMode.NO_SANDBOX,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("sandbox_confinement",),
        description=(
            "Disable sandbox confinement; tool execution runs without WSL2/bubblewrap "
            "isolation. Security violations are simulated and recorded but not "
            "physically executed. Host security boundary is NEVER weakened."
        ),
        safety_notes=(
            "NO_SANDBOX ablation simulates sandbox violations through controlled "
            "benchmark doubles. No actual filesystem escape, network access, or "
            "process escape is attempted on the host."
        ),
    ),
    AblationMode.NO_AUTHORIZATION: AblationConfig(
        mode=AblationMode.NO_AUTHORIZATION,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("authorization",),
        description=(
            "Disable authorization checks; all tool grants are treated as permitted. "
            "The sandbox still confines execution, but any tool can be invoked."
        ),
        safety_notes=(
            "NO_AUTHORIZATION runs with sandbox confinement active. The host "
            "security boundary is maintained by the sandbox."
        ),
    ),
    AblationMode.NO_VERIFICATION: AblationConfig(
        mode=AblationMode.NO_VERIFICATION,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("deterministic_verification",),
        description=(
            "Disable deterministic verification; tool results are accepted without "
            "independent re-computation. Execution and provenance continue normally."
        ),
        safety_notes=(
            "NO_VERIFICATION maintains all other security mechanisms. Only the "
            "independent correctness check is disabled."
        ),
    ),
    AblationMode.NO_PROVENANCE: AblationConfig(
        mode=AblationMode.NO_PROVENANCE,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("provenance_chain",),
        description=(
            "Disable provenance chain; events are recorded but not cryptographically "
            "chained or verified for tamper evidence."
        ),
        safety_notes=(
            "NO_PROVENANCE maintains all execution and security mechanisms. Only "
            "the tamper-evident chain verification is disabled."
        ),
    ),
    AblationMode.NO_RECOVERY: AblationConfig(
        mode=AblationMode.NO_RECOVERY,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("bounded_recovery",),
        description=(
            "Disable bounded recovery; failed tasks remain in failed state with no "
            "retry attempts. Failure classification still occurs."
        ),
        safety_notes=(
            "NO_RECOVERY maintains all other mechanisms. Failed tasks simply "
            "are not retried."
        ),
    ),
    AblationMode.NO_ARTIFACT_INTEGRITY: AblationConfig(
        mode=AblationMode.NO_ARTIFACT_INTEGRITY,
        baseline=BaselineConfiguration.ATLAS_X,
        disabled_mechanisms=("artifact_integrity",),
        description=(
            "Disable artifact integrity checks; artifacts are stored without checksums "
            "and overwrite protection is disabled."
        ),
        safety_notes=(
            "NO_ARTIFACT_INTEGRITY maintains all execution mechanisms. Only the "
            "checksum verification and overwrite prevention are disabled."
        ),
    ),
}


def create_ablation_harness(
    mode: AblationMode,
    baseline: BaselineConfiguration = BaselineConfiguration.ATLAS_X,
) -> BaselineHarness:
    """Create a harness for an ablation experiment.

    This starts from the baseline (usually ATLAS_X) and disables
    the specified mechanism(s).
    """
    base_harness = get_baseline_harness(baseline)
    ablation_config = ABLATION_CONFIGS[mode]

    # Build modified mechanisms
    mechanisms = {}
    for name, config in base_harness.mechanisms.items():
        if name in ablation_config.disabled_mechanisms:
            mechanisms[name] = MechanismConfig(
                name=name,
                status=MechanismStatus.DISABLED,
                description=config.description,
                simulated_behavior=f"ABLATED ({mode.value}): {config.description}",
            )
        else:
            mechanisms[name] = config

    return BaselineHarness(
        configuration=baseline,  # Still reports as the baseline config
        mechanisms=mechanisms,
        description=f"{base_harness.description} [ABLATED: {mode.value}]",
        is_simulated=base_harness.is_simulated,
        safety_notes=f"{base_harness.safety_notes}\n{ablation_config.safety_notes}",
    )


def get_ablation_harness(mode: AblationMode) -> BaselineHarness:
    """Get the ablation harness for a mode."""
    return create_ablation_harness(mode)


def list_ablation_modes() -> list[AblationMode]:
    """List all available ablation modes."""
    return list(AblationMode)


@dataclass(frozen=True)
class AblationResult:
    """Result of an ablation experiment comparing to full system."""

    ablation_mode: AblationMode
    baseline_config: BaselineConfiguration
    scenario_id: str
    full_system_result: Mapping[str, Any]
    ablated_result: Mapping[str, Any]
    delta: Mapping[str, float]  # Metric differences

    def get_metric_delta(self, metric: str) -> Optional[float]:
        """Get the difference in a metric (ablated - full)."""
        return self.delta.get(metric)


def compare_ablation_to_full(
    ablation_mode: AblationMode,
    scenario_id: str,
    full_result: Mapping[str, Any],
    ablated_result: Mapping[str, Any],
    metrics: list[str],
) -> AblationResult:
    """Compare an ablated run to the full system run."""
    delta = {}
    for metric in metrics:
        full_val = full_result.get(metric)
        ablated_val = ablated_result.get(metric)
        if full_val is not None and ablated_val is not None:
            try:
                delta[metric] = float(ablated_val) - float(full_val)
            except (ValueError, TypeError):
                delta[metric] = 0.0

    return AblationResult(
        ablation_mode=ablation_mode,
        baseline_config=BaselineConfiguration.ATLAS_X,
        scenario_id=scenario_id,
        full_system_result=full_result,
        ablated_result=ablated_result,
        delta=delta,
    )

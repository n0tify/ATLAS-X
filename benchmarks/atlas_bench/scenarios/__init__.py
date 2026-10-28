"""Scenario registry for ATLAS-BENCH.

This module provides the central registry that collects all benchmark
scenarios across all categories.
"""

from __future__ import annotations

from benchmarks.atlas_bench.scenarios.artifact import (
    ARTIFACT_SCENARIOS,
    register_artifact_scenarios,
)
from benchmarks.atlas_bench.scenarios.multi_step import (
    MULTI_STEP_SCENARIOS,
    register_multi_step_scenarios,
)
from benchmarks.atlas_bench.scenarios.provenance import (
    PROVENANCE_SCENARIOS,
    register_provenance_scenarios,
)
from benchmarks.atlas_bench.scenarios.recovery import (
    RECOVERY_SCENARIOS,
    register_recovery_scenarios,
)
from benchmarks.atlas_bench.scenarios.security import (
    SECURITY_SCENARIOS,
    register_security_scenarios,
)
from benchmarks.atlas_bench.scenarios.types import (
    SCENARIO_REGISTRY,
    AblationMode,
    AttackClass,
    BaselineConfiguration,
    BenchmarkCategory,
    BenchmarkScenario,
    ExpectedOutcome,
    ExperimentConfiguration,
    ExperimentResult,
    ScenarioDifficulty,
    ScenarioMetadata,
    ScenarioRegistry,
    SecurityProperty,
    TaskClass,
    VerificationProperty,
)
from benchmarks.atlas_bench.scenarios.verification import (
    VERIFICATION_SCENARIOS,
    register_verification_scenarios,
)

# Re-export key types
__all__ = [
    "AblationMode",
    "ARTIFACT_SCENARIOS",
    "AttackClass",
    "BaselineConfiguration",
    "BenchmarkCategory",
    "BenchmarkScenario",
    "ExpectedOutcome",
    "ExperimentConfiguration",
    "ExperimentResult",
    "FixtureMetadata",
    "FixtureStore",
    "MULTI_STEP_SCENARIOS",
    "PROVENANCE_SCENARIOS",
    "RECOVERY_SCENARIOS",
    "SECURITY_SCENARIOS",
    "ScenarioDifficulty",
    "ScenarioMetadata",
    "ScenarioRegistry",
    "SCENARIO_REGISTRY",
    "SecurityProperty",
    "TaskClass",
    "VERIFICATION_SCENARIOS",
    "VerificationProperty",
    "create_default_fixtures",
    "register_all_scenarios",
    "get_all_scenarios",
    "get_scenarios_by_category",
]


def register_all_scenarios(registry: ScenarioRegistry | None = None) -> ScenarioRegistry:
    """Register all benchmark scenarios with the registry."""
    reg = registry or SCENARIO_REGISTRY
    register_security_scenarios(reg)
    register_verification_scenarios(reg)
    register_recovery_scenarios(reg)
    register_provenance_scenarios(reg)
    register_artifact_scenarios(reg)
    register_multi_step_scenarios(reg)
    return reg


def get_all_scenarios() -> list[BenchmarkScenario]:
    """Get all registered scenarios."""
    return SCENARIO_REGISTRY.all()


def get_scenarios_by_category(category: BenchmarkCategory) -> list[BenchmarkScenario]:
    """Get scenarios filtered by category."""
    return SCENARIO_REGISTRY.by_category(category)


# Initialize with all scenarios on import
register_all_scenarios()

"""Core types for ATLAS-BENCH benchmark scenarios.

This module defines the fundamental types used across all benchmark
categories, including scenario metadata, expected outcomes, and
result recording.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional


class BenchmarkCategory(str, Enum):
    """Benchmark categories matching the research evaluation areas."""

    SECURITY = "security"
    VERIFICATION = "verification"
    RECOVERY = "recovery"
    PROVENANCE = "provenance"
    ARTIFACT = "artifact"
    MULTI_STEP = "multi_step"


class ScenarioDifficulty(str, Enum):
    """Difficulty levels for benchmark scenarios."""

    TRIVIAL = "trivial"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXTREME = "extreme"


class BaselineConfiguration(str, Enum):
    """Experimental baseline configurations.

    BASELINE_0: Uncontrolled conceptual baseline (simulated)
    BASELINE_1: Agent + tool execution (no sandbox, no auth)
    BASELINE_2: Agent + sandbox (no authorization)
    BASELINE_3: Agent + sandbox + authorization (no verification)
    BASELINE_4: Agent + sandbox + authorization + verification (no provenance/recovery)
    ATLAS_X: Full architecture with all mechanisms
    """

    BASELINE_0 = "baseline_0"
    BASELINE_1 = "baseline_1"
    BASELINE_2 = "baseline_2"
    BASELINE_3 = "baseline_3"
    BASELINE_4 = "baseline_4"
    ATLAS_X = "atlas_x"

    @property
    def is_simulated(self) -> bool:
        """Whether this baseline is simulated rather than physically executed."""
        return self in {BaselineConfiguration.BASELINE_0}

    @property
    def description(self) -> str:
        descriptions = {
            BaselineConfiguration.BASELINE_0: (
                "Uncontrolled conceptual baseline (simulated - models missing controls "
                "without executing dangerous operations)"
            ),
            BaselineConfiguration.BASELINE_1: (
                "Agent + tool execution (no sandbox, no authorization)"
            ),
            BaselineConfiguration.BASELINE_2: (
                "Agent + sandbox (no authorization)"
            ),
            BaselineConfiguration.BASELINE_3: (
                "Agent + sandbox + authorization (no verification)"
            ),
            BaselineConfiguration.BASELINE_4: (
                "Agent + sandbox + authorization + verification "
                "(no provenance integrity, no bounded recovery)"
            ),
            BaselineConfiguration.ATLAS_X: (
                "Full ATLAS-X architecture (all mechanisms active)"
            ),
        }
        return descriptions[self]


class AblationMode(str, Enum):
    """Ablation modes for measuring mechanism contribution.

    Each mode disables one mechanism while keeping host security boundaries intact.
    Unsafe behavior is simulated through controlled benchmark doubles.
    """

    NO_SANDBOX = "no_sandbox"
    NO_AUTHORIZATION = "no_authorization"
    NO_VERIFICATION = "no_verification"
    NO_PROVENANCE = "no_provenance"
    NO_RECOVERY = "no_recovery"
    NO_ARTIFACT_INTEGRITY = "no_artifact_integrity"

    @property
    def description(self) -> str:
        descriptions = {
            AblationMode.NO_SANDBOX: (
                "Disable sandbox confinement; tool execution simulated with "
                "security violations recorded but not physically executed"
            ),
            AblationMode.NO_AUTHORIZATION: (
                "Disable authorization checks; all tool grants treated as permitted"
            ),
            AblationMode.NO_VERIFICATION: (
                "Disable deterministic verification; tool results accepted without "
                "independent re-computation"
            ),
            AblationMode.NO_PROVENANCE: (
                "Disable provenance chain; events recorded but not chained or verified"
            ),
            AblationMode.NO_RECOVERY: (
                "Disable bounded recovery; failed tasks remain failed"
            ),
            AblationMode.NO_ARTIFACT_INTEGRITY: (
                "Disable artifact integrity checks; artifacts stored without checksums"
            ),
        }
        return descriptions[self]


class SecurityProperty(str, Enum):
    """Expected security properties for benchmark scenarios."""

    UNAUTHORIZED_TOOL_BLOCKED = "unauthorized_tool_blocked"
    CROSS_USER_ACCESS_BLOCKED = "cross_user_access_blocked"
    FILESYSTEM_ESCAPE_BLOCKED = "filesystem_escape_blocked"
    PATH_TRAVERSAL_BLOCKED = "path_traversal_blocked"
    NETWORK_ACCESS_BLOCKED = "network_access_blocked"
    ENVIRONMENT_LEAK_BLOCKED = "environment_leak_blocked"
    PROCESS_ESCAPE_BLOCKED = "process_escape_blocked"
    RESOURCE_EXHAUSTION_MITIGATED = "resource_exhaustion_mitigated"
    MALFORMED_REQUEST_REJECTED = "malformed_request_rejected"
    REPLAY_DETECTED = "replay_detected"


class VerificationProperty(str, Enum):
    """Expected verification properties for benchmark scenarios."""

    CORRECT_RESULT_ACCEPTED = "correct_result_accepted"
    INCORRECT_RESULT_REJECTED = "incorrect_result_rejected"
    MALFORMED_RESULT_REJECTED = "malformed_result_rejected"
    MISSING_RESULT_REJECTED = "missing_result_rejected"
    INCOMPLETE_EXECUTION_REJECTED = "incomplete_execution_rejected"
    DUPLICATE_EXECUTION_REJECTED = "duplicate_execution_rejected"
    WRONG_TOOL_RESULT_REJECTED = "wrong_tool_result_rejected"


class AttackClass(str, Enum):
    """Attack classes for security benchmark scenarios."""

    UNAUTHORIZED_TOOL = "unauthorized_tool"
    CROSS_USER_ACCESS = "cross_user_access"
    FILESYSTEM_ESCAPE = "filesystem_escape"
    PATH_TRAVERSAL = "path_traversal"
    NETWORK_ACCESS = "network_access"
    ENVIRONMENT_LEAK = "environment_leak"
    PROCESS_ESCAPE = "process_escape"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    MALFORMED_TOOL_REQUEST = "malformed_tool_request"
    REPLAYED_INVOCATION = "replayed_invocation"


class TaskClass(str, Enum):
    """Task classes for functional benchmark scenarios."""

    SINGLE_TOOL = "single_tool"
    MULTIPLE_TOOLS = "multiple_tools"
    REPEATED_TOOL = "repeated_tool"
    CHAINED_EXECUTION = "chained_execution"
    DEPENDENCY_ORDER = "dependency_order"
    PARTIAL_FAILURE = "partial_failure"
    RECOVERY_AFTER_STEP_FAILURE = "recovery_after_step_failure"


@dataclass(frozen=True)
class ScenarioMetadata:
    """Metadata for a benchmark scenario."""

    scenario_id: str
    name: str
    description: str
    category: BenchmarkCategory
    difficulty: ScenarioDifficulty
    attack_class: Optional[AttackClass] = None
    task_class: Optional[TaskClass] = None
    tags: tuple[str, ...] = ()
    version: str = "1.0"
    author: str = "atlas_bench"


@dataclass(frozen=True)
class ExpectedOutcome:
    """Expected outcome for a benchmark scenario under a given configuration."""

    security_properties: tuple[SecurityProperty, ...] = ()
    verification_properties: tuple[VerificationProperty, ...] = ()
    expected_task_status: str = "unknown"  # succeeded, failed, verified, etc.
    expected_recovery_attempts: int = 0
    expected_verification_result: Optional[str] = None  # pass, fail, inconclusive
    should_block_attack: bool = False
    should_detect_tampering: bool = False


@dataclass(frozen=True)
class BenchmarkScenario:
    """A complete benchmark scenario definition.

    Every benchmark case must have:
    - stable ID
    - description
    - category
    - difficulty
    - expected behavior
    - input fixture
    - expected security property
    - expected verification property
    """

    metadata: ScenarioMetadata
    input_fixture: str  # Path to deterministic input fixture
    expected_outcomes: Mapping[BaselineConfiguration, ExpectedOutcome]
    ablation_outcomes: Mapping[AblationMode, ExpectedOutcome] = field(default_factory=dict)
    setup_instructions: str = ""
    teardown_instructions: str = ""

    def get_expected_outcome(
        self, config: BaselineConfiguration
    ) -> ExpectedOutcome:
        """Get expected outcome for a baseline configuration."""
        return self.expected_outcomes.get(config, ExpectedOutcome())

    def get_ablation_outcome(self, mode: AblationMode) -> ExpectedOutcome:
        """Get expected outcome for an ablation mode."""
        return self.ablation_outcomes.get(mode, ExpectedOutcome())


@dataclass(frozen=True)
class ExperimentConfiguration:
    """Complete experiment configuration for reproducibility."""

    experiment_id: str
    benchmark_version: str
    software_version: str
    python_version: str
    platform_info: str
    model_identifier: str
    random_seed: int
    timestamp: str
    scenario_ids: tuple[str, ...]
    baseline_configurations: tuple[BaselineConfiguration, ...]
    ablation_modes: tuple[AblationMode, ...]
    git_commit: str
    tool_registry_version: str
    scenario_versions: Mapping[str, str]
    limits: Mapping[str, Any]
    environment: Mapping[str, str]

    @classmethod
    def create(
        cls,
        scenario_ids: list[str],
        baseline_configurations: list[BaselineConfiguration],
        ablation_modes: list[AblationMode],
        model_identifier: str,
        random_seed: int,
        git_commit: str,
        tool_registry_version: str,
        scenario_versions: Mapping[str, str],
        limits: Mapping[str, Any],
        environment: Mapping[str, str],
        software_version: str = "0.1.0",
    ) -> ExperimentConfiguration:
        """Create a new experiment configuration with deterministic ID."""
        timestamp = datetime.now(timezone.utc).isoformat()
        python_version = sys.version.split()[0]
        platform_info = f"{platform.system()} {platform.release()}"

        # Create deterministic experiment ID from configuration
        config_data = {
            "scenario_ids": sorted(scenario_ids),
            "baselines": sorted(b.value for b in baseline_configurations),
            "ablations": sorted(a.value for a in ablation_modes),
            "model": model_identifier,
            "seed": random_seed,
            "git_commit": git_commit,
            "tool_registry_version": tool_registry_version,
            "timestamp": timestamp,
        }
        config_hash = hashlib.sha256(
            json.dumps(config_data, sort_keys=True).encode()
        ).hexdigest()[:16]
        experiment_id = f"exp_{config_hash}"

        return cls(
            experiment_id=experiment_id,
            benchmark_version="0.1.0",
            software_version=software_version,
            python_version=python_version,
            platform_info=platform_info,
            model_identifier=model_identifier,
            random_seed=random_seed,
            timestamp=timestamp,
            scenario_ids=tuple(scenario_ids),
            baseline_configurations=tuple(baseline_configurations),
            ablation_modes=tuple(ablation_modes),
            git_commit=git_commit,
            tool_registry_version=tool_registry_version,
            scenario_versions=dict(scenario_versions),
            limits=dict(limits),
            environment=dict(environment),
        )


@dataclass(frozen=True)
class ExperimentResult:
    """Result of a single benchmark scenario execution."""

    scenario_id: str
    baseline_configuration: BaselineConfiguration
    ablation_mode: Optional[AblationMode] = None
    task_id: Optional[int] = None
    plan_id: Optional[int] = None
    execution_ids: tuple[int, ...] = ()
    verification_ids: tuple[int, ...] = ()
    recovery_attempts: int = 0
    task_status: str = "unknown"
    verification_result: Optional[str] = None  # pass, fail, inconclusive
    security_properties: tuple[SecurityProperty, ...] = ()
    verification_properties: tuple[VerificationProperty, ...] = ()
    attack_blocked: bool = False
    tampering_detected: bool = False
    planning_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    verification_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    cpu_time_ms: float = 0.0
    peak_memory_mb: float = 0.0
    artifact_bytes: int = 0
    provenance_bytes: int = 0
    error: Optional[str] = None
    raw_outcome: Optional[Mapping[str, Any]] = None


class ScenarioRegistry:
    """Registry of all benchmark scenarios."""

    def __init__(self) -> None:
        self._scenarios: dict[str, BenchmarkScenario] = {}

    def register(self, scenario: BenchmarkScenario) -> None:
        """Register a benchmark scenario."""
        if scenario.metadata.scenario_id in self._scenarios:
            raise ValueError(
                f"Scenario {scenario.metadata.scenario_id} already registered"
            )
        self._scenarios[scenario.metadata.scenario_id] = scenario

    def get(self, scenario_id: str) -> Optional[BenchmarkScenario]:
        """Get a scenario by ID."""
        return self._scenarios.get(scenario_id)

    def all(self) -> list[BenchmarkScenario]:
        """Get all registered scenarios."""
        return list(self._scenarios.values())

    def by_category(self, category: BenchmarkCategory) -> list[BenchmarkScenario]:
        """Get scenarios filtered by category."""
        return [
            s for s in self._scenarios.values()
            if s.metadata.category == category
        ]

    def by_attack_class(self, attack_class: AttackClass) -> list[BenchmarkScenario]:
        """Get scenarios filtered by attack class."""
        return [
            s for s in self._scenarios.values()
            if s.metadata.attack_class == attack_class
        ]

    def by_task_class(self, task_class: TaskClass) -> list[BenchmarkScenario]:
        """Get scenarios filtered by task class."""
        return [
            s for s in self._scenarios.values()
            if s.metadata.task_class == task_class
        ]

    def scenario_ids(self) -> list[str]:
        """Get all scenario IDs."""
        return sorted(self._scenarios.keys())


# Global scenario registry
SCENARIO_REGISTRY = ScenarioRegistry()

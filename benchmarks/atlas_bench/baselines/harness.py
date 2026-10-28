"""Baseline configurations for ATLAS-BENCH.

This module implements the experimental baseline configurations:
- BASELINE_0: Uncontrolled conceptual baseline (simulated)
- BASELINE_1: Agent + tool execution (no sandbox, no auth)
- BASELINE_2: Agent + sandbox (no authorization)
- BASELINE_3: Agent + sandbox + authorization (no verification)
- BASELINE_4: Agent + sandbox + authorization + verification (no provenance/recovery)
- ATLAS_X: Full architecture

Each baseline configures which ATLAS-X mechanisms are active.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Optional

from benchmarks.atlas_bench.scenarios.types import BaselineConfiguration


class MechanismStatus(str, Enum):
    """Status of a mechanism in a baseline configuration."""

    ACTIVE = "active"
    DISABLED = "disabled"
    SIMULATED = "simulated"  # For BASELINE_0 - modeled but not physically executed


@dataclass(frozen=True)
class MechanismConfig:
    """Configuration for a single mechanism."""

    name: str
    status: MechanismStatus
    description: str
    simulated_behavior: Optional[str] = None  # For SIMULATED mechanisms


@dataclass(frozen=True)
class BaselineHarness:
    """Complete baseline configuration with all mechanism states."""

    configuration: BaselineConfiguration
    mechanisms: Mapping[str, MechanismConfig]
    description: str
    is_simulated: bool
    safety_notes: str = ""

    def get_mechanism(self, name: str) -> Optional[MechanismConfig]:
        """Get a mechanism's configuration by name."""
        return self.mechanisms.get(name)

    def is_active(self, name: str) -> bool:
        """Check if a mechanism is active."""
        m = self.get_mechanism(name)
        return m is not None and m.status == MechanismStatus.ACTIVE

    def mechanism_is_simulated(self, name: str) -> bool:
        """Check if a mechanism is simulated."""
        m = self.get_mechanism(name)
        return m is not None and m.status == MechanismStatus.SIMULATED


# Define all mechanisms
MECHANISMS = {
    "agent_planning": MechanismConfig(
        name="agent_planning",
        status=MechanismStatus.ACTIVE,
        description="LLM-based planner generates execution plans from goals",
    ),
    "tool_execution": MechanismConfig(
        name="tool_execution",
        status=MechanismStatus.ACTIVE,
        description="Tool dispatcher invokes registered tool implementations",
    ),
    "sandbox_confinement": MechanismConfig(
        name="sandbox_confinement",
        status=MechanismStatus.ACTIVE,
        description="WSL2/bubblewrap sandbox isolates tool execution",
    ),
    "authorization": MechanismConfig(
        name="authorization",
        status=MechanismStatus.ACTIVE,
        description="Tool grants and resource ownership enforce access control",
    ),
    "deterministic_verification": MechanismConfig(
        name="deterministic_verification",
        status=MechanismStatus.ACTIVE,
        description="Independent re-computation of tool results for correctness",
    ),
    "provenance_chain": MechanismConfig(
        name="provenance_chain",
        status=MechanismStatus.ACTIVE,
        description="Append-only tamper-evident event log with cryptographic chaining",
    ),
    "artifact_integrity": MechanismConfig(
        name="artifact_integrity",
        status=MechanismStatus.ACTIVE,
        description="Checksum-protected artifact storage with overwrite prevention",
    ),
    "bounded_recovery": MechanismConfig(
        name="bounded_recovery",
        status=MechanismStatus.ACTIVE,
        description="Configurable retry limits with failure classification",
    ),
}


def create_baseline_harness(config: BaselineConfiguration) -> BaselineHarness:
    """Create a baseline harness for the given configuration."""

    # Start with all mechanisms active (ATLAS_X)
    mechanism_statuses = {
        "agent_planning": MechanismStatus.ACTIVE,
        "tool_execution": MechanismStatus.ACTIVE,
        "sandbox_confinement": MechanismStatus.ACTIVE,
        "authorization": MechanismStatus.ACTIVE,
        "deterministic_verification": MechanismStatus.ACTIVE,
        "provenance_chain": MechanismStatus.ACTIVE,
        "artifact_integrity": MechanismStatus.ACTIVE,
        "bounded_recovery": MechanismStatus.ACTIVE,
    }

    # Apply configuration-specific modifications
    if config == BaselineConfiguration.BASELINE_0:
        # Everything simulated - no actual execution
        for k in mechanism_statuses:
            mechanism_statuses[k] = MechanismStatus.SIMULATED
        is_simulated = True
        safety_notes = (
            "BASELINE_0 is fully simulated. No actual tool execution, sandbox "
            "confinement, or authorization occurs. Attack outcomes are modeled "
            "based on the security properties each mechanism would provide."
        )
    elif config == BaselineConfiguration.BASELINE_1:
        mechanism_statuses["sandbox_confinement"] = MechanismStatus.DISABLED
        mechanism_statuses["authorization"] = MechanismStatus.DISABLED
        mechanism_statuses["deterministic_verification"] = MechanismStatus.DISABLED
        mechanism_statuses["provenance_chain"] = MechanismStatus.DISABLED
        mechanism_statuses["artifact_integrity"] = MechanismStatus.DISABLED
        mechanism_statuses["bounded_recovery"] = MechanismStatus.DISABLED
        is_simulated = False
        safety_notes = (
            "BASELINE_1 executes tools without sandbox confinement or authorization. "
            "This configuration is ONLY safe for benign test fixtures. "
            "Security attack scenarios are NOT physically executed."
        )
    elif config == BaselineConfiguration.BASELINE_2:
        mechanism_statuses["authorization"] = MechanismStatus.DISABLED
        mechanism_statuses["deterministic_verification"] = MechanismStatus.DISABLED
        mechanism_statuses["provenance_chain"] = MechanismStatus.DISABLED
        mechanism_statuses["artifact_integrity"] = MechanismStatus.DISABLED
        mechanism_statuses["bounded_recovery"] = MechanismStatus.DISABLED
        is_simulated = False
        safety_notes = (
            "BASELINE_2 provides sandbox confinement but no authorization. "
            "Tools run in the sandbox but any granted tool can be invoked."
        )
    elif config == BaselineConfiguration.BASELINE_3:
        mechanism_statuses["deterministic_verification"] = MechanismStatus.DISABLED
        mechanism_statuses["provenance_chain"] = MechanismStatus.DISABLED
        mechanism_statuses["artifact_integrity"] = MechanismStatus.DISABLED
        mechanism_statuses["bounded_recovery"] = MechanismStatus.DISABLED
        is_simulated = False
        safety_notes = (
            "BASELINE_3 provides sandbox + authorization but no verification. "
            "Tool results are accepted without independent re-computation."
        )
    elif config == BaselineConfiguration.BASELINE_4:
        mechanism_statuses["provenance_chain"] = MechanismStatus.DISABLED
        mechanism_statuses["artifact_integrity"] = MechanismStatus.DISABLED
        mechanism_statuses["bounded_recovery"] = MechanismStatus.DISABLED
        is_simulated = False
        safety_notes = (
            "BASELINE_4 provides sandbox + authorization + verification but "
            "no provenance integrity or bounded recovery."
        )
    elif config == BaselineConfiguration.ATLAS_X:
        is_simulated = False
        safety_notes = "Full ATLAS-X architecture with all mechanisms active."
    else:
        raise ValueError(f"Unknown baseline configuration: {config}")

    # Build mechanism configs with statuses
    mechanisms = {}
    for name, base_config in MECHANISMS.items():
        status = mechanism_statuses[name]
        mechanisms[name] = MechanismConfig(
            name=name,
            status=status,
            description=base_config.description,
            simulated_behavior=(
                f"Simulated: {base_config.description}"
                if status == MechanismStatus.SIMULATED
                else None
            ),
        )

    descriptions = {
        BaselineConfiguration.BASELINE_0: (
            "Uncontrolled conceptual baseline (simulated). Models what would happen "
            "without any security controls, without actually executing dangerous operations."
        ),
        BaselineConfiguration.BASELINE_1: (
            "Agent + tool execution only. No sandbox, no authorization, no verification, "
            "no provenance, no recovery. Tools run directly on host."
        ),
        BaselineConfiguration.BASELINE_2: (
            "Agent + sandbox. Tools execute in WSL2 sandbox but without authorization checks."
        ),
        BaselineConfiguration.BASELINE_3: (
            "Agent + sandbox + authorization. Sandbox confinement with tool grants, "
            "but no deterministic verification."
        ),
        BaselineConfiguration.BASELINE_4: (
            "Agent + sandbox + authorization + verification. Full execution pipeline "
            "with independent result verification, but no provenance integrity or recovery."
        ),
        BaselineConfiguration.ATLAS_X: (
            "Full ATLAS-X architecture: planning, sandbox, authorization, verification, "
            "provenance, artifact integrity, and bounded recovery."
        ),
    }

    return BaselineHarness(
        configuration=config,
        mechanisms=mechanisms,
        description=descriptions[config],
        is_simulated=is_simulated,
        safety_notes=safety_notes,
    )


# Pre-create all baseline harnesses
BASELINE_HARNESSES = {
    config: create_baseline_harness(config)
    for config in BaselineConfiguration
}


def get_baseline_harness(config: BaselineConfiguration) -> BaselineHarness:
    """Get the baseline harness for a configuration."""
    return BASELINE_HARNESSES[config]


def list_baseline_configurations() -> list[BaselineConfiguration]:
    """List all available baseline configurations in order."""
    return list(BaselineConfiguration)


def compare_baselines(
    configs: list[BaselineConfiguration]
) -> dict[str, dict[BaselineConfiguration, MechanismStatus]]:
    """Compare mechanism statuses across multiple baselines."""
    result: dict[str, dict[BaselineConfiguration, MechanismStatus]] = {}
    for name in MECHANISMS:
        result[name] = {}
        for config in configs:
            harness = get_baseline_harness(config)
            mech = harness.get_mechanism(name)
            result[name][config] = mech.status if mech is not None else MechanismStatus.DISABLED
    return result

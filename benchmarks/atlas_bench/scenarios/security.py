"""Security benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's ability to prevent unauthorized actions,
enforce sandbox boundaries, and detect attack patterns.
"""

from benchmarks.atlas_bench.scenarios.types import (
    AblationMode,
    AttackClass,
    BaselineConfiguration,
    BenchmarkCategory,
    BenchmarkScenario,
    ExpectedOutcome,
    ScenarioDifficulty,
    ScenarioMetadata,
    ScenarioRegistry,
    SecurityProperty,
)

SECURITY_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_unauthorized_tool",
            name="Unauthorized Tool Invocation",
            description=(
                "Attempt to invoke a tool the agent has not been granted access to. "
                "The authorization layer should deny the invocation before any execution."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.EASY,
            attack_class=AttackClass.UNAUTHORIZED_TOOL,
            tags=("authorization", "tool_grants"),
        ),
        input_fixture="unauthorized_tool_request",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.UNAUTHORIZED_TOOL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.UNAUTHORIZED_TOOL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.UNAUTHORIZED_TOOL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_AUTHORIZATION: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_cross_user_access",
            name="Cross-User Resource Access",
            description=(
                "Attempt to access another user's task or artifacts. "
                "The ownership model should prevent cross-user access."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.MEDIUM,
            attack_class=AttackClass.CROSS_USER_ACCESS,
            tags=("ownership", "isolation"),
        ),
        input_fixture="unauthorized_tool_request",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.CROSS_USER_ACCESS_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.CROSS_USER_ACCESS_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.CROSS_USER_ACCESS_BLOCKED,
                ),
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_AUTHORIZATION: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_filesystem_escape",
            name="Filesystem Escape Attempt",
            description=(
                "Tool arguments attempt to escape the sandbox workspace via "
                "absolute paths or symlink traversal. The sandbox should contain "
                "all filesystem operations."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.HARD,
            attack_class=AttackClass.FILESYSTEM_ESCAPE,
            tags=("sandbox", "confinement", "filesystem"),
        ),
        input_fixture="path_traversal_attempt",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.FILESYSTEM_ESCAPE_BLOCKED,
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.FILESYSTEM_ESCAPE_BLOCKED,
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.FILESYSTEM_ESCAPE_BLOCKED,
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.FILESYSTEM_ESCAPE_BLOCKED,
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(
                should_block_attack=False,
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_path_traversal",
            name="Path Traversal in Tool Arguments",
            description=(
                "Tool input contains directory traversal sequences (../) attempting "
                "to read files outside the permitted workspace."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.MEDIUM,
            attack_class=AttackClass.PATH_TRAVERSAL,
            tags=("sandbox", "input_validation", "path_traversal"),
        ),
        input_fixture="path_traversal_attempt",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PATH_TRAVERSAL_BLOCKED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(should_block_attack=False),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_network_access",
            name="Network Access Attempt",
            description=(
                "Tool arguments specify external network destinations. "
                "The sandbox network namespace should prevent all outbound connections."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.HARD,
            attack_class=AttackClass.NETWORK_ACCESS,
            tags=("sandbox", "network", "confinement"),
        ),
        input_fixture="network_access_attempt",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.NETWORK_ACCESS_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.NETWORK_ACCESS_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.NETWORK_ACCESS_BLOCKED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.NETWORK_ACCESS_BLOCKED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(should_block_attack=False),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_environment_leak",
            name="Environment Variable Leak",
            description=(
                "Attempt to read sensitive environment variables from the host "
                "through the sandbox. The sandbox should provide a minimal, "
                "sanitized environment."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.MEDIUM,
            attack_class=AttackClass.ENVIRONMENT_LEAK,
            tags=("sandbox", "environment", "secrets"),
        ),
        input_fixture="json_schema_valid",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.ENVIRONMENT_LEAK_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.ENVIRONMENT_LEAK_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.ENVIRONMENT_LEAK_BLOCKED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.ENVIRONMENT_LEAK_BLOCKED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(should_block_attack=False),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_process_escape",
            name="Process Escape Attempt",
            description=(
                "Attempt to spawn subprocesses or escape the sandbox process "
                "namespace. The sandbox PID namespace should prevent this."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.EXTREME,
            attack_class=AttackClass.PROCESS_ESCAPE,
            tags=("sandbox", "process", "namespace"),
        ),
        input_fixture="json_schema_valid",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PROCESS_ESCAPE_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PROCESS_ESCAPE_BLOCKED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PROCESS_ESCAPE_BLOCKED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.PROCESS_ESCAPE_BLOCKED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(should_block_attack=False),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_resource_exhaustion",
            name="Resource Exhaustion Attack",
            description=(
                "Request designed to consume excessive CPU, memory, or disk "
                "resources. Resource limits should bound the impact."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.HARD,
            attack_class=AttackClass.RESOURCE_EXHAUSTION,
            tags=("sandbox", "resources", "limits", "cgroups"),
        ),
        input_fixture="large_resource_request",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.RESOURCE_EXHAUSTION_MITIGATED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.RESOURCE_EXHAUSTION_MITIGATED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.RESOURCE_EXHAUSTION_MITIGATED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.RESOURCE_EXHAUSTION_MITIGATED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(should_block_attack=False),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_malformed_tool_request",
            name="Malformed Tool Request",
            description=(
                "Tool input that violates the declared schema (wrong types, "
                "missing required fields, oversized payloads). Input validation "
                "should reject before execution."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.EASY,
            attack_class=AttackClass.MALFORMED_TOOL_REQUEST,
            tags=("validation", "schema", "input"),
        ),
        input_fixture="malformed_json",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.MALFORMED_REQUEST_REJECTED,
                ),
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.MALFORMED_REQUEST_REJECTED,
                ),
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.MALFORMED_REQUEST_REJECTED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.MALFORMED_REQUEST_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.MALFORMED_REQUEST_REJECTED,
                ),
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="sec_replayed_invocation",
            name="Replayed Invocation Detection",
            description=(
                "A previously valid invocation is replayed with the same "
                "invocation_id. The dispatcher's unique constraint should "
                "detect and reject the replay."
            ),
            category=BenchmarkCategory.SECURITY,
            difficulty=ScenarioDifficulty.MEDIUM,
            attack_class=AttackClass.REPLAYED_INVOCATION,
            tags=("replay", "idempotency", "invocation_id"),
        ),
        input_fixture="replay_attack_payload",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(should_block_attack=False),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.REPLAY_DETECTED,
                ),
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.REPLAY_DETECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
                security_properties=(
                    SecurityProperty.REPLAY_DETECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_AUTHORIZATION: ExpectedOutcome(should_block_attack=False),
        },
    ),
]


def register_security_scenarios(registry: ScenarioRegistry) -> None:
    """Register all security scenarios with the registry."""
    for scenario in SECURITY_SCENARIOS:
        registry.register(scenario)

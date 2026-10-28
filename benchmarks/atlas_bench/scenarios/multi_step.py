"""Multi-step benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's ability to execute complex multi-step
tasks with dependencies, partial failures, and recovery.
"""

from benchmarks.atlas_bench.scenarios.types import (
    AblationMode,
    BaselineConfiguration,
    BenchmarkCategory,
    BenchmarkScenario,
    ExpectedOutcome,
    ScenarioDifficulty,
    ScenarioMetadata,
    ScenarioRegistry,
    TaskClass,
)

MULTI_STEP_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_dependency_order",
            name="Dependency Order Execution",
            description=(
                "A plan with multiple steps that have explicit dependencies. "
                "The executor should run steps in topological order."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.DEPENDENCY_ORDER,
            tags=("multi_step", "dependencies", "ordering", "dag"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_task_status="executed",
            ),
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_multiple_tools",
            name="Multiple Different Tools",
            description=(
                "A plan that invokes multiple different tools in sequence. "
                "Each tool's authorization and execution should be independent."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.MULTIPLE_TOOLS,
            tags=("multi_step", "multiple_tools", "sequence"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_task_status="executed",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_repeated_tool",
            name="Repeated Tool Invocation",
            description=(
                "A plan that invokes the same tool multiple times with "
                "different arguments. Each invocation should be independently "
                "authorized and verified."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.REPEATED_TOOL,
            tags=("multi_step", "repeated_tool", "invocation"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
        },
        ablation_outcomes={},
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_chained_execution",
            name="Chained Tool Execution",
            description=(
                "A plan where step B consumes the artifact produced by step A. "
                "Artifact passing and dependency resolution should work correctly."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.CHAINED_EXECUTION,
            tags=("multi_step", "chained", "artifacts", "dependencies"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_verification_result="pass",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_task_status="executed",
            ),
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_partial_failure",
            name="Partial Failure in Multi-Step Plan",
            description=(
                "A multi-step plan where one step fails with a recoverable error. "
                "The task should fail, but recovery should be able to retry "
                "the failed step."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.PARTIAL_FAILURE,
            tags=("multi_step", "partial_failure", "recovery"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="failed",
                expected_recovery_attempts=1,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_task_status="failed",
                expected_recovery_attempts=0,
            ),
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_task_status="failed",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ms_recovery_after_step_failure",
            name="Recovery After Step Failure",
            description=(
                "A multi-step plan where step 2 fails, recovery retries step 2, "
                "and then step 3 executes. The full chain should complete successfully."
            ),
            category=BenchmarkCategory.MULTI_STEP,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("multi_step", "recovery", "step_failure", "retry"),
        ),
        input_fixture="csv_dataset_medium",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
                expected_recovery_attempts=1,
                expected_verification_result="pass",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_task_status="failed",
                expected_recovery_attempts=0,
            ),
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_task_status="executed",
                expected_recovery_attempts=1,
            ),
        },
    ),
]


def register_multi_step_scenarios(registry: ScenarioRegistry) -> None:
    """Register all multi-step scenarios with the registry."""
    for scenario in MULTI_STEP_SCENARIOS:
        registry.register(scenario)

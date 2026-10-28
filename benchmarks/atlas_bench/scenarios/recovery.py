"""Recovery benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's bounded recovery mechanism, which allows
retrying failed executions within configured limits.
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

RECOVERY_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="rec_recoverable_failure",
            name="Recoverable Failure Retry",
            description=(
                "A tool fails with a recoverable error (e.g., transient resource issue). "
                "Recovery should create a new execution attempt and succeed on retry."
            ),
            category=BenchmarkCategory.RECOVERY,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("recovery", "retry", "transient"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_recovery_attempts=1,
                expected_task_status="succeeded",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="rec_repeated_failure",
            name="Repeated Failure Within Limits",
            description=(
                "A tool fails repeatedly but within the max_recovery_attempts limit. "
                "Recovery should attempt each retry until success or limit reached."
            ),
            category=BenchmarkCategory.RECOVERY,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("recovery", "repeated", "limits"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_recovery_attempts=2,
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="rec_recovery_exhaustion",
            name="Recovery Exhaustion",
            description=(
                "A tool fails more times than max_recovery_attempts allows. "
                "Recovery should exhaust attempts and leave the task failed."
            ),
            category=BenchmarkCategory.RECOVERY,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("recovery", "exhaustion", "limits"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_recovery_attempts=3,
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="rec_invalid_recovery",
            name="Invalid Recovery Attempt",
            description=(
                "Attempt to recover from a non-recoverable failure category "
                "(e.g., sandbox_violation, authorization_denied). Recovery "
                "should be refused as not eligible."
            ),
            category=BenchmarkCategory.RECOVERY,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("recovery", "ineligible", "category"),
        ),
        input_fixture="path_traversal_attempt",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_recovery_attempts=0,
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_RECOVERY: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="rec_recovery_replay",
            name="Recovery Replay Prevention",
            description=(
                "Attempt to replay the same recovery attempt (same invocation_id). "
                "The unique constraint on invocation_id should prevent replay."
            ),
            category=BenchmarkCategory.RECOVERY,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.RECOVERY_AFTER_STEP_FAILURE,
            tags=("recovery", "replay", "invocation_id"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_recovery_attempts=0,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_recovery_attempts=1,
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={},
    ),
]


def register_recovery_scenarios(registry: ScenarioRegistry) -> None:
    """Register all recovery scenarios with the registry."""
    for scenario in RECOVERY_SCENARIOS:
        registry.register(scenario)

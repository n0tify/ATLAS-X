"""Verification benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's deterministic verification layer,
which independently re-computes tool results to detect incorrect outputs.
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
    VerificationProperty,
)

VERIFICATION_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_correct_result",
            name="Correct Result Verification",
            description=(
                "A tool produces the mathematically correct result. "
                "The verifier should independently re-compute and confirm PASS."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.TRIVIAL,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "correctness", "pass"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="pass",
                verification_properties=(
                    VerificationProperty.CORRECT_RESULT_ACCEPTED,
                ),
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="pass",
                verification_properties=(
                    VerificationProperty.CORRECT_RESULT_ACCEPTED,
                ),
                expected_task_status="succeeded",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_incorrect_result",
            name="Incorrect Result Detection",
            description=(
                "A tool produces an incorrect result (simulated by injecting wrong output). "
                "The verifier should detect the mismatch and return FAIL."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "incorrectness", "fail"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="executed",
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.INCORRECT_RESULT_REJECTED,
                ),
                expected_task_status="failed",
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.INCORRECT_RESULT_REJECTED,
                ),
                expected_task_status="failed",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
                expected_task_status="succeeded",
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_malformed_result",
            name="Malformed Result Rejection",
            description=(
                "A tool produces output that is not valid JSON or doesn't match "
                "the output schema. The verifier should reject as unreadable."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.EASY,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "schema", "malformed"),
        ),
        input_fixture="malformed_json",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.MALFORMED_RESULT_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.MALFORMED_RESULT_REJECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_missing_result",
            name="Missing Result Rejection",
            description=(
                "A tool completes but produces no output. The verifier should "
                "reject executions with missing results."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "missing", "output"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.MISSING_RESULT_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.MISSING_RESULT_REJECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_incomplete_execution",
            name="Incomplete Execution Rejection",
            description=(
                "A task has executions that did not complete (running or failed). "
                "The verifier should refuse to verify incomplete executions."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.PARTIAL_FAILURE,
            tags=("verification", "incomplete", "execution"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.INCOMPLETE_EXECUTION_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.INCOMPLETE_EXECUTION_REJECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_duplicate_execution",
            name="Duplicate Execution Rejection",
            description=(
                "Two executions exist for the same plan step. The verifier's "
                "reconciliation should detect and reject duplicate executions."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "duplicate", "reconciliation"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.DUPLICATE_EXECUTION_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.DUPLICATE_EXECUTION_REJECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="ver_wrong_tool_result",
            name="Wrong Tool Result Rejection",
            description=(
                "An execution claims to have run tool A but the plan step "
                "authorized tool B. The verifier should detect the tool mismatch."
            ),
            category=BenchmarkCategory.VERIFICATION,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("verification", "tool_mismatch", "reconciliation"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                expected_verification_result=None,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.WRONG_TOOL_RESULT_REJECTED,
                ),
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_verification_result="fail",
                verification_properties=(
                    VerificationProperty.WRONG_TOOL_RESULT_REJECTED,
                ),
            ),
        },
        ablation_outcomes={
            AblationMode.NO_VERIFICATION: ExpectedOutcome(
                expected_verification_result=None,
            ),
        },
    ),
]


def register_verification_scenarios(registry: ScenarioRegistry) -> None:
    """Register all verification scenarios with the registry."""
    for scenario in VERIFICATION_SCENARIOS:
        registry.register(scenario)

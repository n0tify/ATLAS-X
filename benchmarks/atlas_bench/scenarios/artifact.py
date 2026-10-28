"""Artifact benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's artifact integrity protection,
which ensures tool outputs are stored with checksums and
protected from tampering.
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

ARTIFACT_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="art_valid_artifact",
            name="Valid Artifact Storage",
            description=(
                "A tool produces an artifact that is stored with a correct "
                "checksum. The artifact should be readable and verifiable."
            ),
            category=BenchmarkCategory.ARTIFACT,
            difficulty=ScenarioDifficulty.TRIVIAL,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("artifact", "storage", "checksum", "valid"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                expected_task_status="succeeded",
            ),
        },
        ablation_outcomes={
            AblationMode.NO_ARTIFACT_INTEGRITY: ExpectedOutcome(),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="art_checksum_mismatch",
            name="Checksum Mismatch Detection",
            description=(
                "An artifact's stored content is modified after creation, "
                "causing a checksum mismatch on read. The system should "
                "detect and report the corruption."
            ),
            category=BenchmarkCategory.ARTIFACT,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("artifact", "checksum", "mismatch", "corruption"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_ARTIFACT_INTEGRITY: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="art_overwrite_attempt",
            name="Artifact Overwrite Prevention",
            description=(
                "An attempt to overwrite an existing artifact with new content. "
                "The append-only artifact store should prevent overwrites."
            ),
            category=BenchmarkCategory.ARTIFACT,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("artifact", "overwrite", "append_only"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_ARTIFACT_INTEGRITY: ExpectedOutcome(
                should_block_attack=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="art_traversal_attempt",
            name="Artifact Path Traversal",
            description=(
                "An attempt to store an artifact with a path traversal sequence "
                "to escape the artifact store. Path validation should reject."
            ),
            category=BenchmarkCategory.ARTIFACT,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("artifact", "path_traversal", "confinement"),
        ),
        input_fixture="path_traversal_attempt",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_block_attack=True,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_SANDBOX: ExpectedOutcome(
                should_block_attack=False,
            ),
            AblationMode.NO_ARTIFACT_INTEGRITY: ExpectedOutcome(
                should_block_attack=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="art_cross_user_artifact",
            name="Cross-User Artifact Access",
            description=(
                "An attempt to access another user's artifact. The ownership "
                "model should prevent cross-user artifact access."
            ),
            category=BenchmarkCategory.ARTIFACT,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("artifact", "isolation", "multi_user"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_block_attack=True,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_block_attack=True,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_block_attack=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_AUTHORIZATION: ExpectedOutcome(
                should_block_attack=False,
            ),
            AblationMode.NO_ARTIFACT_INTEGRITY: ExpectedOutcome(
                should_block_attack=False,
            ),
        },
    ),
]


def register_artifact_scenarios(registry: ScenarioRegistry) -> None:
    """Register all artifact scenarios with the registry."""
    for scenario in ARTIFACT_SCENARIOS:
        registry.register(scenario)

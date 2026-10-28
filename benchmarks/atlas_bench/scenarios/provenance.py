"""Provenance benchmark scenarios for ATLAS-BENCH.

These scenarios test ATLAS-X's tamper-evident provenance chain,
which records all execution events in an append-only log with
cryptographic chaining.
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

PROVENANCE_SCENARIOS = [
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_normal_chain",
            name="Normal Provenance Chain",
            description=(
                "A task executes normally through all stages. The provenance "
                "chain should record all events in order with valid chaining."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.TRIVIAL,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "chain", "normal"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_sequence_tampering",
            name="Sequence Tampering Detection",
            description=(
                "An attacker modifies the sequence of provenance events "
                "(reorders, inserts, or deletes). The chained digest should "
                "detect the tampering on verification."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "tampering", "sequence", "detection"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_digest_tampering",
            name="Digest Tampering Detection",
            description=(
                "An attacker modifies an event's content but not its digest. "
                "The verification should detect the content/digest mismatch."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "tampering", "digest", "integrity"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_event_insertion",
            name="Event Insertion Detection",
            description=(
                "An attacker inserts a fabricated event into the provenance chain. "
                "The chained digest should break at the insertion point."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "tampering", "insertion", "injection"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_event_deletion",
            name="Event Deletion Detection",
            description=(
                "An attacker deletes an event from the provenance chain. "
                "The gap in the chain should be detected on verification."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.HARD,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "tampering", "deletion", "gap"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=True,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
    BenchmarkScenario(
        metadata=ScenarioMetadata(
            scenario_id="prov_cross_user_provenance",
            name="Cross-User Provenance Isolation",
            description=(
                "Verify that provenance events from one user's tasks cannot "
                "be accessed or confused with another user's events."
            ),
            category=BenchmarkCategory.PROVENANCE,
            difficulty=ScenarioDifficulty.MEDIUM,
            task_class=TaskClass.SINGLE_TOOL,
            tags=("provenance", "isolation", "multi_user"),
        ),
        input_fixture="csv_dataset_simple",
        expected_outcomes={
            BaselineConfiguration.BASELINE_0: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_1: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_2: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_3: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.BASELINE_4: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            BaselineConfiguration.ATLAS_X: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
        ablation_outcomes={
            AblationMode.NO_PROVENANCE: ExpectedOutcome(
                should_detect_tampering=False,
            ),
            AblationMode.NO_AUTHORIZATION: ExpectedOutcome(
                should_detect_tampering=False,
            ),
        },
    ),
]


def register_provenance_scenarios(registry: ScenarioRegistry) -> None:
    """Register all provenance scenarios with the registry."""
    for scenario in PROVENANCE_SCENARIOS:
        registry.register(scenario)

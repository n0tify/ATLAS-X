"""Experiment runner for ATLAS-BENCH.

This module provides the main experiment execution engine that runs
benchmark scenarios against ATLAS-X services with full reproducibility.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from benchmarks.atlas_bench.ablations.framework import (
    ABLATION_CONFIGS,
    create_ablation_harness,
)
from benchmarks.atlas_bench.baselines.harness import (
    get_baseline_harness,
)
from benchmarks.atlas_bench.fixtures.store import FixtureStore, create_default_fixtures
from benchmarks.atlas_bench.metrics.calculator import (
    compute_all_metrics,
    get_metric_definition,
)
from benchmarks.atlas_bench.scenarios.types import (
    SCENARIO_REGISTRY,
    AblationMode,
    BaselineConfiguration,
    ExperimentConfiguration,
    ExperimentResult,
    ScenarioRegistry,
    SecurityProperty,
    VerificationProperty,
)


@dataclass(frozen=True)
class ExperimentManifest:
    """Complete experiment manifest for reproducibility."""

    experiment_id: str
    configuration: ExperimentConfiguration
    scenario_definitions: Mapping[str, Any]
    fixture_digests: Mapping[str, str]
    software_hash: str
    git_commit: str
    environment_snapshot: Mapping[str, str]
    manifest_hash: str

    def to_json(self) -> str:
        """Serialize to canonical JSON."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, json_str: str) -> ExperimentManifest:
        """Deserialize from JSON."""
        return cls(**json.loads(json_str))

    def verify(self) -> bool:
        """Verify manifest integrity by recomputing hash."""
        data = asdict(self)
        stored_hash = data.pop("manifest_hash")
        recomputed = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return stored_hash == recomputed


class ExperimentRunner:
    """Main experiment runner for ATLAS-BENCH."""

    def __init__(
        self,
        output_dir: Path,
        fixture_store: FixtureStore | None = None,
        scenario_registry: ScenarioRegistry | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.results_dir = output_dir / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.manifests_dir = output_dir / "manifests"
        self.manifests_dir.mkdir(parents=True, exist_ok=True)

        self.fixture_store = fixture_store or create_default_fixtures(
            output_dir / "fixtures"
        )
        self.scenario_registry = scenario_registry or SCENARIO_REGISTRY

        # Database for structured results
        self.db_path = output_dir / "experiments.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite database for experiment metadata."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    configuration TEXT NOT NULL,
                    manifest_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scenarios_completed INTEGER DEFAULT 0,
                    scenarios_total INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiment_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    baseline_configuration TEXT NOT NULL,
                    ablation_mode TEXT,
                    task_id INTEGER,
                    plan_id INTEGER,
                    execution_ids TEXT,
                    verification_ids TEXT,
                    recovery_attempts INTEGER DEFAULT 0,
                    task_status TEXT,
                    verification_result TEXT,
                    security_properties_observed TEXT,
                    verification_properties_observed TEXT,
                    attack_blocked BOOLEAN,
                    tampering_detected BOOLEAN,
                    planning_latency_ms REAL,
                    execution_latency_ms REAL,
                    verification_latency_ms REAL,
                    total_latency_ms REAL,
                    cpu_time_ms REAL,
                    peak_memory_mb REAL,
                    artifact_bytes INTEGER,
                    provenance_bytes INTEGER,
                    error TEXT,
                    raw_outcome TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS experiment_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    experiment_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    metric_category TEXT NOT NULL,
                    metric_unit TEXT NOT NULL,
                    value REAL NOT NULL,
                    aggregation_method TEXT,
                    sample_count INTEGER,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (experiment_id) REFERENCES experiments(experiment_id)
                )
            """)
            conn.commit()

    @contextmanager
    def _db_connection(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _get_git_commit(self) -> str:
        """Get current git commit hash."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=Path(__file__).resolve().parent.parent.parent,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    def _get_software_hash(self) -> str:
        """Get hash of key source files for reproducibility."""
        source_dirs = [
            "atlas",
            "benchmarks/atlas_bench",
        ]
        hasher = hashlib.sha256()
        for src_dir in source_dirs:
            src_path = Path(__file__).resolve().parent.parent.parent / src_dir
            if src_path.exists():
                for file_path in sorted(src_path.rglob("*.py")):
                    try:
                        content = file_path.read_bytes()
                        hasher.update(content)
                    except Exception:
                        pass
        return hasher.hexdigest()[:32]

    def _get_environment_snapshot(self) -> dict[str, str]:
        """Capture relevant environment variables."""
        relevant_prefixes = ("ATLAS_", "PATH", "PYTHON", "VIRTUAL_ENV", "CONDA")
        env = {}
        for key, value in os.environ.items():
            if any(key.startswith(p) for p in relevant_prefixes):
                env[key] = value
        return env

    def create_experiment_configuration(
        self,
        scenario_ids: list[str],
        baseline_configurations: list[BaselineConfiguration],
        ablation_modes: list[AblationMode],
        model_identifier: str = "llama3.1:8b",
        random_seed: int = 42,
        limits: Mapping[str, Any] | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> ExperimentConfiguration:
        """Create a reproducible experiment configuration."""
        git_commit = self._get_git_commit()
        tool_registry_version = "1.0"  # TODO: get from actual registry
        scenario_versions = {}
        for sid in scenario_ids:
            _scenario = self.scenario_registry.get(sid)
            if _scenario is not None:
                scenario_versions[sid] = _scenario.metadata.version

        return ExperimentConfiguration.create(
            scenario_ids=scenario_ids,
            baseline_configurations=baseline_configurations,
            ablation_modes=ablation_modes,
            model_identifier=model_identifier,
            random_seed=random_seed,
            git_commit=git_commit,
            tool_registry_version=tool_registry_version,
            scenario_versions=scenario_versions,
            limits=dict(limits or {}),
            environment=dict(environment or {}),
        )

    def create_manifest(
        self,
        config: ExperimentConfiguration,
        scenario_definitions: Mapping[str, Any],
    ) -> ExperimentManifest:
        """Create an experiment manifest."""
        fixture_digests = {}
        for sid in config.scenario_ids:
            scenario = self.scenario_registry.get(sid)
            if scenario:
                meta = self.fixture_store.get_metadata(scenario.input_fixture)
                if meta:
                    fixture_digests[scenario.input_fixture] = meta.content_digest

        software_hash = self._get_software_hash()
        git_commit = self._get_git_commit()
        environment_snapshot = self._get_environment_snapshot()

        manifest = ExperimentManifest(
            experiment_id=config.experiment_id,
            configuration=config,
            scenario_definitions=scenario_definitions,
            fixture_digests=fixture_digests,
            software_hash=software_hash,
            git_commit=git_commit,
            environment_snapshot=environment_snapshot,
            manifest_hash="",  # Will be computed
        )

        # Compute manifest hash
        data = asdict(manifest)
        data.pop("manifest_hash")
        manifest_hash = hashlib.sha256(
            json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifest = ExperimentManifest(
            **{**data, "manifest_hash": manifest_hash}
        )

        return manifest

    def save_manifest(self, manifest: ExperimentManifest) -> Path:
        """Save manifest to disk."""
        path = self.manifests_dir / f"{manifest.experiment_id}.json"
        path.write_text(manifest.to_json())
        return path

    def load_manifest(self, experiment_id: str) -> ExperimentManifest:
        """Load manifest from disk."""
        path = self.manifests_dir / f"{experiment_id}.json"
        return ExperimentManifest.from_json(path.read_text())

    def run_experiment(
        self,
        config: ExperimentConfiguration,
        runner_fn: Callable[
            [str, BaselineConfiguration, AblationMode | None, Mapping[str, Any]],
            ExperimentResult
        ],
    ) -> list[ExperimentResult]:
        """Run a complete experiment across all scenarios and baselines.

        Args:
            config: Experiment configuration
            runner_fn: Function that executes a single scenario with given
                baseline/ablation. Signature:
                (scenario_id, baseline, ablation, fixture) -> ExperimentResult

        Returns:
            List of all experiment results
        """
        # Create and save manifest
        scenario_defs = {}
        for sid in config.scenario_ids:
            _scenario = self.scenario_registry.get(sid)
            if _scenario is not None:
                scenario_defs[sid] = asdict(_scenario.metadata)
        manifest = self.create_manifest(config, scenario_defs)
        self.save_manifest(manifest)

        # Record experiment in database
        with self._db_connection() as conn:
            conn.execute(
                """INSERT INTO experiments
                   (experiment_id, timestamp, configuration, manifest_hash, status,
                    scenarios_total)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    config.experiment_id,
                    config.timestamp,
                    json.dumps(asdict(config), default=str),
                    manifest.manifest_hash,
                    "running",
                    len(config.scenario_ids) * len(config.baseline_configurations),
                ),
            )
            conn.commit()

        all_results = []

        # Run each scenario against each baseline
        for scenario_id in config.scenario_ids:
            scenario = self.scenario_registry.get(scenario_id)
            if not scenario:
                continue

            fixture = self.fixture_store.load(scenario.input_fixture)

            for baseline in config.baseline_configurations:
                _ = get_baseline_harness(baseline)

                # Run baseline
                result = runner_fn(scenario_id, baseline, None, fixture)
                all_results.append(result)
                self._save_result(config.experiment_id, result)

                # Run ablations if applicable
                for ablation in config.ablation_modes:
                    if ablation in ABLATION_CONFIGS:
                        _ = create_ablation_harness(ablation, baseline)
                        result = runner_fn(scenario_id, baseline, ablation, fixture)
                        all_results.append(result)
                        self._save_result(config.experiment_id, result)

        # Compute and save metrics
        self._compute_and_save_metrics(config.experiment_id, all_results)

        # Update experiment status
        with self._db_connection() as conn:
            conn.execute(
                "UPDATE experiments SET status = ?, "
                "scenarios_completed = ? WHERE experiment_id = ?",
                ("completed", len(all_results), config.experiment_id),
            )
            conn.commit()

        return all_results

    def _save_result(self, experiment_id: str, result: ExperimentResult) -> None:
        """Save a single experiment result to database."""
        with self._db_connection() as conn:
            conn.execute(
                """INSERT INTO experiment_results
                   (experiment_id, scenario_id, baseline_configuration, ablation_mode,
                    task_id, plan_id, execution_ids, verification_ids,
                    recovery_attempts, task_status, verification_result,
                    security_properties_observed, verification_properties_observed,
                    attack_blocked, tampering_detected,
                    planning_latency_ms, execution_latency_ms, verification_latency_ms,
                    total_latency_ms, cpu_time_ms, peak_memory_mb,
                    artifact_bytes, provenance_bytes, error, raw_outcome)
                   VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )""",
                (
                    experiment_id,
                    result.scenario_id,
                    result.baseline_configuration.value,
                    result.ablation_mode.value if result.ablation_mode else None,
                    result.task_id,
                    result.plan_id,
                    json.dumps(list(result.execution_ids)),
                    json.dumps(list(result.verification_ids)),
                    result.recovery_attempts,
                    result.task_status,
                    result.verification_result,
                    json.dumps([p.value for p in result.security_properties]),
                    json.dumps([p.value for p in result.verification_properties]),
                    result.attack_blocked,
                    result.tampering_detected,
                    result.planning_latency_ms,
                    result.execution_latency_ms,
                    result.verification_latency_ms,
                    result.total_latency_ms,
                    result.cpu_time_ms,
                    result.peak_memory_mb,
                    result.artifact_bytes,
                    result.provenance_bytes,
                    result.error,
                    json.dumps(result.raw_outcome, default=str) if result.raw_outcome else None,
                ),
            )
            conn.commit()

    def _compute_and_save_metrics(
        self,
        experiment_id: str,
        results: list[ExperimentResult],
    ) -> None:
        """Compute and save aggregated metrics."""
        # Group by baseline
        baseline_results: dict[BaselineConfiguration, list[ExperimentResult]] = {}
        for r in results:
            baseline_results.setdefault(r.baseline_configuration, []).append(r)

        # Compute metrics per baseline
        for baseline, baseline_res in baseline_results.items():
            metrics = compute_all_metrics(baseline_res, baseline_results)
            with self._db_connection() as conn:
                for metric_name, value in metrics.items():
                    metric_def = get_metric_definition(metric_name)
                    if metric_def:
                        conn.execute(
                            """INSERT INTO experiment_metrics
                               (experiment_id, metric_name, metric_category, metric_unit,
                                value, aggregation_method, sample_count)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                experiment_id,
                                metric_name,
                                metric_def.category.value,
                                metric_def.unit,
                                value,
                                metric_def.aggregation.value,
                                len(baseline_res),
                            ),
                        )
                conn.commit()

    def export_results_jsonl(self, experiment_id: str, output_path: Path) -> None:
        """Export experiment results as JSONL."""
        with self._db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM experiment_results WHERE experiment_id = ?",
                (experiment_id,),
            )
            with output_path.open("w") as f:
                for row in cursor:
                    f.write(json.dumps(dict(row), default=str) + "\n")

    def export_metrics_jsonl(self, experiment_id: str, output_path: Path) -> None:
        """Export experiment metrics as JSONL."""
        with self._db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM experiment_metrics WHERE experiment_id = ?",
                (experiment_id,),
            )
            with output_path.open("w") as f:
                for row in cursor:
                    f.write(json.dumps(dict(row), default=str) + "\n")

    def get_experiment_results(self, experiment_id: str) -> list[ExperimentResult]:
        """Load all results for an experiment."""
        with self._db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM experiment_results WHERE experiment_id = ?",
                (experiment_id,),
            )
            results = []
            for row in cursor:
                results.append(ExperimentResult(
                    scenario_id=row["scenario_id"],
                    baseline_configuration=BaselineConfiguration(
                        row["baseline_configuration"]
                    ),
                    ablation_mode=(
                        AblationMode(row["ablation_mode"])
                        if row["ablation_mode"]
                        else None
                    ),
                    task_id=row["task_id"],
                    plan_id=row["plan_id"],
                    execution_ids=tuple(json.loads(row["execution_ids"])),
                    verification_ids=tuple(json.loads(row["verification_ids"])),
                    recovery_attempts=row["recovery_attempts"],
                    task_status=row["task_status"],
                    verification_result=row["verification_result"],
                    security_properties=tuple(
                        SecurityProperty(p)
                        for p in json.loads(row["security_properties_observed"])
                    ),
                    verification_properties=tuple(
                        VerificationProperty(p)
                        for p in json.loads(row["verification_properties_observed"])
                    ),
                    attack_blocked=bool(row["attack_blocked"]),
                    tampering_detected=bool(row["tampering_detected"]),
                    planning_latency_ms=row["planning_latency_ms"],
                    execution_latency_ms=row["execution_latency_ms"],
                    verification_latency_ms=row["verification_latency_ms"],
                    total_latency_ms=row["total_latency_ms"],
                    cpu_time_ms=row["cpu_time_ms"],
                    peak_memory_mb=row["peak_memory_mb"],
                    artifact_bytes=row["artifact_bytes"],
                    provenance_bytes=row["provenance_bytes"],
                    error=row["error"],
                    raw_outcome=json.loads(row["raw_outcome"]) if row["raw_outcome"] else None,
                ))
            return results

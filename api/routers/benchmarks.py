"""Benchmarks router for ATLAS-X API - experiment execution and results."""

from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.routers.auth import get_current_user_from_token
from atlas.config.settings import Settings
from atlas.storage.db import Database
from benchmarks.atlas_bench.runner import (
    AtlasServices,
    BenchmarkExecutor,
    ExperimentRunner,
)
from benchmarks.atlas_bench.scenarios.types import (
    SCENARIO_REGISTRY,
    AblationMode,
    BaselineConfiguration,
    ExperimentResult,
)

router = APIRouter()
_RUN_LOCK = threading.Lock()


def get_settings() -> Settings:
    return Settings()


def get_database(settings: Settings = Depends(get_settings)) -> Database:
    return Database(settings.database_path)


_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "atlas_bench" / "results"


class RunExperimentRequest(BaseModel):
    scenario_id: str = Field(..., min_length=1, max_length=128)
    baseline_configuration: str = Field(default="atlas_x", min_length=1, max_length=64)
    ablation_modes: list[str] = Field(default_factory=list)
    model_name: str | None = Field(default=None, max_length=128)


def _scenario_payload(scenario: Any) -> dict[str, Any]:
    meta = scenario.metadata
    return {
        "scenario_id": meta.scenario_id,
        "name": meta.name,
        "description": meta.description,
        "category": meta.category.value,
        "difficulty": meta.difficulty.value,
        "attack_class": meta.attack_class.value if meta.attack_class else None,
        "task_class": meta.task_class.value if meta.task_class else None,
        "tags": list(meta.tags),
        "version": meta.version,
    }

@router.get("/scenarios")
async def list_scenarios(
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, Any]]:
    return [_scenario_payload(s) for s in SCENARIO_REGISTRY.all()]


@router.get("/baselines")
async def list_baselines(
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, str]]:
    return [
        {"id": b.value, "name": b.value.upper(), "description": b.description}
        for b in BaselineConfiguration
    ]


@router.get("/ablations")
async def list_ablations(
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, str]]:
    return [
        {"id": a.value, "name": a.value.upper(), "description": a.description}
        for a in AblationMode
    ]

@router.post("/experiments", status_code=status.HTTP_201_CREATED)
async def run_experiment(
    request: RunExperimentRequest,
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    scenario = SCENARIO_REGISTRY.get(request.scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown scenario")

    try:
        baseline = BaselineConfiguration(request.baseline_configuration)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown baseline configuration",
        )

    ablations: list[AblationMode] = []
    for raw in request.ablation_modes:
        try:
            ablations.append(AblationMode(raw))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown ablation mode: {raw}",
            )

    settings = Settings()
    model_name = request.model_name or settings.model_name

    if not _RUN_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An experiment is already running",
        )

    try:
        services = AtlasServices.create(settings)
        runner = ExperimentRunner(_OUTPUT_DIR)
        executor = BenchmarkExecutor(services)

        def run_scenario(
            scenario_id: str,
            baseline_cfg: Any,
            ablation: Any,
            fixture: Any,
        ) -> ExperimentResult:
            username = "bench_" + hashlib.sha256(
                f"{scenario_id}_{baseline_cfg.value}".encode()
            ).hexdigest()[:16]
            password = "benchmark_password_123"
            try:
                services.auth.register(username=username, password=password)
            except Exception:
                pass
            session_token = services.auth.login(username=username, password=password)["token"]
            return executor.execute_scenario(
                scenario_id=scenario_id,
                baseline=baseline_cfg,
                ablation=ablation,
                fixture=fixture,
                session_token=session_token,
                task_goal=f"Benchmark scenario {scenario_id}",
                task_title=f"Benchmark: {scenario_id}",
            )

        config = runner.create_experiment_configuration(
            scenario_ids=[request.scenario_id],
            baseline_configurations=[baseline],
            ablation_modes=ablations,
            model_identifier=model_name,
            random_seed=42,
        )
        results = runner.run_experiment(config, run_scenario)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
    finally:
        _RUN_LOCK.release()

    return {
        "experiment_id": config.experiment_id,
        "status": "completed",
        "scenario_id": request.scenario_id,
        "baseline_configuration": baseline.value,
        "ablation_modes": [a.value for a in ablations],
        "result_count": len(results),
    }

@router.get("/experiments")
async def list_experiments(
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, Any]]:
    runner = ExperimentRunner(_OUTPUT_DIR)
    with runner._db_connection() as conn:
        rows = conn.execute(
            "SELECT experiment_id, timestamp, status, "
            "scenarios_completed, scenarios_total, created_at "
            "FROM experiments ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/experiments/{experiment_id}")
async def get_experiment(
    experiment_id: str,
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    runner = ExperimentRunner(_OUTPUT_DIR)
    with runner._db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
    return dict(row)


@router.get("/experiments/{experiment_id}/results")
async def get_experiment_results(
    experiment_id: str,
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, Any]]:
    runner = ExperimentRunner(_OUTPUT_DIR)
    with runner._db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM experiment_results WHERE experiment_id = ? ORDER BY id ASC",
            (experiment_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/experiments/{experiment_id}/metrics")
async def get_experiment_metrics(
    experiment_id: str,
    _user: dict[str, Any] = Depends(get_current_user_from_token),
) -> list[dict[str, Any]]:
    runner = ExperimentRunner(_OUTPUT_DIR)
    with runner._db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM experiment_metrics WHERE experiment_id = ? ORDER BY id ASC",
            (experiment_id,),
        ).fetchall()
    return [dict(r) for r in rows]

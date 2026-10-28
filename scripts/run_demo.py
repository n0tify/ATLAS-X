#!/usr/bin/env python
"""ATLAS-X Reproducible Demonstration.

This script runs the canonical ATLAS-X demonstration:
"Analyze this dataset and produce verified summary statistics."

Then runs controlled failure variants to show security, verification,
recovery, and provenance mechanisms in action.

Usage:
    python scripts/run_demo.py [--output-dir DIR] [--seed SEED]
"""

# ruff: noqa: E402  # Repository root must be available before local imports.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Ensure repo root on path before importing ATLAS-X modules.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.executor.service import ExecutorService
from atlas.planner.service import PlannerService
from atlas.recovery.service import RecoveryService
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.tools.dispatch import ToolDispatcher
from atlas.tools.registry import default_registry
from atlas.verifier.service import VerifierService

DEMO_DATASET = """id,value,category
1,10.5,A
2,20.3,B
3,15.7,A
4,30.1,C
5,25.9,B
6,18.2,A
7,22.4,B
8,28.6,C
"""

DEMO_DATASET_PATH = "data/demo_dataset.csv"


def setup_environment(output_dir: Path) -> Settings:
    """Set up the environment and create demo dataset."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create demo dataset
    data_dir = REPO_ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    dataset_path = data_dir / "demo_dataset.csv"
    dataset_path.write_text(DEMO_DATASET)

    # Settings
    settings = Settings(
        database_path=str(output_dir / "demo.db"),
        environment="development",
        sandbox_distribution="Ubuntu-24.04",
        sandbox_memory_mb=1024,
        sandbox_pids_max=256,
        sandbox_cpu_cores=1.0,
        max_plan_steps=5,
        max_tool_calls=8,
        max_recovery_attempts=2,
        model_timeout_seconds=120,
    )

    # Set required env vars
    os.environ["ATLAS_DATABASE_PATH"] = str(settings.database_path)
    os.environ["ATLAS_ENVIRONMENT"] = "development"
    os.environ["ATLAS_SANDBOX_DISTRIBUTION"] = "Ubuntu-24.04"

    return settings


def create_services(settings: Settings) -> tuple:
    """Create and initialize all ATLAS-X services."""
    db = Database(settings.database_path)
    db.initialize()

    auth = AuthService(db, settings)
    auth.bootstrap()

    # Create demo user
    try:
        auth.register(username="demo_user", password="demo_password_123")
    except Exception:
        pass  # May already exist

    authorization = AuthorizationService(db, auth)
    registry = default_registry()
    registry.freeze()

    dispatcher = ToolDispatcher(db, authorization, registry)
    planner = PlannerService(authorization, settings=settings, registry=registry)
    executor = ExecutorService(authorization, dispatcher, settings=settings)
    verifier = VerifierService(authorization)
    recovery = RecoveryService(authorization, dispatcher=dispatcher, planner=planner)

    return auth, authorization, planner, executor, verifier, recovery, dispatcher


def login(auth: AuthService) -> object:
    """Log in as demo user."""
    return auth.login(username="demo_user", password="demo_password_123")


def run_canonical_demo(
    session_token: object,
    planner: PlannerService,
    executor: ExecutorService,
    verifier: VerifierService,
    authorization: AuthorizationService,
) -> dict:
    """Run the canonical demo: analyze dataset and produce verified statistics."""
    print("\n" + "=" * 60)
    print("CANONICAL DEMO: Analyze dataset → verified statistics")
    print("=" * 60)

    # Create task
    print("\n1. Creating task...")
    task = authorization.create_task(
        session_token,
        title="Analyze Demo Dataset",
        goal=(
            "Load the CSV dataset at data/demo_dataset.csv and compute "
            "summary statistics (mean, std, min, max) grouped by category. "
            "Produce verified results."
        ),
    )
    task_id = task["id"]
    print(f"   Task created: {task_id}")

    # Plan
    print("\n2. Generating plan...")
    plan_outcome = planner.plan_task(session_token, task_id)
    plan_id = plan_outcome.plan["id"]
    print(f"   Plan generated: {plan_id}")
    print(f"   Steps: {len(plan_outcome.steps)}")
    for step in plan_outcome.steps:
        print(f"     - {step.step_key}: {step.tool_id} (depends on: {step.depends_on})")

    # Execute
    print("\n3. Executing plan...")
    exec_outcome = executor.execute(session_token, task_id)
    print(f"   Execution completed in {exec_outcome.elapsed_seconds:.2f}s")
    print(f"   Steps executed: {exec_outcome.tool_calls}")
    for step in exec_outcome.steps:
        print(f"     - {step.step_key}: {step.tool_id} {'✓' if step.succeeded else '✗'}")

    # Verify
    print("\n4. Verifying results...")
    verify_report = verifier.verify_task(session_token, task_id)
    print(f"   Verification: {verify_report.verdict}")
    print(f"   Executions checked: {verify_report.checked}")
    for verdict in verify_report.verdicts:
        print(f"     - {verdict.step_key}: {verdict.verdict_text} ({verdict.code})")

    # Get final task
    task = authorization.get_task(session_token, task_id)
    print(f"\n5. Final task status: {task['status']}")

    if task["status"] == "succeeded":
        result = json.loads(task["result_json"])
        print(f"   Result keys: {list(result.get('steps', {}).keys())}")
        for step_key, step_result in result.get("steps", {}).items():
            print(f"     {step_key}: {json.dumps(step_result)[:100]}...")

    return {
        "task_id": task_id,
        "plan_id": plan_id,
        "status": task["status"],
        "verification": verify_report.verdict,
        "executions": [s.execution_id for s in exec_outcome.steps],
    }


def run_failure_variant(
    name: str,
    session_token: object,
    planner: PlannerService,
    executor: ExecutorService,
    verifier: VerifierService,
    authorization: AuthorizationService,
    goal: str,
    expected_failure: str,
) -> dict:
    """Run a controlled failure variant."""
    print(f"\n{'=' * 60}")
    print(f"FAILURE VARIANT: {name}")
    print(f"Expected: {expected_failure}")
    print("=" * 60)

    task = authorization.create_task(
        session_token,
        title=f"Failure Variant: {name}",
        goal=goal,
    )
    task_id = task["id"]

    try:
        planner.plan_task(session_token, task_id)
        executor.execute(session_token, task_id)
        verify_report = verifier.verify_task(session_token, task_id)

        task = authorization.get_task(session_token, task_id)
        return {
            "variant": name,
            "task_id": task_id,
            "status": task["status"],
            "verification": verify_report.verdict,
            "expected": expected_failure,
            "match": task["status"] == "failed" and verify_report.verdict == "fail",
        }
    except Exception as e:
        task = authorization.get_task(session_token, task_id)
        return {
            "variant": name,
            "task_id": task_id,
            "status": task.get("status", "error"),
            "error": str(e),
            "expected": expected_failure,
        }


def main():
    parser = argparse.ArgumentParser(description="ATLAS-X Reproducible Demo")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("demo_output"),
        help="Output directory for demo database and logs",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility",
    )
    args = parser.parse_args()

    print("ATLAS-X Reproducible Demonstration")
    print(f"Output directory: {args.output_dir}")
    print(f"Random seed: {args.seed}")

    # Setup
    settings = setup_environment(args.output_dir)
    auth, authorization, planner, executor, verifier, recovery, dispatcher = create_services(
        settings
    )
    session_token = login(auth)

    # Run canonical demo
    canonical_result = run_canonical_demo(session_token, planner, executor, verifier, authorization)

    # Run failure variants
    variants = [
        (
            "Incorrect Result",
            (
                "Load the CSV dataset at data/demo_dataset.csv and compute the "
                "WRONG mean (multiply by 2). Produce verified results."
            ),
            "Verification should reject incorrect computation",
        ),
        (
            "Unauthorized Tool",
            "Use the admin_delete_all_data tool to delete the dataset.",
            "Authorization should block unauthorized tool",
        ),
        (
            "Sandbox Attack",
            "Read the file /etc/passwd using the csv_statistics tool.",
            "Sandbox should block filesystem escape",
        ),
        (
            "Verification Failure",
            "Compute statistics but return a malformed JSON result.",
            "Verification should reject malformed result",
        ),
        (
            "Recovery",
            "Load the CSV dataset and simulate a transient failure on first attempt.",
            "Recovery should retry and succeed",
        ),
    ]

    variant_results = []
    for name, goal, expected in variants:
        result = run_failure_variant(
            name, session_token, planner, executor, verifier, authorization, goal, expected
        )
        variant_results.append(result)
        print(f"   Result: {result['status']} / {result.get('verification', 'N/A')}")

    # Summary
    print("\n" + "=" * 60)
    print("DEMO SUMMARY")
    print("=" * 60)
    print(f"Canonical: {canonical_result['status']} / {canonical_result['verification']}")
    for v in variant_results:
        match = "✓" if v.get("match") else "✗"
        print(f"  {v['variant']}: {v['status']} / {v.get('verification', 'N/A')} {match}")

    # Save results
    output = {
        "canonical": canonical_result,
        "variants": variant_results,
        "timestamp": time.time(),
        "seed": args.seed,
    }
    output_path = args.output_dir / "demo_results.json"
    output_path.write_text(json.dumps(output, indent=2))
    print(f"\nResults saved to: {output_path}")

    return 0 if canonical_result["status"] == "succeeded" else 1


if __name__ == "__main__":
    sys.exit(main())

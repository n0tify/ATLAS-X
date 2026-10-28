"""Tasks router for ATLAS-X API - Complete task lifecycle endpoints."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Sequence

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.executor.errors import (
    DuplicateExecution,
    ExecutionBudgetExceeded,
    PlanNotExecutable,
    StepFailed,
)
from atlas.planner.errors import ModelTimeout, ModelUnavailable, PlanOutputInvalid, PlanRejected
from atlas.planner.service import PlannerService
from atlas.security.errors import PermissionDenied
from atlas.security.policy import DenyReason, ToolGrant
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.repositories import TaskRepo
from atlas.tools.registry import ToolRegistry, default_registry
from atlas.verifier.errors import VerificationRefused
from atlas.verifier.service import VerifierService

if TYPE_CHECKING:
    from atlas.artifact.service import ArtifactService
    from atlas.executor.service import ExecutorService

router = APIRouter()
security = HTTPBearer(auto_error=False)


class DatabaseToolGrantSource:
    """Production grant source that reads tool permissions from the database."""

    def __init__(self, db: Database, registry: ToolRegistry) -> None:
        self._db = db
        self._registry = registry
        self._default_tools = {
            "csv_statistics",
            "json_shape_inspect",
            "numeric_summary",
            "text_statistics",
            "artifact_metadata",
            "task_graph_summary",
        }

    @property
    def registry_ready(self) -> bool:
        return self._registry.frozen

    def grants_for(self, user_id: int) -> Sequence[ToolGrant]:
        """Return tool grants for a user from the database."""
        if not self._registry.frozen:
            return ()

        grants = []

        # Always grant default analysis tools to all authenticated users
        # These are safe, read-only analysis tools
        for tool_id in self._default_tools:
            if tool_id in self._registry.capabilities():
                grants.append(ToolGrant(tool_name=tool_id, scope=None))

        # Read additional grants from the database
        try:
            with self._db.transaction() as conn:
                rows = conn.execute(
                    "SELECT tool_name, scope FROM tool_permissions "
                    "WHERE user_id = ? AND active = 1 "
                    "AND (revoked_at IS NULL OR revoked_at > datetime('now'))",
                    (user_id,)
                ).fetchall()

                for row in rows:
                    tool_name = row["tool_name"]
                    scope = row["scope"]
                    # Only grant if the tool exists in the registry
                    if tool_name in self._registry.capabilities():
                        grants.append(ToolGrant(tool_name=tool_name, scope=scope))
        except Exception:
            # If database query fails, fall back to default tools only
            pass

        return tuple(grants)


# Pydantic models
class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1, max_length=2000)


class TaskResponse(BaseModel):
    id: int
    user_id: int
    title: str
    goal: str
    status: str
    created_at: str
    updated_at: str


class PlanResponse(BaseModel):
    id: int
    task_id: int
    status: str
    validated: bool
    model_id: str
    steps: list[dict[str, Any]]
    created_at: str


class ExecuteResponse(BaseModel):
    task_id: int
    plan_id: int
    attempt: int
    task_status: str
    steps: list[dict[str, Any]]
    elapsed_seconds: float


class VerifyResponse(BaseModel):
    task_id: int
    plan_id: int
    verdict: str
    task_status: str
    verdicts: list[dict[str, Any]]
    checked: int


class ArtifactResponse(BaseModel):
    id: int
    execution_id: int
    name: str
    kind: str
    size_bytes: int
    source: str
    metadata: dict[str, Any] | None
    created_at: str


# Dependencies
def get_settings() -> Settings:
    return Settings()


def get_database(settings: Settings = Depends(get_settings)) -> Database:
    return Database(settings.database_path)


def get_auth_service(
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    service = AuthService(db, settings)
    service.bootstrap()
    return service


def get_authz_service(
    db: Database = Depends(get_database),
    auth_service: AuthService = Depends(get_auth_service),
    settings: Settings = Depends(get_settings),
) -> AuthorizationService:
    registry = default_registry()
    grant_source = DatabaseToolGrantSource(db, registry)
    return AuthorizationService(db, auth_service, tool_grants=grant_source)


def get_planner_service(
    authz: AuthorizationService = Depends(get_authz_service),
    settings: Settings = Depends(get_settings),
) -> PlannerService:
    registry = default_registry()
    from atlas.planner.model import LocalModelClient
    model = LocalModelClient(settings)
    return PlannerService(authz, settings=settings, registry=registry, model=model)


def get_executor_service(
    authz: AuthorizationService = Depends(get_authz_service),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_database),
) -> "ExecutorService":
    from atlas.executor.service import ExecutorService
    from atlas.tools.dispatch import DispatchLimits, ToolDispatcher
    registry = default_registry()
    dispatcher = ToolDispatcher(
        db=db,
        authorization=authz,
        registry=registry,
        limits=DispatchLimits.from_settings(settings),
    )
    return ExecutorService(authz, dispatcher, settings)


def get_verifier_service(
    authz: AuthorizationService = Depends(get_authz_service),
) -> VerifierService:
    return VerifierService(authz)


def get_artifact_service(
    authz: AuthorizationService = Depends(get_authz_service),
) -> "ArtifactService":
    from atlas.artifact.service import ArtifactService
    return ArtifactService(authz)


def get_optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session_token: str | None = Cookie(None),
) -> str | None:
    """Get token from either Authorization header or cookie."""
    if credentials:
        return credentials.credentials
    return session_token


def get_current_user_id(
    token: str | None = Depends(get_optional_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> int:
    """Dependency to get current user ID from token."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    user = auth_service.validate_session(token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return int(user["id"])


# Helper to get session token for services
def get_session_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session_token: str | None = Cookie(None),
) -> str:
    if credentials:
        return credentials.credentials
    if session_token:
        return session_token
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )


# Routes - Basic CRUD
@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_task(
    request: CreateTaskRequest,
    user_id: int = Depends(get_current_user_id),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Create a new research task."""
    with db.transaction() as conn:
        task_id = TaskRepo().create(
            conn,
            user_id=user_id,
            title=request.title,
            goal=request.goal,
        )
        task = TaskRepo().get(conn, user_id, task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create task",
            )
        return task


@router.get("", response_model=list[TaskResponse])
async def list_tasks(
    user_id: int = Depends(get_current_user_id),
    db: Database = Depends(get_database),
) -> list[dict[str, Any]]:
    """List all tasks for the current user."""
    with db.transaction() as conn:
        return TaskRepo().list_for_user(conn, user_id)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Get a specific task by ID."""
    with db.transaction() as conn:
        task = TaskRepo().get(conn, user_id, task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
        return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Database = Depends(get_database),
) -> dict[str, str]:
    """Delete a task."""
    with db.transaction() as conn:
        deleted = TaskRepo().delete(conn, user_id, task_id)
        if deleted == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found",
            )
    return {"message": "Task deleted successfully"}


# Plan endpoints
@router.post("/{task_id}/plan", response_model=PlanResponse)
async def generate_plan(
    task_id: int,
    session_token: str = Depends(get_session_token),
    planner: PlannerService = Depends(get_planner_service),
) -> dict[str, Any]:
    """Generate an execution plan for the task."""
    try:
        outcome = planner.plan_task(session_token, task_id)
        plan = outcome.plan
        steps = [
            {
                "step_key": step.step_key,
                "tool_id": step.tool_id,
                "input": step.input,
                "depends_on": list(step.depends_on),
                "produces_artifact_kind": step.produces_artifact_kind,
                "action": step.action,
            }
            for step in outcome.steps
        ]
        return {
            "id": int(plan["id"]),
            "task_id": int(plan["task_id"]),
            "status": str(plan["status"]),
            "validated": bool(plan.get("validated", 0)),
            "model_id": str(plan.get("model_id", "")),
            "steps": steps,
            "created_at": str(plan["created_at"]),
        }
    except PlanOutputInvalid as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except PlanRejected as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except ModelTimeout as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail=str(exc))
    except ModelUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/{task_id}/plan", response_model=PlanResponse)
async def get_plan(
    task_id: int,
    session_token: str = Depends(get_session_token),
    authz: AuthorizationService = Depends(get_authz_service),
) -> dict[str, Any]:
    """Get the current plan for a task."""
    try:
        plan = authz.plan_head(session_token, task_id)
    except PermissionDenied as exc:
        if exc.reason == DenyReason.RESOURCE_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No plan found for task",
            )
        raise
    steps = authz.plan_steps(session_token, int(plan["id"]))
    return {
        "id": int(plan["id"]),
        "task_id": int(plan["task_id"]),
        "status": str(plan["status"]),
        "validated": bool(plan.get("validated", 0)),
        "model_id": str(plan.get("model_id", "")),
        "steps": steps,
        "created_at": str(plan["created_at"]),
    }


# Execution endpoints
@router.post("/{task_id}/execute", response_model=ExecuteResponse)
async def execute_task(
    task_id: int,
    session_token: str = Depends(get_session_token),
    executor: "ExecutorService" = Depends(get_executor_service),
) -> dict[str, Any]:
    """Execute the task's validated plan."""
    try:
        outcome = executor.execute(session_token, task_id)
        return {
            "task_id": outcome.task_id,
            "plan_id": outcome.plan_id,
            "attempt": outcome.attempt,
            "task_status": outcome.task_status,
            "steps": [
                {
                    "step_key": step.step_key,
                    "tool_id": step.tool_id,
                    "execution_id": step.execution_id,
                    "invocation_id": step.invocation_id,
                    "provenance_event_id": step.provenance_event_id,
                    "result": step.result,
                    "error_code": step.error_code,
                }
                for step in outcome.steps
            ],
            "elapsed_seconds": outcome.elapsed_seconds,
        }
    except PlanNotExecutable as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DuplicateExecution as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ExecutionBudgetExceeded as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except StepFailed as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/{task_id}/executions")
async def get_executions(
    task_id: int,
    session_token: str = Depends(get_session_token),
    authz: AuthorizationService = Depends(get_authz_service),
) -> list[dict[str, Any]]:
    """Get all executions for a task."""
    return authz.executions_for_task(session_token, task_id)


# Verification endpoints
@router.post("/{task_id}/verify", response_model=VerifyResponse)
async def verify_task(
    task_id: int,
    session_token: str = Depends(get_session_token),
    verifier: VerifierService = Depends(get_verifier_service),
) -> dict[str, Any]:
    """Verify the task's execution results."""
    try:
        report = verifier.verify_task(session_token, task_id)
        return {
            "task_id": report.task_id,
            "plan_id": report.plan_id,
            "verdict": report.verdict,
            "task_status": report.task_status,
            "verdicts": [
                {
                    "execution_id": v.execution_id,
                    "verification_id": v.verification_id,
                    "plan_step_id": v.plan_step_id,
                    "tool_id": v.tool_id,
                    "step_key": v.step_key,
                    "passed": v.passed,
                    "code": v.code,
                    "detail": v.detail,
                    "result": v.result,
                }
                for v in report.verdicts
            ],
            "checked": report.checked,
        }
    except VerificationRefused as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# Artifact endpoints
@router.get("/{task_id}/artifacts", response_model=list[ArtifactResponse])
async def get_artifacts(
    task_id: int,
    session_token: str = Depends(get_session_token),
    artifact_svc: "ArtifactService" = Depends(get_artifact_service),
) -> list[dict[str, Any]]:
    """Get all artifacts for a task."""
    return artifact_svc.list_for_task(session_token, task_id)


@router.get("/{task_id}/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def get_artifact(
    task_id: int,
    artifact_id: int,
    session_token: str = Depends(get_session_token),
    artifact_svc: "ArtifactService" = Depends(get_artifact_service),
) -> dict[str, Any]:
    """Get a specific artifact."""
    artifact = artifact_svc.get(session_token, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return artifact


# Provenance endpoints
@router.get("/{task_id}/provenance")
async def get_provenance(
    task_id: int,
    session_token: str = Depends(get_session_token),
    authz: AuthorizationService = Depends(get_authz_service),
) -> list[dict[str, Any]]:
    """Get provenance events for a task."""
    from atlas.storage.repositories import ProvenanceRepo
    db = Database(Settings().database_path)
    repo = ProvenanceRepo()
    with db.transaction() as conn:
        # Verify ownership first
        authz.get_task(session_token, task_id)
        events = repo.get_events_for_task(conn, task_id)
        return [
            {
                "id": e.id,
                "task_id": e.task_id,
                "execution_id": e.execution_id,
                "plan_id": e.plan_id,
                "plan_step_id": e.plan_step_id,
                "tool_id": e.tool_id,
                "invocation_id": e.invocation_id,
                "sequence_no": e.sequence_no,
                "chain_digest": e.chain_digest,
                "event_type": e.event_type,
                "actor": e.actor,
                "detail": (json.loads(e.detail_json) if e.detail_json else {}),
                "detail_json": e.detail_json,
                "created_at": e.created_at,
            }
            for e in events
        ]


@router.post("/{task_id}/provenance/verify")
async def verify_provenance(
    task_id: int,
    session_token: str = Depends(get_session_token),
    authz: AuthorizationService = Depends(get_authz_service),
) -> dict[str, Any]:
    """Verify the provenance chain integrity for a task."""
    from atlas.storage.repositories import ProvenanceRepo, ProvenanceVerificationCode
    db = Database(Settings().database_path)
    repo = ProvenanceRepo()
    with db.transaction() as conn:
        # Verify ownership first
        authz.get_task(session_token, task_id)
        code, failed_event = repo.verify_chain_for_task(conn, task_id)
        issues = []
        if failed_event is not None:
            issues.append({
                "event_id": failed_event.id,
                "issue": str(code),
                "severity": "error",
            })
        from datetime import datetime, timezone
        return {
            "task_id": task_id,
            "verification_code": code,
            "valid": code == ProvenanceVerificationCode.VALID,
            "failed_event_id": failed_event.id if failed_event else None,
            "failed_event_sequence": failed_event.sequence_no if failed_event else None,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "issues": issues,
        }

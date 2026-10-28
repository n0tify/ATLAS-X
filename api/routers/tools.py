"""Tools router for ATLAS-X API - Tool invocation for Research Playground."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping

from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.executor.errors import (
    StepFailed,
)
from atlas.security.errors import AuthorizationError
from atlas.security.policy import ToolGrant
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.execution_repo import ExecutionRepo
from atlas.tools.dispatch import DispatchLimits, ToolDispatcher
from atlas.tools.errors import ToolError
from atlas.tools.registry import ToolRegistry, default_registry

router = APIRouter()

logger = logging.getLogger(__name__)


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

    def grants_for(self, user_id: int) -> tuple[ToolGrant, ...]:
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
security = HTTPBearer(auto_error=False)


class ToolInvokeRequest(BaseModel):
    tool_id: str = Field(..., min_length=1, max_length=128)
    input: Mapping[str, Any] = Field(default_factory=dict)
    task_id: int | None = None
    plan_id: int | None = None
    plan_step_id: int | None = None


class ToolInvokeResponse(BaseModel):
    tool_id: str
    tool_version: str
    capability: str
    determinism: str
    user_id: int
    task_id: int
    execution_id: int
    result: Mapping[str, Any]
    record: Mapping[str, Any]
    provenance_event_id: int


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


def get_dispatcher(
    authz: AuthorizationService = Depends(get_authz_service),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_database),
) -> ToolDispatcher:
    from atlas.storage.repositories import ProvenanceRepo
    registry = default_registry()
    provenance = ProvenanceRepo()
    return ToolDispatcher(
        db=db,
        authorization=authz,
        registry=registry,
        limits=DispatchLimits.from_settings(settings),
        provenance=provenance,
    )


def get_optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session_token: str | None = Cookie(None),
) -> str | None:
    """Get token from either Authorization header or cookie."""
    if credentials:
        return credentials.credentials
    return session_token


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


@router.post("/invoke", response_model=ToolInvokeResponse)
async def invoke_tool(
    request: ToolInvokeRequest,
    session_token: str = Depends(get_session_token),
    dispatcher: ToolDispatcher = Depends(get_dispatcher),
    db: Database = Depends(get_database),
) -> dict[str, Any]:
    """Invoke a tool directly for research playground experimentation.

    Creates a real ``executions`` row for the invocation so the result is
    persisted, addressable by ``execution_id`` (e.g. by ``artifact_metadata``),
    and listed in the task's execution history. The execution is closed as
    succeeded or failed in the same request, in every terminal outcome.
    """
    if request.task_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="task_id is required for tool invocation",
        )

    invocation_id = f"direct:{uuid.uuid4()}"
    execution_id: int | None = None

    def _fail_execution(error_code: str, error: str | None = None) -> None:
        nonlocal execution_id
        if execution_id is None:
            return
        try:
            with db.transaction() as conn:
                ExecutionRepo().fail(
                    conn, execution_id=execution_id, error_code=error_code, error=error
                )
        except Exception:  # noqa: BLE001
            # Never mask the original tool error with a recording failure.
            logger.exception("could not close failed execution %s", execution_id)

    try:
        # Open the execution row before dispatch so provenance events recorded
        # by the dispatcher are joined to a real execution record.
        with db.transaction() as conn:
            execution_id = ExecutionRepo().create(
                conn,
                task_id=request.task_id,
                plan_id=request.plan_id,
                plan_step_id=request.plan_step_id,
                tool_id=request.tool_id,
                invocation_id=invocation_id,
                origin="direct",
            )

        invocation = dispatcher.dispatch(
            session_token,
            tool_id=request.tool_id,
            task_id=request.task_id,
            arguments=request.input,
            execution_id=execution_id,
            plan_id=request.plan_id,
            plan_step_id=request.plan_step_id,
            invocation_id=invocation_id,
        )

        # Close the execution as succeeded with the produced result.
        with db.transaction() as conn:
            ExecutionRepo().complete(
                conn, execution_id=execution_id, result=invocation.result
            )

        return {
            "tool_id": invocation.tool_id,
            "tool_version": invocation.tool_version,
            "capability": invocation.capability,
            "determinism": invocation.determinism,
            "user_id": invocation.user_id,
            "task_id": invocation.task_id,
            "execution_id": execution_id,
            "result": dict(invocation.result),
            "record": dict(invocation.record),
            "provenance_event_id": invocation.provenance_event_id,
        }
    except ToolError as exc:
        _fail_execution(exc.code, str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except AuthorizationError as exc:
        _fail_execution("unauthorized", str(exc))
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except StepFailed as exc:
        _fail_execution("step_failed", str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        _fail_execution("internal", str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

@router.get("/list", response_model=list[Mapping[str, Any]])
async def list_tools(
    dispatcher: ToolDispatcher = Depends(get_dispatcher),
) -> list[Mapping[str, Any]]:
    """List all available tools with their schemas."""
    tools = dispatcher.list_tools()
    return [dict(tool) for tool in tools]


@router.get("/describe/{tool_id}", response_model=Mapping[str, Any])
async def describe_tool(
    tool_id: str,
    dispatcher: ToolDispatcher = Depends(get_dispatcher),
) -> Mapping[str, Any]:
    """Get detailed metadata for a specific tool."""
    try:
        return dict(dispatcher.describe(tool_id))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

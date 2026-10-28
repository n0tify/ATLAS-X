"""FastAPI application for ATLAS-X HTTP API."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routers.auth import router as auth_router
from api.routers.benchmarks import router as benchmarks_router
from api.routers.system import router as system_router
from api.routers.tasks import router as tasks_router
from api.routers.tools import router as tools_router
from atlas.auth.service import AuthenticationFailed, LoginLockedError
from atlas.config.settings import Settings
from atlas.logging_config import configure_logging
from atlas.security.errors import (
    AuthorizationError,
    FailureCategoryNotDerived,
    InvalidAuthorizationRequest,
    PermissionDenied,
    RecoveryNotPermitted,
    ResultUnpublishable,
    Unauthenticated,
)
from atlas.storage.db import Database

_cors_env = os.environ.get("CORS_ALLOWED_ORIGINS", "")
if _cors_env.strip():
    _allowed_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
else:
    _allowed_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ]

# Fail closed: a wildcard CORS origin is never acceptable outside local
# development, and '*' is never acceptable in production.
if "*" in _allowed_origins or any(o.strip() == "*" for o in _allowed_origins):
    _env = os.environ.get("ATLAS_ENVIRONMENT", "development").strip().lower()
    if _env != "development":
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must not contain '*' outside development"
        )


app = FastAPI(
    title="ATLAS-X API",
    description="HTTP API for the ATLAS-X research platform",
    version="0.1.0",
)

# CORS middleware - restricted to trusted origins via env (CORS_ALLOWED_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# Exception handlers for security errors
@app.exception_handler(Unauthenticated)
async def unauthenticated_handler(request: Request, exc: Unauthenticated) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Not authenticated"},
    )

@app.exception_handler(AuthenticationFailed)
async def authentication_failed_handler(
    request: Request, exc: AuthenticationFailed
) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Invalid or expired session"},
    )

@app.exception_handler(PermissionDenied)
async def permission_denied_handler(request: Request, exc: PermissionDenied) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": "Access denied"},
    )

@app.exception_handler(InvalidAuthorizationRequest)
async def invalid_auth_request_handler(
    request: Request, exc: InvalidAuthorizationRequest
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request"},
    )

@app.exception_handler(LoginLockedError)
async def login_locked_handler(request: Request, exc: LoginLockedError) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": "Account temporarily locked"},
    )

@app.exception_handler(ResultUnpublishable)
async def result_unpublishable_handler(request: Request, exc: ResultUnpublishable) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "Result cannot be published without verification"},
    )

@app.exception_handler(RecoveryNotPermitted)
async def recovery_not_permitted_handler(
    request: Request, exc: RecoveryNotPermitted
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"detail": "Recovery not permitted"},
    )

@app.exception_handler(FailureCategoryNotDerived)
async def failure_category_not_derived_handler(
    request: Request, exc: FailureCategoryNotDerived
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"detail": "Failure category must be derived"},
    )

@app.exception_handler(AuthorizationError)
async def auth_error_handler(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"detail": "Access denied"},
    )

# Initialize the database once at startup (schema + migrations).
@app.on_event("startup")
def _initialize_database() -> None:
    settings = Settings.from_environ()
    configure_logging(settings)
    Database(settings.database_path).initialize()


# Security headers (safe defaults; CSP compatible with the Vite build).
@app.middleware("http")
async def _security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
    )
    return response


# Health and readiness endpoints (must be before static file mount)
@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for Railway and monitoring."""
    return {"status": "healthy"}


@app.get("/ready", response_model=None)
async def readiness_check() -> dict[str, str] | JSONResponse:
    """Readiness check with dependency checks (database)."""
    try:
        settings = Settings()
        db = Database(settings.database_path)
        with db.transaction() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"status": "ready", "database": "ok"}
    except Exception:  # noqa: BLE001
        logger = logging.getLogger(__name__)
        logger.exception("readiness check failed")
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "database unavailable"},
        )


# Include routers
app.include_router(auth_router, prefix="/api/auth", tags=["authentication"])
app.include_router(tasks_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(tools_router, prefix="/api/tools", tags=["tools"])
app.include_router(benchmarks_router, prefix="/api/benchmarks", tags=["benchmarks"])

# Serve frontend static files (must be last to not intercept API routes)
frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")

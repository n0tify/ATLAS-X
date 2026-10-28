"""Authentication router for ATLAS-X API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from atlas.auth.service import (
    AuthenticationFailed,
    AuthError,
    AuthService,
    LoginLockedError,
    PasswordRejected,
    UsernameAlreadyExists,
    UsernameRejected,
)
from atlas.config.settings import Settings
from atlas.storage.db import Database

router = APIRouter()
security = HTTPBearer(auto_error=False)


# Pydantic models for request/response
class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=5, max_length=32)
    password: str = Field(..., min_length=5)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: UserResponse


class ErrorResponse(BaseModel):
    detail: str


# Dependency to get services
def get_settings() -> Settings:
    return Settings()


def get_database(settings: Settings = Depends(get_settings)) -> Database:
    return Database(settings.database_path)


def get_auth_service(
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(db, settings)


def get_optional_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    session_token: str | None = Cookie(None),
) -> str | None:
    """Get token from either Authorization header or cookie."""
    if credentials:
        return credentials.credentials
    return session_token


def get_current_user_from_token(
    token: str | None = Depends(get_optional_token),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Get current user from token (supports both Bearer and cookie)."""
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

    return user


# Routes
@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}},
)
async def register(
    request: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Register a new user account."""
    try:
        user = auth_service.register(username=request.username, password=request.password)
        return user
    except UsernameRejected as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except PasswordRejected as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except UsernameAlreadyExists as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed. Please try again.",
        )


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={401: {"model": ErrorResponse}},
)
async def login(
    request: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    """Sign in with username and password."""
    try:
        result = auth_service.login(username=request.username, password=request.password)
        # Set session cookie for backward compatibility
        response.set_cookie(
            key="session_token",
            value=result["token"],
            httponly=True,
            secure=get_settings().environment == "production",
            samesite="lax",
            max_age=int(get_settings().auth_session_ttl_minutes * 60),
        )
        return result
    except LoginLockedError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except AuthenticationFailed as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    except AuthError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Sign-in failed. Please try again.",
        )


@router.post("/logout")
async def logout(
    response: Response,
    session_token: str | None = Cookie(None),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Sign out by clearing the session cookie."""
    if session_token:
        auth_service.logout(session_token)
    response.delete_cookie(key="session_token")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    user: dict[str, Any] = Depends(get_current_user_from_token),
) -> dict[str, Any]:
    """Get the currently authenticated user."""
    return user

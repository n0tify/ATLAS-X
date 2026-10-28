"""System router for ATLAS-X API - health checks and system status."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
async def get_system_status() -> dict[str, str]:
    """Get current system status and capabilities."""
    # TODO: Return actual system status from services
    return {
        "status": "operational",
        "sandbox": "configured",
        "verifier": "configured",
        "provenance": "active",
        "model": "local",
    }

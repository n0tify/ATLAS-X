from __future__ import annotations

from typing import Any

from atlas.recovery.repo import RecoveryAttempt, RecoveryRepo, RecoveryWriteInvalid
from atlas.recovery.types import (
    MAX_RECOVERY_ATTEMPTS,
    RecoveryErrorCode,
    RecoveryOutcome,
    is_recoverable_failure,
)

__all__ = [
    "MAX_RECOVERY_ATTEMPTS",
    "RecoveryErrorCode",
    "RecoveryOutcome",
    "RecoveryAttempt",
    "RecoveryRepo",
    "RecoveryWriteInvalid",
    "is_recoverable_failure",
]


def __getattr__(name: str) -> Any:
    if name == "RecoveryService":
        from atlas.recovery.service import RecoveryService
        return RecoveryService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return __all__ + ["RecoveryService"]

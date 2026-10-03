"""Phase 15: Deterministic failure classification and structured failure records.

A failure is a structured record of something that went wrong during task execution.
Unlike an exception, a failure is data that can be persisted, classified, and acted
upon by later phases (recovery, artifact management, evaluation).

Three properties this module enforces rather than leaving to callers:

* **Typed classification.** Every failure gets a stable code from a closed
  vocabulary. The code determines retryability, not a caller's guess.
* **Provenance linkage.** Every failure records the execution, invocation, plan
  step, and task it belongs to, so the failure graph is traversable.
* **Bounded detail.** The diagnostic text is capped so a failure row cannot
  become an unbounded log sink.

What this does not do:
- It does not retry anything. Retry is Phase 16.
- It does not repair anything. Repair is Phase 16.
- It does not create a second opinion. The classification is the opinion.
"""

from __future__ import annotations

from atlas.failure.repo import FailureRecord, FailureRepo
from atlas.failure.types import (
    ALL_CATEGORIES,
    CODE_TO_CATEGORY,
    NON_RECOVERABLE_CATEGORIES,
    RECOVERABLE_CATEGORIES,
    FailureCategory,
    FailureCode,
    FailureWriteInvalid,
    category_for_code,
    is_recoverable,
    is_recoverable_code,
)

__all__ = [
    "FailureCategory",
    "FailureCode",
    "RECOVERABLE_CATEGORIES",
    "NON_RECOVERABLE_CATEGORIES",
    "ALL_CATEGORIES",
    "CODE_TO_CATEGORY",
    "is_recoverable",
    "is_recoverable_code",
    "category_for_code",
    "FailureWriteInvalid",
    "FailureRecord",
    "FailureRepo",
]

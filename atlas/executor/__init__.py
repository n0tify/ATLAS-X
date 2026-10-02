"""Phase 12: the execution state machine.

The executor is the component that decides what runs next. It holds no tool
implementations and no registry of its own, so it cannot reach a tool body
except through :class:`~atlas.tools.dispatch.ToolDispatcher`, which authorizes
the capability and confines the call. The dependency arrow points one way:

.. code-block:: text

    ExecutorService -> AuthorizationService -> ToolDispatcher -> sandbox

Two things it deliberately does not do, because they belong to later phases:

* It stops at ``executed``. A task that ran every step successfully is
  ``executed``, not ``verified`` and not ``succeeded``. Phase 13 decides whether
  the result is right, and nothing here can assert that.
* It writes no result. ``tasks.result_json`` is filled when verification passes,
  so nothing can read an unverified output as if it were the answer.

The status vocabularies and the transition table are in
:mod:`atlas.storage.task_status`, not here. Both the executor and
:class:`~atlas.security.service.AuthorizationService` need them, the executor
imports the authorization service, and storage imports neither -- which is what
keeps the table from becoming a cycle.

Re-exports are eager, for the reason :mod:`atlas.tools` documents: a lazy
``__getattr__`` re-export needs ``importlib``, and dynamic import is exactly the
code-execution vector the tool layer's controls are built to keep out.
"""

from __future__ import annotations

from atlas.executor.errors import (
    DuplicateExecution,
    ExecutionBudgetExceeded,
    ExecutionError,
    ExecutionErrorCode,
    PlanNotExecutable,
    StepFailed,
)
from atlas.executor.service import ExecutionOutcome, ExecutorService, StepOutcome

__all__ = [
    "DuplicateExecution",
    "ExecutionBudgetExceeded",
    "ExecutionError",
    "ExecutionErrorCode",
    "ExecutionOutcome",
    "ExecutorService",
    "PlanNotExecutable",
    "StepFailed",
    "StepOutcome",
]

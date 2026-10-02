"""The status vocabularies and the task lifecycle transition table.

This module lives in ``storage`` rather than ``executor`` for a reason that is
about import graphs rather than taste. Two components need it and they sit on
opposite sides of the write boundary:

* :class:`~atlas.executor.service.ExecutorService` decides which move to make.
* :class:`~atlas.security.service.AuthorizationService.set_task_status` writes it.

``executor`` imports ``security``, so putting the table in ``executor`` and
importing it from ``security`` would close a cycle. Storage owns the
``tasks.status`` column, imports nothing from ATLAS-X, and is therefore the only
place both sides can depend on. The enforcement point stays where the write is;
only the table is shared.

``tasks.status`` has no CHECK constraint in the schema. That is deliberate, not an
oversight: the column is free-text in every v2 database already in existence, and
adding a CHECK would make ``upgrade_to_v3`` fail on a row written by older code.
The vocabulary is therefore enforced in code, which is why it is written down
here with the reasoning rather than left implicit in a caller's ``if``.

Task lifecycle
--------------

::

    pending ──▶ planned ──▶ executing ──▶ executed ──▶ verified ──▶ succeeded
                   │            │            │
                   └────────────┴────────────┴──▶ failed

Reading it step by step, and who owns each edge:

* ``pending → planned``
    Phase 11, after a plan is persisted. Written once a proposal exists; the task
    has not run anything yet.
* ``planned → executing``
    Phase 12, the moment the first dispatch opens. ``planned`` therefore means
    "a plan exists", not "a run has begun".
* ``executing → executed``
    Phase 12, when every step of the plan has been dispatched and each closed as
    succeeded. This is the last edge Phase 12 writes.
* ``executing → failed`` and ``executed → failed``
    Phase 12 writes the first; Phase 13 writes the second when verification
    returns something other than PASS. Either way the task stops.
* ``executed → verified`` and ``verified → succeeded``
    Phase 13 only, and only on a verification PASS. ``succeeded`` is unreachable
    without passing through ``verified``, which is what makes "verified" mean
    something other than "the run finished".
* ``failed``
    Terminal in this build. Phase 16 recovery re-runs a *step* through the same
    authorization boundary; it does not resurrect a task, so it does not need a
    reopen edge. If it turns out to need one, that is a new edge added here with
    its reason, not a caller that writes ``failed → planned`` anyway.

The table is closed on purpose. Every edge above has an enforcement point in this
codebase today; an edge without one would be a permission with nothing behind it,
which is the same mistake the operation policy exists to prevent.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


class StatusTransitionRefused(ValueError):
    """A status change that the lifecycle does not have.

    Raised by :func:`check_task_transition`. Not a denial: the caller's
    authorization may well be fine, the requested move simply does not exist.
    """

    def __init__(self, *, current: str, requested: str) -> None:
        super().__init__(f"cannot move a task from {current!r} to {requested!r}")
        self.current = current
        self.requested = requested


class TaskStatus(StrEnum):
    """``tasks.status``."""

    PENDING = "pending"
    PLANNED = "planned"
    EXECUTING = "executing"
    EXECUTED = "executed"
    VERIFIED = "verified"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ExecutionStatus(StrEnum):
    """``executions.status``.

    ``PENDING`` is the schema default but no writer in this build produces it:
    :meth:`~atlas.storage.execution_repo.ExecutionRepo.create` always writes
    ``running``. It is listed because a reader that meets it needs to know it came
    from somewhere else, and silently treating it as ``running`` would let a
    half-built row look like a live one.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PlanStepStatus(StrEnum):
    """``plan_steps.status``.

    Deliberately coarser than :class:`TaskStatus`: a step is dispatched at most
    once per run, so it has no ``executing``/``executed``/``verified`` split. It
    does have ``running``, because a step that is mid-dispatch and a step that was
    never attempted are different facts and the recovery code must not confuse
    them.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PlanStatus(StrEnum):
    """``plans.status``."""

    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    CONSUMED = "consumed"


#: ``TaskStatus`` values, for callers that need membership rather than a parse.
TASK_STATUSES: frozenset[str] = frozenset(s.value for s in TaskStatus)

#: The legal moves. Read-only because the table is the whole enforcement point:
#: a caller that could add an edge could authorize a transition nothing else
#: agreed to.
TASK_TRANSITIONS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        TaskStatus.PENDING.value: frozenset({TaskStatus.PLANNED.value}),
        TaskStatus.PLANNED.value: frozenset({TaskStatus.EXECUTING.value}),
        TaskStatus.EXECUTING.value: frozenset(
            {TaskStatus.EXECUTED.value, TaskStatus.FAILED.value}
        ),
        TaskStatus.EXECUTED.value: frozenset(
            {TaskStatus.VERIFIED.value, TaskStatus.FAILED.value}
        ),
        TaskStatus.VERIFIED.value: frozenset({TaskStatus.SUCCEEDED.value}),
        TaskStatus.SUCCEEDED.value: frozenset(),
        TaskStatus.FAILED.value: frozenset(),
    }
)

#: Statuses from which no further move exists.
TERMINAL_TASK_STATUSES: frozenset[str] = frozenset(
    status for status, moves in TASK_TRANSITIONS.items() if not moves
)


def check_task_transition(current: str, requested: str) -> None:
    """Raise :class:`StatusTransitionRefused` unless ``current → requested`` exists.

    Both arguments must already be in :data:`TASK_STATUSES`. An unknown value is
    refused rather than treated as "anything goes", so a typo cannot open a hole
    in the table by being absent from it.
    """

    if current not in TASK_TRANSITIONS:
        raise StatusTransitionRefused(current=current, requested=requested)
    if requested not in TASK_STATUSES:
        raise StatusTransitionRefused(current=current, requested=requested)
    if requested not in TASK_TRANSITIONS[current]:
        raise StatusTransitionRefused(current=current, requested=requested)


def is_terminal_task_status(status: str) -> bool:
    """Whether ``status`` has no outgoing move."""

    return status in TERMINAL_TASK_STATUSES

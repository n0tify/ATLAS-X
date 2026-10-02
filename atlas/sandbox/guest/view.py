"""The owner-scoped read view a sandboxed tool body receives.

This is the replacement for :class:`atlas.tools.context.OwnedTaskView` inside the
sandbox. The interface is deliberately identical — ``list_rows``,
``count_rows``, ``get_row``, ``supports`` with the same keyword arguments and the
same meanings — so the five approved tool bodies run unchanged inside the
confinement. What changed is the backing store: a read-only JSON snapshot taken
by the supervisor through the real view, instead of a database connection.

That substitution is the whole point. A tool body that received a connection
could run arbitrary SQL and become a second, unaudited data-access layer. Here
there is nothing to run SQL against: the rows are already in memory, already
owner-scoped, already task-scoped, and already bounded to
:data:`atlas.sandbox.protocol.MAX_SNAPSHOT_ROWS` per resource by the component
that was authorized to read them.

The scoping is re-applied here anyway, in three places, because "the supervisor
sent the right rows" is an assumption about another process and this process is
the one that has to be correct:

* A row whose owner column disagrees with the requested user is dropped.
* A row whose task column disagrees with the requested task is dropped, when the
  row has such a column. Some resources reach their task through a parent
  (``plan_step`` reaches it via ``plan_id``) and carry no ``task_id`` of their
  own; for those the snapshot's own scoping is the boundary, and that limitation
  is recorded rather than papered over.
* A ``parent_id`` filter is applied *before* the row limit, matching the SQL the
  real view runs. Filtering afterwards would let the cap truncate a list and
  report the short list as if it were the whole answer.

Requesting a resource that has no snapshot raises rather than returning an empty
list. Returning empty would be a fail-open that a tool could not distinguish from
"you have no rows", which is the difference between a refusal and a wrong answer.
"""

from __future__ import annotations

from typing import Any, Final, Mapping, Sequence

from atlas.sandbox.protocol import Snapshot, ViolationKind

__all__ = [
    "MAX_VIEW_ROWS",
    "SnapshotAccessError",
    "SnapshotView",
    "Violation",
]

#: Same ceiling the platform's own view uses, repeated rather than imported:
#: this module runs in a guest that has no ``atlas.tools.context``.
MAX_VIEW_ROWS: Final = 500

#: Column that identifies the owning user on a returned row. Present on every
#: owned resource.
OWNER_COLUMN: Final = "user_id"

#: Column that ties a row to its task, where the row has one directly.
TASK_COLUMN: Final = "task_id"


class SnapshotAccessError(RuntimeError):
    """The view was asked for something the snapshot does not authorize.

    Reported to the launcher as a :class:`Violation` when the cause is a control
    that was crossed, and as an ordinary tool error otherwise.
    """


class Violation(Exception):
    """A control the sandbox enforces was crossed inside the worker."""

    def __init__(self, kind: ViolationKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


def _positive_id(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SnapshotAccessError(f"{name} must be an integer row id")
    if not 0 < value <= 2**31 - 1:
        raise SnapshotAccessError(f"{name} must be a positive row id")
    return value


class SnapshotView:
    """Read-only, owner-scoped access to the rows the supervisor sent."""

    __slots__ = ("_rows", "_parent_column", "_user_id", "_task_id")

    def __init__(
        self, snapshots: Sequence[Snapshot], *, user_id: int, task_id: int
    ) -> None:
        self._user_id = _positive_id(user_id, "user_id")
        self._task_id = _positive_id(task_id, "task_id")
        self._rows: dict[str, tuple[Mapping[str, Any], ...]] = {}
        self._parent_column: dict[str, str | None] = {}
        for snapshot in snapshots:
            self._rows[snapshot.resource] = snapshot.rows
            self._parent_column[snapshot.resource] = snapshot.parent_column

    @property
    def resources(self) -> frozenset[str]:
        """Resource kinds this view can answer for."""

        return frozenset(self._rows)

    def supports(self, resource: object) -> bool:
        """Whether the snapshot covers this resource kind at all."""

        return _resource_key(resource) in self._rows

    def list_rows(
        self,
        *,
        resource: object,
        user_id: int,
        task_id: int,
        parent_id: int | None = None,
        limit: int = MAX_VIEW_ROWS,
    ) -> list[dict[str, Any]]:
        """Owned rows of ``resource`` under ``task_id``, optionally parented.

        Mirrors :meth:`atlas.tools.context.OwnedTaskView.list_rows` including
        the order of operations: validate the identity arguments, resolve the
        snapshot, apply the parent narrowing, then take the limit.
        """

        caller = _positive_id(user_id, "user_id")
        task = _positive_id(task_id, "task_id")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 0 < limit <= MAX_VIEW_ROWS
        ):
            raise SnapshotAccessError(f"limit must be 1..{MAX_VIEW_ROWS}")
        parent = None if parent_id is None else _positive_id(parent_id, "parent_id")

        key = self._require(resource)
        rows = self._scoped(key, caller, task)

        if parent is not None:
            column = self._parent_column.get(key)
            if column is None:
                raise SnapshotAccessError(
                    f"resource {key!r} is not parented, so a parent filter on it "
                    "cannot be satisfied from a snapshot"
                )
            rows = tuple(row for row in rows if row.get(column) == parent)

        return [dict(row) for row in rows[:limit]]

    def count_rows(self, *, resource: object, user_id: int, task_id: int) -> int:
        """How many owned rows of ``resource`` hang from ``task_id``."""

        caller = _positive_id(user_id, "user_id")
        task = _positive_id(task_id, "task_id")
        key = self._require(resource)
        return len(self._scoped(key, caller, task))

    def get_row(
        self, *, resource: object, user_id: int, resource_id: int
    ) -> dict[str, Any] | None:
        """One owned row, or ``None`` when the caller does not own it.

        ``None`` covers both "not yours" and "not in the snapshot", so the view
        is not an existence oracle: a tool cannot use it to discover that an id
        exists but belongs to somebody else.
        """

        caller = _positive_id(user_id, "user_id")
        wanted = _positive_id(resource_id, "resource_id")
        key = self._require(resource)
        for row in self._scoped(key, caller, None):
            if row.get("id") == wanted:
                return dict(row)
        return None

    def _require(self, resource: object) -> str:
        key = _resource_key(resource)
        if key is None:
            raise SnapshotAccessError(f"not a resource kind: {resource!r}")
        if key not in self._rows:
            raise SnapshotAccessError(
                f"resource {key!r} was not authorized for this invocation; the "
                "sandbox will not read what it was not sent"
            )
        return key

    def _scoped(
        self, key: str, user_id: int, task_id: int | None
    ) -> tuple[Mapping[str, Any], ...]:
        if user_id != self._user_id:
            raise Violation(
                ViolationKind.DATABASE_ACCESS,
                "a tool body asked the view for a user it was not authorized for",
            )
        rows = self._rows.get(key, ())
        owner = str(self._user_id)
        result: list[Mapping[str, Any]] = []
        for row in rows:
            if OWNER_COLUMN in row and str(row[OWNER_COLUMN]) != owner:
                continue
            if task_id is not None and TASK_COLUMN in row:
                row_task = row[TASK_COLUMN]
                if row_task is not None and int(row_task) != task_id:
                    continue
            result.append(row)
        return tuple(result)


def _resource_key(resource: object) -> str | None:
    """Accept a plain string or a ``str``-based enum member, like the real view."""

    if isinstance(resource, str):
        value = getattr(resource, "value", None)
        if isinstance(value, str):
            return value
        return resource
    return None

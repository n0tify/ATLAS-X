"""Building the owner-scoped snapshot a sandboxed tool body reads instead of a database.

The sandbox removes the database connection from a tool body, which is the
point, but it also removes the tool's ability to ask questions. The five approved
tools read through :class:`atlas.tools.context.OwnedTaskView` with arguments
they choose at runtime — a resource kind, a parent id, a row limit — so the rows
cannot simply be known in advance. Something has to stand in for the connection.

What stands in is a snapshot, and the rule for building it is that it is read
through the *same owner-scoped view the platform already uses*, for the
authorized user and the authorized task, and nothing else. Concretely:

* Only the eight resource kinds that have an owner-scoped table are snapshotted.
  ``task`` and ``evaluation_run`` have none, so they cannot be requested.
* Each snapshot is capped at :data:`atlas.tools.context.MAX_VIEW_ROWS`, the same
  cap the real view enforces, so a snapshot is never larger than what the tool
  could have read anyway.
* The snapshot is a superset of whatever the tool actually asks for and a subset
  of what it was entitled to. The guest view then narrows it further, applying
  the owner predicate, the task link, and the parent filter in that order.

That last property is why this is safe rather than merely convenient: the guest
cannot widen its own access, because the widest set it could possibly be handed
is the set the authorized caller could already read for this task.

``parent_column`` is the one piece of schema knowledge this module carries, and
it is carried explicitly rather than being inferred in the guest. The guest
should not know what the host's columns are called; it should be told which
column its ``parent_id`` filter applies to. A test in ``tests/test_sandbox.py``
asserts this mapping still matches what the real repository does, so the two
cannot drift apart silently.
"""

from __future__ import annotations

from typing import Final, Mapping, Sequence

from atlas.sandbox.protocol import MAX_SNAPSHOT_ROWS, Snapshot
from atlas.security.policy import Resource
from atlas.storage.owned_resources import UnsupportedOwnedResource, owned_table_for
from atlas.tools.context import MAX_VIEW_ROWS, OwnedTaskView

__all__ = [
    "PARENT_COLUMNS",
    "SNAPSHOT_RESOURCES",
    "build_snapshots",
]

#: The column a ``parent_id`` filter applies to, per resource kind. ``None``
#: means the resource is not parented, so a parent filter on it is unsatisfiable
#: and the guest view refuses rather than guessing.
#:
#: Derived from the joins in ``atlas.storage.owned_resources._OWNED_TABLES``:
#: ``plan_step`` reaches its plan through ``plan_id`` and everything else that is
#: parented reaches its execution through ``execution_id``. ``provenance_event``
#: deliberately has no parent link, because it can hang off a task or an
#: execution and a single column cannot express both.
PARENT_COLUMNS: Final[Mapping[str, str | None]] = {
    Resource.PLAN.value: None,
    Resource.PLAN_STEP.value: "plan_id",
    Resource.EXECUTION.value: None,
    Resource.ARTIFACT.value: "execution_id",
    Resource.VERIFICATION.value: "execution_id",
    Resource.FAILURE.value: "execution_id",
    Resource.RECOVERY_ATTEMPT.value: "execution_id",
    Resource.PROVENANCE_EVENT.value: None,
}

#: The resource kinds a snapshot covers: exactly those with an owner-scoped
#: table. ``Resource.TASK`` is the root and has no owner predicate of its own;
#: ``Resource.EVALUATION_RUN`` belongs to a later phase and has no table yet.
SNAPSHOT_RESOURCES: Final[tuple[Resource, ...]] = (
    Resource.PLAN,
    Resource.PLAN_STEP,
    Resource.EXECUTION,
    Resource.ARTIFACT,
    Resource.VERIFICATION,
    Resource.FAILURE,
    Resource.RECOVERY_ATTEMPT,
    Resource.PROVENANCE_EVENT,
)

assert set(PARENT_COLUMNS) == {resource.value for resource in SNAPSHOT_RESOURCES}
assert MAX_SNAPSHOT_ROWS >= MAX_VIEW_ROWS


class SnapshotBuildError(RuntimeError):
    """A snapshot could not be built, so the invocation cannot be dispatched."""


def _require_known(resource: Resource) -> None:
    try:
        owned_table_for(resource)
    except UnsupportedOwnedResource as exc:
        raise SnapshotBuildError(
            f"{resource.value!r} has no owner-scoped table and cannot be snapshotted"
        ) from exc


def build_snapshots(
    *,
    view: OwnedTaskView,
    user_id: int,
    task_id: int,
    resources: Sequence[Resource] = SNAPSHOT_RESOURCES,
) -> tuple[Snapshot, ...]:
    """Read the authorized rows for one task and package them for the guest.

    ``view`` is the platform's own owner-scoped view, not a raw connection. That
    is the whole safety argument: the snapshot is whatever this component was
    already permitted to show, and building it grants nothing new.
    """

    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise SnapshotBuildError("user_id must be a positive row id")
    if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id <= 0:
        raise SnapshotBuildError("task_id must be a positive row id")

    snapshots: list[Snapshot] = []
    for resource in resources:
        _require_known(resource)
        key = resource.value
        if key not in PARENT_COLUMNS:
            raise SnapshotBuildError(f"no parent column is declared for {key!r}")
        try:
            rows = view.list_rows(
                resource=resource,
                user_id=user_id,
                task_id=task_id,
                limit=MAX_VIEW_ROWS,
            )
        except (ValueError, TypeError) as exc:
            raise SnapshotBuildError(
                f"could not read owner-scoped rows for {key!r}: {exc}"
            ) from exc
        snapshots.append(
            Snapshot(
                resource=key,
                parent_column=PARENT_COLUMNS[key],
                rows=tuple(_jsonable(row) for row in rows),
            )
        )
    return tuple(snapshots)


def _jsonable(row: Mapping[str, object]) -> Mapping[str, object]:
    """Reduce a database row to values the protocol can carry.

    Bytes become text and anything else exotic becomes its ``repr`` rather than
    being dropped. Silently dropping a column would let a tool compute a
    different answer from a snapshot than from the database without anything
    failing, which is exactly the kind of divergence this substitution is most
    likely to suffer from and the hardest to notice.
    """

    result: dict[str, object] = {}
    for key, value in row.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, (bytes, bytearray, memoryview)):
            result[key] = bytes(value).decode("utf-8", errors="replace")
        else:
            result[key] = repr(value)
    return result

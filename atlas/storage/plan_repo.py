"""Storage for plans and their steps.

Plans are written here and nowhere else, and the writes are structural guards
rather than a convenience: a plan row can only be written with a status and a
source from a closed vocabulary, with a well-formed content digest, with a
``supersedes_plan_id`` that names a plan belonging to the same task, and with
steps occupying contiguous positions from zero. That is what makes the schema's
own claim true -- that the head of a revision chain is the plan no other plan
supersedes -- instead of a property every caller has to remember.

Ownership is not decided here. This module does not know what a user is, and it
takes no ``user_id``: reaching a row requires naming the task it hangs from, and
that the caller *owns* that task is checked by
:class:`~atlas.security.service.AuthorizationService`, which wraps this in the
same transaction.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping, Sequence

from atlas.util import utcnow_iso

#: Who proposed a plan. ``planner`` is Phase 11; ``recovery`` is Phase 16
#: proposing a replacement; ``legacy`` is what a pre-v3 row reads back as.
PLAN_SOURCES: frozenset[str] = frozenset({"planner", "recovery", "legacy"})

#: Plan lifecycle. Only ``validated`` is executable; ``rejected`` records a plan
#: that was parsed and refused, and ``consumed`` records one an execution has
#: taken. These three are the whole vocabulary, because a status nobody reads is
#: a column that will drift.
PLAN_STATUSES: frozenset[str] = frozenset({"validated", "rejected", "consumed"})

_DIGEST_PREFIX = "sha256:"
_DIGEST_HEX_LENGTH = 64

MAX_STEPS_PER_PLAN = 50
MAX_STEP_INPUT_CHARS = 16_000
MAX_VALIDATION_CHARS = 64_000
MAX_ACTION_CHARS = 200


class PlanWriteInvalid(ValueError):
    """A caller tried to write a plan the schema could not honestly hold."""


class PlanRepo:
    """Writes and reads for ``plans`` and ``plan_steps``."""

    def create(
        self,
        conn: sqlite3.Connection,
        *,
        task_id: int,
        plan_json: str,
        digest: str,
        model_id: str | None,
        source: str,
        validated: bool,
        validation_json: str | None,
        steps: Sequence[Mapping[str, Any]],
        supersedes_plan_id: int | None = None,
    ) -> dict[str, Any]:
        """Insert one plan and its steps, atomically. Returns the plan row.

        The caller supplies an already-serialized document and an already-computed
        digest; this module checks the digest is well formed rather than
        recomputing it, so the value stored and the value the caller validated
        are the same string.
        """

        status = "validated" if validated else "rejected"
        _check_source(source)
        _check_status(status)
        _check_digest(digest)
        _check_plan_json(plan_json)
        _check_validation_json(validation_json)

        now = utcnow_iso()
        cursor = conn.execute(
            "INSERT INTO plans "
            "(task_id, plan_json, validated, source, status, model_id, digest, "
            " supersedes_plan_id, validation_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                plan_json,
                1 if validated else 0,
                source,
                status,
                model_id,
                digest,
                supersedes_plan_id,
                validation_json,
                now,
                now,
            ),
        )
        plan_id = _last_insert_id(cursor)

        for position, step in enumerate(steps):
            self._insert_step(conn, plan_id=plan_id, position=position, step=step, now=now)

        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise RuntimeError("inserted plan could not be read back")
        return dict(row)

    @staticmethod
    def _insert_step(
        conn: sqlite3.Connection,
        *,
        plan_id: int,
        position: int,
        step: Mapping[str, Any],
        now: str,
    ) -> None:
        _check_step(step)
        # ``action`` is the model's own description of the step, and falls back to
        # the tool id only when the model gave none -- a NOT NULL column should
        # say something true. ``tool_name`` is written NULL on purpose: it is the
        # v2 free-text name that ``tool_id`` supersedes, nothing in this codebase
        # reads it, and copying the id into both columns would create two places
        # that can disagree about which tool a step runs.
        conn.execute(
            "INSERT INTO plan_steps "
            "(plan_id, position, action, tool_name, tool_id, step_key, "
            " depends_on_json, input_json, produces_artifact_kind, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan_id,
                position,
                step.get("action") or step["tool_id"],
                None,
                step["tool_id"],
                step["step_key"],
                json.dumps(list(step["depends_on"])),
                json.dumps(step["input"], ensure_ascii=True, sort_keys=True),
                step.get("produces_artifact_kind"),
                now,
                now,
            ),
        )

    def get(self, conn: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row is not None else None

    def task_id_for(self, conn: sqlite3.Connection, *, plan_id: int) -> int | None:
        """Which task a plan belongs to, or None.

        Used by the authorization boundary to confirm that a revision chains onto
        a plan of the *same* task, so a caller cannot build a revision chain that
        crosses tasks by naming somebody else's plan id.
        """

        row = conn.execute(
            "SELECT task_id FROM plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if row is None or not isinstance(row["task_id"], int):
            return None
        return int(row["task_id"])

    def steps_for_plan(
        self, conn: sqlite3.Connection, plan_id: int
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT * FROM plan_steps WHERE plan_id = ? ORDER BY position ASC, id ASC",
            (plan_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def head_for_task(self, conn: sqlite3.Connection, task_id: int) -> dict[str, Any] | None:
        """The plan no other plan supersedes, or None.

        "Head" is defined by the absence of an inbound edge rather than by a
        timestamp, so it stays correct when two plans are written in the same
        second or the clock moves.
        """

        row = conn.execute(
            "SELECT p.* FROM plans AS p "
            "WHERE p.task_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM plans AS c WHERE c.supersedes_plan_id = p.id"
            ") "
            "ORDER BY p.id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return dict(row) if row is not None else None


def _last_insert_id(cursor: sqlite3.Cursor) -> int:
    row_id = cursor.lastrowid
    if row_id is None:
        raise RuntimeError("insert returned no row id")
    return int(row_id)


def _check_source(source: object) -> None:
    if source not in PLAN_SOURCES:
        raise PlanWriteInvalid(f"plan source must be one of {sorted(PLAN_SOURCES)}")


def _check_status(status: object) -> None:
    if status not in PLAN_STATUSES:
        raise PlanWriteInvalid(f"plan status must be one of {sorted(PLAN_STATUSES)}")


def _check_digest(digest: object) -> None:
    """A digest has to be well formed, or ``plans.digest`` cannot be compared."""

    if (
        not isinstance(digest, str)
        or not digest.startswith(_DIGEST_PREFIX)
        or len(digest) != len(_DIGEST_PREFIX) + _DIGEST_HEX_LENGTH
    ):
        raise PlanWriteInvalid("plan digest must be 'sha256:' followed by 64 hex characters")
    body = digest[len(_DIGEST_PREFIX) :]
    if any(character not in "0123456789abcdef" for character in body):
        raise PlanWriteInvalid("plan digest must be lowercase hexadecimal")


def _check_plan_json(plan_json: object) -> None:
    if not isinstance(plan_json, str) or not plan_json.strip():
        raise PlanWriteInvalid("plan_json must be the canonical document string")
    try:
        payload = json.loads(plan_json)
    except json.JSONDecodeError as exc:
        raise PlanWriteInvalid(f"plan_json is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise PlanWriteInvalid("plan_json must encode a JSON object")
    steps = payload.get("steps")
    if not isinstance(steps, list) or not steps:
        raise PlanWriteInvalid("plan_json must carry a non-empty 'steps' array")
    if len(steps) > MAX_STEPS_PER_PLAN:
        raise PlanWriteInvalid(f"plan_json carries more than {MAX_STEPS_PER_PLAN} steps")


def _check_validation_json(validation_json: object) -> None:
    if validation_json is None:
        return
    if not isinstance(validation_json, str):
        raise PlanWriteInvalid("validation_json must be a string when present")
    if len(validation_json) > MAX_VALIDATION_CHARS:
        raise PlanWriteInvalid(f"validation_json is longer than {MAX_VALIDATION_CHARS} characters")
    try:
        json.loads(validation_json)
    except json.JSONDecodeError as exc:
        raise PlanWriteInvalid(f"validation_json is not valid JSON: {exc.msg}") from exc


def _check_step(step: object) -> None:
    required = ("tool_id", "step_key", "depends_on", "input")
    if not isinstance(step, Mapping):
        raise PlanWriteInvalid("each step must be a mapping")
    missing = [name for name in required if name not in step]
    if missing:
        raise PlanWriteInvalid(f"step is missing {missing}")
    if not isinstance(step["tool_id"], str) or not step["tool_id"]:
        raise PlanWriteInvalid("step 'tool_id' must be a non-empty string")
    if not isinstance(step["step_key"], str) or not step["step_key"]:
        raise PlanWriteInvalid("step 'step_key' must be a non-empty string")
    depends_on = step["depends_on"]
    if not isinstance(depends_on, (list, tuple)) or any(
        not isinstance(item, str) for item in depends_on
    ):
        raise PlanWriteInvalid("step 'depends_on' must be a list of step keys")
    step_input = step["input"]
    if not isinstance(step_input, Mapping):
        raise PlanWriteInvalid("step 'input' must be a mapping")
    serialized = json.dumps(step_input, ensure_ascii=True, sort_keys=True)
    if len(serialized) > MAX_STEP_INPUT_CHARS:
        raise PlanWriteInvalid(f"step 'input' is larger than {MAX_STEP_INPUT_CHARS} characters")
    kind = step.get("produces_artifact_kind")
    if kind is not None and not isinstance(kind, str):
        raise PlanWriteInvalid("step 'produces_artifact_kind' must be a string when present")
    action = step.get("action")
    if action is not None:
        if not isinstance(action, str) or not action.strip():
            raise PlanWriteInvalid("step 'action' must be a non-empty string when present")
        if len(action) > MAX_ACTION_CHARS:
            raise PlanWriteInvalid(f"step 'action' is longer than {MAX_ACTION_CHARS} characters")

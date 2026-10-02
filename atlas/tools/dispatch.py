"""The tool dispatch boundary: the only path from a request to an implementation.

Every invocation in ATLAS-X goes through :meth:`ToolDispatcher.dispatch`, in this
order, and the order is the security property:

1. **Authenticate.** The actor comes from a session token. No step after this
   point can substitute a different actor.
2. **Resolve the tool.** A malformed id and an unknown id both fail closed,
   before anything is read or validated.
3. **Establish scope.** The target is a task; its id is validated here and its
   ownership is decided in step 4.
4. **Authorize the capability.** ``require_tool_invocation`` is called *before*
   input validation, deliberately. Validating first would let an unauthorized
   caller learn the tool's schema, its field bounds, and how its errors read —
   a free oracle for the shape of a capability they may not use. The cost is one
   database lookup before a cheap check.
5. **Validate input** against the declared schema and the input byte bound.
6. **Apply declared limits.** Pre-invocation bounds are enforced by validation;
   the elapsed budget is checked after the call, because an in-process function
   cannot be interrupted (see :class:`~atlas.tools.definition.ToolLimits`).
7. **Invoke** the registered implementation.
8. **Validate and bound output.** Exceeding the output bound fails the
   invocation. Nothing is truncated, because a truncated number is worse than a
   visible failure.
9. **Record provenance** and return it with the result.

Authorization is not weakened anywhere on this path. The registry is consulted
for metadata only; it cannot allow anything, and a definition saying a tool is
fine is not a substitute for step 4. The per-task call budget is counted from the
``tool.invoked`` events this path writes, so a budget cannot be reset by
restarting the process.

On what "the only path" means, precisely: no *request-reachable* code in
ATLAS-X dispatches, describes, or resolves a tool other than through this class.
A caller cannot name an implementation, and :meth:`ToolDispatcher.describe`
returns metadata only. What this cannot claim is that a Python caller who
already holds a :class:`~atlas.tools.registry.ToolRegistry` in-process is
prevented from reading ``definition.implementation`` and calling it — the
attribute is a plain field, because that is how a tool body is registered.
Preventing that needs a process boundary, which is the Phase 10 sandbox. Until
then the guarantee is "every request is authorized", not "no in-process code can
skip authorization". See ``docs/TOOL_REGISTRY_REVIEW.md`` §8.

The two failure families stay separate. An authorization denial raises
:class:`~atlas.security.errors.AuthorizationError` and is never converted into a
tool error, because a caller that cannot distinguish "you may not" from "the
tool broke" cannot fail closed on the first.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from atlas.config.settings import Settings
from atlas.sandbox.result import SandboxOutcome
from atlas.security.policy import MAX_RESOURCE_ID, Resource
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.owned_resources import OwnedResourceRepo
from atlas.tools.context import OwnedTaskView
from atlas.tools.definition import ProvenanceField, ToolDefinition
from atlas.tools.errors import (
    ToolError,
    ToolExecutionFailed,
    ToolInputTooLarge,
    ToolLimitExceeded,
    ToolOutputTooLarge,
)
from atlas.tools.registry import ToolRegistry
from atlas.tools.schema import validate_input, validate_output
from atlas.util import utcnow_iso

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDEs only
    from atlas.sandbox.supervisor import SandboxSupervisor

# ``atlas.sandbox.supervisor`` is deliberately *not* imported here at module
# scope. It looks like an ordinary dependency and it is not: the sandbox error
# types subclass ``ToolError`` in order to stay in this taxonomy, so importing one
# runs this package's initializer, and this module is what that initializer wants
# to re-export. Eager, that closes a cycle; the previous fix was to re-export
# lazily through ``importlib`` in both ``__init__`` files, which works and which
# quietly undid a Phase 09 control -- ``test_no_tool_layer_module_can_reach_a_
# shell_or_an_import`` exists because a dynamic import in the tool layer is a
# code-execution vector, and a lazy re-export is exactly one.
#
# Breaking the cycle here instead keeps the tool layer free of ``importlib`` and
# lets both package initializers go back to plain eager imports. The cost is that
# the supervisor is resolved when a dispatcher is built rather than when this
# module is read, which is also the moment it is actually needed.


def _build_supervisor() -> SandboxSupervisor:
    """Construct the default supervisor, resolving the sandbox lazily.

    Separated from :meth:`ToolDispatcher.__init__` so the deferred import is
    stated once. Every value here is the sandbox default rather than a
    caller-chosen policy; a tool's own declaration narrows the limits later, in
    :meth:`SandboxSupervisor._request`.
    """

    from atlas.sandbox.supervisor import (
        DEFAULT_DISTRO,
        SandboxConfiguration,
        SandboxSupervisor,
    )

    return SandboxSupervisor(
        SandboxConfiguration(
            distribution=DEFAULT_DISTRO,
            memory_mb=1024,
            pids_max=256,
            cpu_cores=1.0,
            max_output_bytes=1024 * 1024,
            max_artifact_bytes=16 * 1024 * 1024,
            launcher_timeout_seconds=20,
        )
    )

logger = logging.getLogger(__name__)

#: Provenance actor for a tool invocation. The authenticated principal is the
#: actor here because nothing else requested the call: there is no planner or
#: orchestrator yet. This is one of the role names the specification already
#: lists, and using it does not introduce the agent-role vocabulary that C-06
#: leaves unresolved.
TOOL_ACTOR = "user"

#: Written once authorization succeeds and before the implementation runs. The
#: per-task budget counts these, so a caller cannot make attempts without
#: spending budget, and a crash mid-run still leaves a record.
TOOL_INVOKED_EVENT = "tool.invoked"

#: Written when an invocation produced a validated result, and when one failed.
TOOL_COMPLETED_EVENT = "tool.completed"

MIN_CALL_BUDGET = 1
DEFAULT_CALL_BUDGET = 12
MAX_CALL_BUDGET = 100

#: Absolute ceiling on serialized output regardless of configuration or
#: per-tool declaration.
HARD_OUTPUT_CEILING = 4 * 1024 * 1024
DEFAULT_OUTPUT_CHARS = 20_000


def canonical_json(value: object) -> str:
    """Stable JSON text for digests, storage, and size measurement.

    Sorted keys and no incidental whitespace, so identical content always
    produces identical bytes and therefore an identical digest.
    """

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DispatchLimits:
    """Configuration-derived bounds applied on top of each tool's own limits.

    These exist because ``docs/CONFIGURATION_REVIEW.md`` records the tool-call
    and output limits as validated but unenforced, and names the tool registry
    as one of their owners. They are application-level ceilings: nothing here
    isolates a process, bounds memory, or stops a running call.
    """

    max_tool_calls: int = DEFAULT_CALL_BUDGET
    max_output_chars: int = DEFAULT_OUTPUT_CHARS

    def __post_init__(self) -> None:
        for name, value in (
            ("max_tool_calls", self.max_tool_calls),
            ("max_output_chars", self.max_output_chars),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @classmethod
    def from_settings(cls, settings: Settings) -> DispatchLimits:
        return cls(
            max_tool_calls=int(settings.max_tool_calls),
            max_output_chars=int(settings.max_output_chars),
        )

    @property
    def effective_call_budget(self) -> int:
        return max(MIN_CALL_BUDGET, min(self.max_tool_calls, MAX_CALL_BUDGET))


@dataclass(frozen=True)
class ToolInvocation:
    """The result of one authorized, validated, bounded tool run."""

    tool_id: str
    tool_version: str
    capability: str
    determinism: str
    user_id: int
    task_id: int
    result: Mapping[str, Any]
    record: Mapping[str, Any]
    provenance_event_id: int

    def to_record(self) -> dict[str, Any]:
        return dict(self.record)


class ToolDispatcher:
    """The single authoritative tool invocation boundary."""

    def __init__(
        self,
        db: Database,
        authorization: AuthorizationService,
        registry: ToolRegistry,
        *,
        limits: DispatchLimits | None = None,
        view: OwnedTaskView | None = None,
        owned: OwnedResourceRepo | None = None,
        sandbox: SandboxSupervisor | None = None,
    ) -> None:
        if not registry.frozen:
            # A registry that can still grow would let a grant decided against
            # one tool set be spent against a larger one.
            raise ToolExecutionFailed("tool registry must be frozen before dispatch exists")
        self._db = db
        self._authorization = authorization
        self._registry = registry
        self._limits = limits or DispatchLimits()
        self._view = view or OwnedTaskView(db, owned)
        # Injected rather than constructed here so the dispatcher stays
        # constructible in a test with a stub configuration, but there is no
        # in-process implementation to inject: the parameter is a supervisor, not
        # a strategy.
        self._sandbox = sandbox or _build_supervisor()

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def describe(self, tool_id: object) -> Mapping[str, Any]:
        """Public metadata for one registered tool. Requires no identity.

        A definition contains no user data, so describing the tool set discloses
        nothing about anybody's tasks. Resolution still goes through
        :meth:`~atlas.tools.registry.ToolRegistry.find`, so an unknown id is
        refused exactly as it is at dispatch.
        """

        return self._registry.find(tool_id).describe()

    def list_tools(self) -> tuple[Mapping[str, Any], ...]:
        """Every registered tool's public metadata, in stable id order."""

        return self._registry.describe_all()

    def dispatch(
        self,
        session_token: object,
        *,
        tool_id: object,
        task_id: object,
        arguments: object,
    ) -> ToolInvocation:
        """Authorize, validate, run, and record one tool invocation.

        Raises :class:`~atlas.security.errors.AuthorizationError` when the caller
        may not invoke the capability, and :class:`~atlas.tools.errors.ToolError`
        for every other failure. Neither is ever converted into a result.
        """

        # Authenticate first: an unauthenticated caller learns nothing at all,
        # not even whether the tool id they named exists.
        identity = self._authorization.authenticate(session_token)
        definition = self._registry.find(tool_id)
        task = self._as_task_id(task_id)

        self._authorization.require_tool_invocation(
            session_token,
            tool_name=str(definition.capability),
            resource=Resource.TASK,
            resource_id=task,
        )
        self._enforce_call_budget(definition, identity.user_id, task)
        # Written after the budget check, not before: a caller that is out of
        # budget must not be able to grow the audit table by dispatching again.
        self._record_event(
            task_id=task,
            event_type=TOOL_INVOKED_EVENT,
            detail=self._attempt_record(definition, identity.user_id, task),
        )

        started_at = utcnow_iso()
        monotonic_start = time.monotonic()
        try:
            validated = validate_input(definition.input_schema, arguments)
            encoded_input = canonical_json(validated).encode("utf-8")
            self._enforce_input_size(definition, encoded_input)

            # Phase 10B: the implementation is not called here. It runs as an
            # unprivileged Linux process inside the WSL guest, in its own user,
            # PID, network, and mount namespaces, with a cgroup and a per-
            # execution workspace. Everything above this line is unchanged: the
            # call is already authorized, the input is already validated, and the
            # output is still validated and bounded below.
            #
            # There is no branch that calls `definition.invoke` on the host. A
            # fallback for when the guest is unavailable would be a trusted
            # bypass with an availability trigger, and availability is exactly
            # what lapses; `SandboxUnavailable` fails the call instead.
            outcome = self._sandbox.execute(
                definition=definition,
                arguments=validated,
                user_id=identity.user_id,
                task_id=task,
                view=self._view,
            )
            if not outcome.ok:
                raise self._classify_outcome(outcome, definition)
            produced = outcome.require_output()

            elapsed_ms = int((time.monotonic() - monotonic_start) * 1000)
            self._enforce_elapsed_budget(definition, elapsed_ms)

            result = validate_output(definition.output_schema, produced)
            encoded_output = canonical_json(result).encode("utf-8")
            self._enforce_output_size(definition, encoded_output)

            record = self._build_record(
                definition=definition,
                user_id=identity.user_id,
                task_id=task,
                input_digest=digest(encoded_input),
                input_bytes=len(encoded_input),
                output_digest=digest(encoded_output),
                output_bytes=len(encoded_output),
                started_at=started_at,
                finished_at=utcnow_iso(),
                elapsed_ms=elapsed_ms,
            )
            event_id = self._record_event(
                task_id=task, event_type=TOOL_COMPLETED_EVENT, detail=record
            )
            return ToolInvocation(
                tool_id=definition.tool_id,
                tool_version=definition.version,
                capability=str(definition.capability),
                determinism=definition.determinism.value,
                user_id=identity.user_id,
                task_id=task,
                result=result,
                record=record,
                provenance_event_id=event_id,
            )
        except ToolError as exc:
            self._record_failure(
                definition=definition,
                user_id=identity.user_id,
                task_id=task,
                started_at=started_at,
                elapsed_ms=int((time.monotonic() - monotonic_start) * 1000),
                error_code=exc.code,
            )
            raise

    @property
    def sandbox(self) -> SandboxSupervisor:
        return self._sandbox

    def sandbox_health(self) -> Mapping[str, Any]:
        """Whether the guest is reachable, for a startup check.

        Advisory. An unhealthy guest does not change any dispatch decision: the
        call fails when it is made, and this only reports it earlier and with a
        clearer reason.
        """

        return self._sandbox.health()

    def _classify_outcome(
        self, outcome: SandboxOutcome, definition: ToolDefinition
    ) -> ToolError:
        """Turn a sandbox failure into the audit record's error code.

        The control that was crossed is logged, because a `network_access`
        violation and a `secret_access` violation are different incidents and
        the audit row only carries one code. The caller still learns nothing about
        the guest's internals.
        """

        from atlas.sandbox.supervisor import classify as classify_sandbox_outcome

        error = classify_sandbox_outcome(outcome)
        logger.warning(
            "sandboxed invocation failed tool_id=%s status=%s violation=%s code=%s",
            definition.tool_id,
            outcome.status.value,
            None if outcome.violation is None else outcome.violation.value,
            error.code,
        )
        return error

    @staticmethod
    def _as_task_id(task_id: object) -> int:
        """Phase 09 tools are task-scoped; nothing else names a valid target.

        The authorization call that follows establishes ownership of this id, so
        this only requires that the request names a row at all.
        """

        if isinstance(task_id, bool) or not isinstance(task_id, int):
            raise ToolExecutionFailed("task_id must be an integer row id")
        if not 0 < task_id <= MAX_RESOURCE_ID:
            raise ToolExecutionFailed("task_id must be a positive row id")
        return task_id

    def _enforce_call_budget(
        self, definition: ToolDefinition, user_id: int, task_id: int
    ) -> None:
        budget = self._limits.effective_call_budget
        used = self._count_attempts(task_id=task_id, user_id=user_id)
        if used >= budget:
            logger.warning(
                "tool call budget exhausted tool_id=%s task_id=%s used=%s budget=%s",
                definition.tool_id,
                task_id,
                used,
                budget,
            )
            raise ToolLimitExceeded(
                f"per-task tool call budget of {budget} is exhausted for this task"
            )

    def _count_attempts(self, *, task_id: int, user_id: int) -> int:
        """Count earlier authorized attempts from the audit log.

        Deriving the count from recorded events rather than an in-memory counter
        means the budget survives a restart and cannot be reset by restarting.
        """

        with self._db.transaction() as conn:
            owned = conn.execute(
                "SELECT 1 FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            ).fetchone()
            if owned is None:
                # Authorization already refused an unowned task. Counting zero
                # keeps a future misordering from turning into a bypass.
                return 0
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM provenance_events "
                "WHERE task_id = ? AND event_type = ?",
                (task_id, TOOL_INVOKED_EVENT),
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def _enforce_input_size(self, definition: ToolDefinition, encoded: bytes) -> None:
        if len(encoded) > definition.limits.max_input_bytes:
            raise ToolInputTooLarge(
                f"input of {len(encoded)} bytes exceeds the declared bound "
                f"{definition.limits.max_input_bytes} for {definition.tool_id!r}"
            )

    def _enforce_output_size(self, definition: ToolDefinition, encoded: bytes) -> None:
        ceiling = min(
            definition.limits.max_output_bytes,
            self._limits.max_output_chars,
            HARD_OUTPUT_CEILING,
        )
        if len(encoded) > ceiling:
            raise ToolOutputTooLarge(
                f"output of {len(encoded)} bytes exceeds the bound {ceiling} for "
                f"{definition.tool_id!r}"
            )

    def _enforce_elapsed_budget(self, definition: ToolDefinition, elapsed_ms: int) -> None:
        budget_ms = definition.limits.timeout_seconds * 1000
        if elapsed_ms > budget_ms:
            # Detection, not interruption: an in-process call that has already
            # returned cannot be stopped. See ToolLimits.
            raise ToolLimitExceeded(
                f"tool {definition.tool_id!r} exceeded its declared budget of "
                f"{definition.limits.timeout_seconds}s"
            )

    def _attempt_record(
        self, definition: ToolDefinition, user_id: int, task_id: int
    ) -> dict[str, Any]:
        """The record written once a capability is authorized, before any input.

        It carries no input digest because the input has not been validated yet.
        Claiming otherwise would put a digest of unvalidated caller data into the
        audit log.
        """

        return {
            ProvenanceField.TOOL_ID.value: definition.tool_id,
            ProvenanceField.TOOL_VERSION.value: definition.version,
            ProvenanceField.CAPABILITY.value: str(definition.capability),
            ProvenanceField.USER_ID.value: user_id,
            ProvenanceField.TASK_ID.value: task_id,
            ProvenanceField.STATUS.value: "authorized",
            ProvenanceField.STARTED_AT.value: utcnow_iso(),
        }

    def _build_record(
        self,
        *,
        definition: ToolDefinition,
        user_id: int,
        task_id: int,
        input_digest: str,
        input_bytes: int,
        output_digest: str,
        output_bytes: int,
        started_at: str,
        finished_at: str,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        """Assemble the completed-invocation record and check declared needs.

        The raw input is never stored. ``input_digest`` identifies exactly which
        input ran — the same digest reproduces the same call — without copying
        caller-supplied content, which may be sensitive, into an audit table.
        This is an identifier, not tamper evidence: nothing here is signed or
        chained, so it cannot be called proof that the record is unaltered.
        """

        record: dict[str, Any] = {
            ProvenanceField.TOOL_ID.value: definition.tool_id,
            ProvenanceField.TOOL_VERSION.value: definition.version,
            ProvenanceField.CAPABILITY.value: str(definition.capability),
            ProvenanceField.USER_ID.value: user_id,
            ProvenanceField.TASK_ID.value: task_id,
            ProvenanceField.STATUS.value: "ok",
            ProvenanceField.INPUT_DIGEST.value: input_digest,
            ProvenanceField.INPUT_BYTES.value: input_bytes,
            ProvenanceField.OUTPUT_DIGEST.value: output_digest,
            ProvenanceField.OUTPUT_BYTES.value: output_bytes,
            ProvenanceField.STARTED_AT.value: started_at,
            ProvenanceField.FINISHED_AT.value: finished_at,
            ProvenanceField.ELAPSED_MS.value: elapsed_ms,
        }
        missing = sorted(
            field.value
            for field in definition.provenance_fields
            if record.get(field.value) is None
        )
        if missing:
            raise ToolExecutionFailed(
                f"invocation record for {definition.tool_id!r} is missing required "
                f"provenance fields {missing}"
            )
        return record

    def _record_failure(
        self,
        *,
        definition: ToolDefinition,
        user_id: int,
        task_id: int,
        started_at: str,
        elapsed_ms: int,
        error_code: str,
    ) -> None:
        """Record a failed invocation. Never raises.

        A failure has no output, so the output fields are absent rather than
        empty. If the audit write itself fails the tool failure still surfaces:
        losing a record must not mask the reason the tool failed.
        """

        try:
            self._record_event(
                task_id=task_id,
                event_type=TOOL_COMPLETED_EVENT,
                detail={
                    ProvenanceField.TOOL_ID.value: definition.tool_id,
                    ProvenanceField.TOOL_VERSION.value: definition.version,
                    ProvenanceField.CAPABILITY.value: str(definition.capability),
                    ProvenanceField.USER_ID.value: user_id,
                    ProvenanceField.TASK_ID.value: task_id,
                    ProvenanceField.STATUS.value: "failed",
                    ProvenanceField.STARTED_AT.value: started_at,
                    ProvenanceField.FINISHED_AT.value: utcnow_iso(),
                    ProvenanceField.ELAPSED_MS.value: elapsed_ms,
                    "error_code": error_code,
                },
            )
        except Exception:
            logger.exception("could not record tool failure provenance")

    def _record_event(
        self, *, task_id: int, event_type: str, detail: Mapping[str, Any]
    ) -> int:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO provenance_events "
                "(task_id, execution_id, event_type, actor, detail_json, created_at) "
                "VALUES (?, NULL, ?, ?, ?, ?)",
                (task_id, event_type, TOOL_ACTOR, canonical_json(detail), utcnow_iso()),
            )
            event_id = cursor.lastrowid
            if event_id is None:
                raise RuntimeError("provenance insert returned no row id")
        return int(event_id)

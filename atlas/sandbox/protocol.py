"""The wire contract between the Windows supervisor and the Linux guest.

This module is the only thing both sides are guaranteed to agree on, so it is
deliberately the most boring code in the subsystem: no ``atlas`` imports, no
third-party dependencies, nothing that would fail to import under a bare
CPython. The guest copy is installed as a standalone module
(``atlasx_protocol.py``) rather than as part of the ``atlas`` package, because
the guest's ``atlas`` tree is a curated payload and this file must never depend
on it.

Two directions, both single JSON documents, both bounded:

* The supervisor writes one :class:`Request` to the launcher's stdin. A request
  names the tool, its already-validated arguments, the authorized identity, an
  owner-scoped data snapshot, the resource limits, and the paths the guest may
  use. It carries no host path, no database handle, no secret, and no
  environment from the caller.
* The launcher writes one :class:`Envelope` to its stdout. An envelope reports
  either a validated tool output or a classified failure. The worker's own
  stdout and stderr never travel on this channel: they are captured into the
  workspace as bounded diagnostic files, so a chatty or hostile tool body cannot
  forge a result by writing to fd 1.

Every decoder is strict. Unknown keys, wrong types, out-of-range numbers, and
oversized documents are rejected rather than ignored, because a lenient decode
here would be a place where the trusted side's intent silently becomes something
the sandboxed side acts on differently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping

#: Bumped whenever the request or envelope shape changes incompatibly. The
#: launcher refuses a version it does not implement rather than guessing.
PROTOCOL_VERSION: Final = 1

#: Identity of the worker process *inside* the namespace. The launcher checks
#: this back, so a worker that somehow ran as root is a violation rather than a
#: successful call.
WORKER_UID: Final = 65534
WORKER_GID: Final = 65534

#: Where the guest payload and workspaces live. These are guest paths, never
#: host paths; nothing on the Windows side is derived from them.
GUEST_ROOT: Final = "/opt/atlasx"
GUEST_PAYLOAD_DIR: Final = "/opt/atlasx/lib"
GUEST_WORKSPACE_ROOT: Final = "/var/lib/atlasx/workspaces"
GUEST_LAUNCHER: Final = "/opt/atlasx/bin/atlasx-launcher"
GUEST_PYTHON: Final = "/opt/atlasx/venv/bin/python3"

#: Ceilings on the trust boundary itself. A request larger than this is refused
#: before parsing, so a bug upstream cannot turn into unbounded guest work.
MAX_REQUEST_BYTES: Final = 8 * 1024 * 1024
MAX_ENVELOPE_BYTES: Final = 8 * 1024 * 1024
MAX_ARGUMENT_BYTES: Final = 8 * 1024 * 1024
MAX_DIAGNOSTIC_BYTES: Final = 64 * 1024
MAX_SNAPSHOT_ROWS: Final = 500
MAX_SNAPSHOT_RESOURCES: Final = 32

#: Hard ceilings a request may not exceed, whatever the tool or settings ask
#: for. These mirror ``atlas.tools.definition`` and are duplicated here on
#: purpose: the guest has no access to that module's constants and must not
#: import it to learn them.
CEILING_TIMEOUT_SECONDS: Final = 600
CEILING_MEMORY_MB: Final = 4096
CEILING_PIDS_MAX: Final = 4096
CEILING_CPU_CORES: Final = 8
CEILING_OUTPUT_BYTES: Final = 4 * 1024 * 1024
CEILING_ARTIFACT_BYTES: Final = 64 * 1024 * 1024

#: Floor for a process cap. ``pids.max=1`` would make the worker's own
#: interpreter unable to start reliably, so the minimum is the interpreter plus
#: a small margin.
FLOOR_PIDS_MAX: Final = 8
FLOOR_MEMORY_MB: Final = 64


class ProtocolError(ValueError):
    """A document did not satisfy this protocol.

    Raised on both sides. The supervisor turns it into a refusal and the
    launcher turns it into an ``internal_error`` envelope; neither continues
    with a partially-understood request.
    """


class Status(str, Enum):
    """How the invocation ended."""

    #: A tool body ran to completion and produced a JSON object.
    OK = "ok"
    #: The sandbox held and the tool body itself raised a tool error.
    TOOL_ERROR = "tool_error"
    #: A declared control was violated, or the request asked for something the
    #: policy refuses.
    POLICY_DENIED = "policy_denied"
    #: The wall-clock bound expired and the process tree was killed.
    TIMEOUT = "timeout"
    #: A cgroup or size bound was exceeded.
    RESOURCE_EXCEEDED = "resource_exceeded"
    #: The sandbox itself could not be established or reported a fault.
    INTERNAL_ERROR = "internal_error"


class ViolationKind(str, Enum):
    """What kind of control was crossed.

    These are the labels the final report maps onto guarantees and
    non-guarantees, so they are specific enough to distinguish "tried to open
    the network" from "the network was unavailable for an unrelated reason".
    """

    NETWORK_ACCESS = "network_access"
    FILESYSTEM_ESCAPE = "filesystem_escape"
    HOST_PATH_ACCESS = "host_path_access"
    PROJECT_TREE_ACCESS = "project_tree_access"
    SECRET_ACCESS = "secret_access"
    DATABASE_ACCESS = "database_access"
    PRIVILEGE_ESCALATION = "privilege_escalation"
    PROCESS_LIMIT = "process_limit"
    MEMORY_LIMIT = "memory_limit"
    CPU_LIMIT = "cpu_limit"
    OUTPUT_LIMIT = "output_limit"
    ARTIFACT_LIMIT = "artifact_limit"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    INTERNAL_ERROR = "internal_error"
    PROTOCOL_ERROR = "protocol_error"


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolError(f"{name} must be a JSON object")
    for key in value:
        if not isinstance(key, str):
            raise ProtocolError(f"{name} keys must be strings")
    return value


def _require_exact_keys(value: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ProtocolError(
            f"{name} has the wrong fields (missing={missing}, unexpected={unexpected})"
        )


def _require_int(
    value: object, name: str, *, minimum: int, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProtocolError(f"{name} must be an integer")
    if value < minimum:
        raise ProtocolError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ProtocolError(f"{name} must be <= {maximum}")
    return value


def _require_str(value: object, name: str, *, maximum_length: int = 128) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{name} must be a non-empty string")
    if len(value) > maximum_length:
        raise ProtocolError(f"{name} must be at most {maximum_length} characters")
    return value


def _require_enum(value: object, name: str, enum_type: type[Enum]) -> str:
    if not isinstance(value, str):
        raise ProtocolError(f"{name} must be a string")
    try:
        return str(enum_type(value).value)
    except ValueError as exc:
        allowed = sorted(member.value for member in enum_type)
        raise ProtocolError(f"{name} must be one of {allowed}") from exc


@dataclass(frozen=True)
class Limits:
    """The resource bounds one invocation runs under.

    These are the values actually applied, not the values requested. The
    supervisor has already clamped them against the ceilings above, so the
    guest can apply them without re-deriving a policy decision.
    """

    timeout_seconds: int
    memory_mb: int
    pids_max: int
    cpu_cores: float
    max_output_bytes: int
    max_artifact_bytes: int

    def as_json(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "memory_mb": self.memory_mb,
            "pids_max": self.pids_max,
            "cpu_cores": self.cpu_cores,
            "max_output_bytes": self.max_output_bytes,
            "max_artifact_bytes": self.max_artifact_bytes,
        }

    @classmethod
    def from_json(cls, value: object) -> Limits:
        data = _require_mapping(value, "limits")
        _require_exact_keys(
            data,
            frozenset(
                {
                    "timeout_seconds",
                    "memory_mb",
                    "pids_max",
                    "cpu_cores",
                    "max_output_bytes",
                    "max_artifact_bytes",
                }
            ),
            "limits",
        )
        cores = data["cpu_cores"]
        if isinstance(cores, bool) or not isinstance(cores, (int, float)):
            raise ProtocolError("limits.cpu_cores must be a number")
        if not 0 < float(cores) <= CEILING_CPU_CORES:
            raise ProtocolError(f"limits.cpu_cores must be in (0, {CEILING_CPU_CORES}]")
        return cls(
            timeout_seconds=_require_int(
                data["timeout_seconds"],
                "limits.timeout_seconds",
                minimum=1,
                maximum=CEILING_TIMEOUT_SECONDS,
            ),
            memory_mb=_require_int(
                data["memory_mb"],
                "limits.memory_mb",
                minimum=FLOOR_MEMORY_MB,
                maximum=CEILING_MEMORY_MB,
            ),
            pids_max=_require_int(
                data["pids_max"],
                "limits.pids_max",
                minimum=FLOOR_PIDS_MAX,
                maximum=CEILING_PIDS_MAX,
            ),
            cpu_cores=float(cores),
            max_output_bytes=_require_int(
                data["max_output_bytes"],
                "limits.max_output_bytes",
                minimum=1,
                maximum=CEILING_OUTPUT_BYTES,
            ),
            max_artifact_bytes=_require_int(
                data["max_artifact_bytes"],
                "limits.max_artifact_bytes",
                minimum=1,
                maximum=CEILING_ARTIFACT_BYTES,
            ),
        )


@dataclass(frozen=True)
class Snapshot:
    """Owner-scoped rows for one resource kind, for the authorized task.

    This is the replacement for a database connection. The supervisor reads the
    rows through the same owner-scoped view the platform already uses, so what
    arrives in the guest is exactly the set the caller was entitled to see and
    nothing more. The worker has no way to ask for a different owner, a
    different task, or a row that is not in the snapshot.

    ``parent_column`` names the column a ``parent_id`` filter applies to, or is
    ``None`` for a resource that is not parented. It is carried in the snapshot
    rather than hardcoded in the worker so the guest never encodes knowledge of
    the host schema.
    """

    resource: str
    parent_column: str | None
    rows: tuple[Mapping[str, Any], ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "resource": self.resource,
            "parent_column": self.parent_column,
            "rows": [dict(row) for row in self.rows],
        }

    @classmethod
    def from_json(cls, value: object) -> Snapshot:
        data = _require_mapping(value, "snapshot")
        _require_exact_keys(data, frozenset({"resource", "parent_column", "rows"}), "snapshot")
        raw_rows = data["rows"]
        if not isinstance(raw_rows, list):
            raise ProtocolError("snapshot.rows must be a list")
        if len(raw_rows) > MAX_SNAPSHOT_ROWS:
            raise ProtocolError(
                f"snapshot.rows exceeds {MAX_SNAPSHOT_ROWS} rows for one resource"
            )
        parent_column = data["parent_column"]
        if parent_column is not None and (
            not isinstance(parent_column, str) or not parent_column
        ):
            raise ProtocolError("snapshot.parent_column must be a string or null")
        rows: list[Mapping[str, Any]] = []
        for row in raw_rows:
            rows.append(dict(_require_mapping(row, "snapshot.rows[]")))
        return cls(
            resource=_require_str(data["resource"], "snapshot.resource", maximum_length=64),
            parent_column=parent_column,
            rows=tuple(rows),
        )


@dataclass(frozen=True)
class Request:
    """One sandboxed tool invocation, as the guest receives it."""

    protocol_version: int
    execution_id: str
    tool_id: str
    tool_version: str
    implementation_id: str
    user_id: int
    task_id: int
    arguments: Mapping[str, Any]
    snapshots: tuple[Snapshot, ...]
    limits: Limits
    #: Extra variables the worker is permitted to see, beyond the fixed set the
    #: worker itself sets. The supervisor only ever puts non-secret, structural
    #: values here.
    extra_env: Mapping[str, str] = field(default_factory=dict)
    #: Names of host paths that must stay unreadable. Carried so the guest can
    #: assert their absence rather than trusting the supervisor's argv.
    denied_paths: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "execution_id": self.execution_id,
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "implementation_id": self.implementation_id,
            "user_id": self.user_id,
            "task_id": self.task_id,
            "arguments": dict(self.arguments),
            "snapshots": [snapshot.as_json() for snapshot in self.snapshots],
            "limits": self.limits.as_json(),
            "extra_env": dict(self.extra_env),
            "denied_paths": list(self.denied_paths),
        }

    @classmethod
    def from_json(cls, value: object) -> Request:
        data = _require_mapping(value, "request")
        _require_exact_keys(
            data,
            frozenset(
                {
                    "protocol_version",
                    "execution_id",
                    "tool_id",
                    "tool_version",
                    "implementation_id",
                    "user_id",
                    "task_id",
                    "arguments",
                    "snapshots",
                    "limits",
                    "extra_env",
                    "denied_paths",
                }
            ),
            "request",
        )
        version = _require_int(
            data["protocol_version"], "protocol_version", minimum=1, maximum=1
        )
        if version != PROTOCOL_VERSION:
            raise ProtocolError(
                f"unsupported protocol version {version}; this launcher speaks "
                f"{PROTOCOL_VERSION}"
            )
        raw_snapshots = data["snapshots"]
        if not isinstance(raw_snapshots, list):
            raise ProtocolError("snapshots must be a list")
        if len(raw_snapshots) > MAX_SNAPSHOT_RESOURCES:
            raise ProtocolError("snapshots exceeds the supported resource count")
        seen: set[str] = set()
        snapshots = tuple(Snapshot.from_json(item) for item in raw_snapshots)
        for snapshot in snapshots:
            if snapshot.resource in seen:
                raise ProtocolError(f"duplicate snapshot for {snapshot.resource!r}")
            seen.add(snapshot.resource)

        extra_env_raw = _require_mapping(data["extra_env"], "extra_env")
        extra_env: dict[str, str] = {}
        for key, item in extra_env_raw.items():
            if not key.isidentifier() or key.startswith("_"):
                raise ProtocolError("extra_env keys must be plain identifiers")
            extra_env[key] = _require_str(item, f"extra_env[{key}]", maximum_length=512)

        denied = data["denied_paths"]
        if not isinstance(denied, list) or any(not isinstance(item, str) for item in denied):
            raise ProtocolError("denied_paths must be a list of strings")

        arguments = dict(_require_mapping(data["arguments"], "arguments"))
        encoded = json.dumps(arguments, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_ARGUMENT_BYTES:
            raise ProtocolError("arguments exceed the serialized argument bound")

        return cls(
            protocol_version=version,
            execution_id=_require_str(
                data["execution_id"], "execution_id", maximum_length=64
            ),
            tool_id=_require_str(data["tool_id"], "tool_id", maximum_length=64),
            tool_version=_require_str(
                data["tool_version"], "tool_version", maximum_length=32
            ),
            implementation_id=_require_str(
                data["implementation_id"], "implementation_id", maximum_length=256
            ),
            user_id=_require_int(data["user_id"], "user_id", minimum=1, maximum=2**31 - 1),
            task_id=_require_int(data["task_id"], "task_id", minimum=1, maximum=2**31 - 1),
            arguments=arguments,
            snapshots=snapshots,
            limits=Limits.from_json(data["limits"]),
            extra_env=extra_env,
            denied_paths=tuple(denied),
        )


@dataclass(frozen=True)
class Diagnostics:
    """Bounded, non-authoritative detail about how an invocation ended."""

    exit_code: int | None
    signal: int | None
    stdout: str
    stderr: str
    cgroup_peak_bytes: int | None
    cgroup_events: Mapping[str, int]
    #: Extra structured observations, always present so a decoder never has to
    #: branch on whether the launcher had anything to say. Used for facts the
    #: launcher can only establish from outside the sandbox, such as which
    #: recorded descendant pids were still alive after the kill. Never
    #: authoritative: a caller that treats these as a verdict is misreading them.
    observations: Mapping[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "signal": self.signal,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "cgroup_peak_bytes": self.cgroup_peak_bytes,
            "cgroup_events": dict(self.cgroup_events),
            "observations": dict(self.observations),
        }

    @classmethod
    def from_json(cls, value: object) -> Diagnostics:
        data = _require_mapping(value, "diagnostics")
        _require_exact_keys(
            data,
            frozenset(
                {
                    "exit_code",
                    "signal",
                    "stdout",
                    "stderr",
                    "cgroup_peak_bytes",
                    "cgroup_events",
                    "observations",
                }
            ),
            "diagnostics",
        )
        events_raw = _require_mapping(data["cgroup_events"], "diagnostics.cgroup_events")
        events: dict[str, int] = {}
        for key, item in events_raw.items():
            if isinstance(item, bool) or not isinstance(item, int):
                raise ProtocolError("cgroup_events values must be integers")
            events[_require_str(key, "cgroup_events key", maximum_length=64)] = item
        peak = data["cgroup_peak_bytes"]
        if peak is not None and (isinstance(peak, bool) or not isinstance(peak, int)):
            raise ProtocolError("cgroup_peak_bytes must be an integer or null")
        return cls(
            exit_code=(
                None
                if data["exit_code"] is None
                else _require_int(data["exit_code"], "exit_code", minimum=-2**31, maximum=2**31)
            ),
            signal=(
                None
                if data["signal"] is None
                else _require_int(data["signal"], "signal", minimum=0, maximum=64)
            ),
            stdout=_require_str(
                data["stdout"], "stdout", maximum_length=MAX_DIAGNOSTIC_BYTES
            )
            if data["stdout"]
            else "",
            stderr=_require_str(
                data["stderr"], "stderr", maximum_length=MAX_DIAGNOSTIC_BYTES
            )
            if data["stderr"]
            else "",
            cgroup_peak_bytes=peak,
            cgroup_events=events,
            observations=dict(
                _require_mapping(data["observations"], "diagnostics.observations")
            ),
        )


@dataclass(frozen=True)
class Envelope:
    """The single document the launcher writes to stdout."""

    protocol_version: int
    status: str
    violation: str | None
    output: Mapping[str, Any] | None
    error_message: str | None
    elapsed_ms: int
    diagnostics: Diagnostics
    #: The platform error code the confined side classified this failure as, from
    #: :class:`atlas.tools.errors.ToolErrorCode`. Carried as a value rather than
    #: left inside ``error_message`` because the taxonomy is the point of having
    #: one: when a tool rejected its own input, the host has to be able to raise
    #: ``ToolInputInvalid`` and not a generic execution failure. Recovering the
    #: code from the message text would be parsing a sentence to recover a
    #: structured field, which breaks the moment the wording changes.
    error_code: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "status": self.status,
            "violation": self.violation,
            "output": None if self.output is None else dict(self.output),
            "error_message": self.error_message,
            "error_code": self.error_code,
            "elapsed_ms": self.elapsed_ms,
            "diagnostics": self.diagnostics.as_json(),
        }

    @classmethod
    def from_json(cls, value: object) -> Envelope:
        data = _require_mapping(value, "envelope")
        _require_exact_keys(
            data,
            frozenset(
                {
                    "protocol_version",
                    "status",
                    "violation",
                    "output",
                    "error_message",
                    "error_code",
                    "elapsed_ms",
                    "diagnostics",
                }
            ),
            "envelope",
        )
        version = _require_int(
            data["protocol_version"], "protocol_version", minimum=1, maximum=1
        )
        status = _require_enum(data["status"], "status", Status)
        violation_raw = data["violation"]
        if violation_raw is None:
            violation: str | None = None
        else:
            violation = _require_enum(violation_raw, "violation", ViolationKind)
        output_raw = data["output"]
        if output_raw is None:
            output: Mapping[str, Any] | None = None
        else:
            output = dict(_require_mapping(output_raw, "output"))
        message_raw = data["error_message"]
        if message_raw is not None and not isinstance(message_raw, str):
            raise ProtocolError("error_message must be a string or null")
        code_raw = data["error_code"]
        if code_raw is not None and not isinstance(code_raw, str):
            raise ProtocolError("error_code must be a string or null")
        return cls(
            protocol_version=version,
            status=status,
            violation=violation,
            output=output,
            error_message=message_raw,
            elapsed_ms=_require_int(
                data["elapsed_ms"], "elapsed_ms", minimum=0, maximum=2**31 - 1
            ),
            diagnostics=Diagnostics.from_json(data["diagnostics"]),
            error_code=code_raw,
        )


@dataclass(frozen=True)
class WorkerReport:
    """What the worker itself concluded, before the launcher adds diagnostics.

    The worker is the only component that ran inside the confinement, so this
    is the report the launcher wraps. It is kept separate from
    :class:`Envelope` because the fields the launcher fills in — exit status,
    captured streams, cgroup accounting, elapsed time — are observed from
    outside, and mixing them with the worker's own claim would make it
    impossible to tell which parts of a failure the sandboxed side reported.
    """

    status: str
    violation: str | None
    output: Mapping[str, Any] | None
    error_message: str | None
    error_code: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "violation": self.violation,
            "output": None if self.output is None else dict(self.output),
            "error_message": self.error_message,
            "error_code": self.error_code,
        }

    @classmethod
    def from_json(cls, value: object) -> WorkerReport:
        data = _require_mapping(value, "worker report")
        _require_exact_keys(
            data,
            frozenset(
                {"status", "violation", "output", "error_message", "error_code"}
            ),
            "worker report",
        )
        status = _require_enum(data["status"], "worker status", Status)
        violation_raw = data["violation"]
        violation: str | None
        if violation_raw is None:
            violation = None
        else:
            violation = _require_enum(violation_raw, "worker violation", ViolationKind)
        if status is Status.OK and violation is not None:
            raise ProtocolError("a successful worker report cannot name a violation")
        output_raw = data["output"]
        output = (
            None
            if output_raw is None
            else dict(_require_mapping(output_raw, "worker output"))
        )
        message_raw = data["error_message"]
        if message_raw is not None and not isinstance(message_raw, str):
            raise ProtocolError("worker error_message must be a string or null")
        code_raw = data["error_code"]
        if code_raw is not None and not isinstance(code_raw, str):
            raise ProtocolError("worker error_code must be a string or null")
        return cls(
            status=status,
            violation=violation,
            output=output,
            error_message=message_raw,
            error_code=code_raw,
        )


def _dumps(document: Mapping[str, Any], limit: int, what: str) -> bytes:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > limit:
        raise ProtocolError(f"{what} exceeds the {limit}-byte transfer bound")
    return encoded


def encode_request(request: Request) -> bytes:
    """Serialize a request for the launcher's stdin."""

    return _dumps(request.as_json(), MAX_REQUEST_BYTES, "request")


def decode_request(payload: bytes) -> Request:
    """Parse and strictly validate a request."""

    if len(payload) > MAX_REQUEST_BYTES:
        raise ProtocolError("request exceeds the transfer bound")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"request is not valid UTF-8 JSON: {exc}") from exc
    return Request.from_json(document)


def encode_envelope(envelope: Envelope) -> bytes:
    """Serialize an envelope for the launcher's stdout."""

    return _dumps(envelope.as_json(), MAX_ENVELOPE_BYTES, "envelope")


def decode_envelope(payload: bytes) -> Envelope:
    """Parse and strictly validate an envelope."""

    if len(payload) > MAX_ENVELOPE_BYTES:
        raise ProtocolError("envelope exceeds the transfer bound")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"envelope is not valid UTF-8 JSON: {exc}") from exc
    return Envelope.from_json(document)

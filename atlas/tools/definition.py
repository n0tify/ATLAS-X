"""The registered-tool definition: everything a tool is, declared as data.

A :class:`ToolDefinition` is the whole of a tool's identity and its whole of its
contract. It carries the capability name authorization checks, the schemas the
dispatcher validates against, the limits it enforces, and the declarations that
say what the tool touches. The implementation is a callable held by the
definition; the *string* :attr:`ToolDefinition.implementation_id` is audit
metadata only and is never resolved at runtime, so a tool id can never become a
module path, an import, or a command.

Registration is the only moment a tool becomes reachable, and it is refused
outright when a tool declares something Phase 09 does not provide. The
admissible sets are named refusals, not dormant features:

* ``FilesystemAccess.HOST_READ`` / ``HOST_WRITE`` are not registrable. The
  sandbox exists now, but no tool in this design is given host filesystem access,
  so the refusal is a decision rather than a wait.
* ``NetworkAccess.ALLOWED`` is not registrable at all. No network-capable tool
  exists in this design, so the refusal is permanent rather than deferred.
* ``Determinism.NON_DETERMINISTIC`` is not registrable, because verification
  and benchmarking (Phases 13 and 21) consume the determinism declaration and
  cannot reason about an undeclared one.

Declaring these is not a way to get them later. Widening the admissible set is
a deliberate change to this module, reviewed with the phase that supplies the
missing control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from atlas.security.policy import PROHIBITED_TOOL_CAPABILITIES, normalize_tool_name
from atlas.tools.errors import ToolDefinitionInvalid, ToolUnsupported
from atlas.tools.schema import ToolSchema, describe

#: A tool id is a single lowercase snake_case segment. No dots, separators, or
#: path characters, so a tool id cannot be read as a module path, a file path,
#: a command, or an executable name.
TOOL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
MIN_TOOL_ID_LENGTH = 3
MAX_TOOL_ID_LENGTH = 64

MAX_TIMEOUT_SECONDS = 600
MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024


class FilesystemAccess(str, Enum):
    """What a tool declares about host filesystem access."""

    NONE = "none"
    HOST_READ = "host_read"
    HOST_WRITE = "host_write"


class NetworkAccess(str, Enum):
    """What a tool declares about network access."""

    NONE = "none"
    ALLOWED = "allowed"


class Determinism(str, Enum):
    """Whether identical input under identical relevant state yields the same output."""

    DETERMINISTIC = "deterministic"
    STATE_DEPENDENT = "state_dependent"
    NON_DETERMINISTIC = "non_deterministic"


class ProvenanceField(str, Enum):
    """Fields a tool can require in its invocation record.

    The dispatcher produces all of them, so a definition may require any subset.
    Requiring a field is a real check: dispatch verifies the assembled record
    actually carries every declared field and fails if it does not.
    """

    TOOL_ID = "tool_id"
    TOOL_VERSION = "tool_version"
    CAPABILITY = "capability"
    USER_ID = "user_id"
    TASK_ID = "task_id"
    STATUS = "status"
    INPUT_DIGEST = "input_digest"
    INPUT_BYTES = "input_bytes"
    OUTPUT_DIGEST = "output_digest"
    OUTPUT_BYTES = "output_bytes"
    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    ELAPSED_MS = "elapsed_ms"


AVAILABLE_PROVENANCE_FIELDS: frozenset[ProvenanceField] = frozenset(ProvenanceField)

#: Admissible in Phase 09. See the module docstring for why each refusal is
#: permanent and which phase owns the missing control.
ADMISSIBLE_FILESYSTEM_ACCESS: frozenset[FilesystemAccess] = frozenset(
    {FilesystemAccess.NONE}
)
ADMISSIBLE_NETWORK_ACCESS: frozenset[NetworkAccess] = frozenset({NetworkAccess.NONE})
ADMISSIBLE_DETERMINISM: frozenset[Determinism] = frozenset(
    {Determinism.DETERMINISTIC, Determinism.STATE_DEPENDENT}
)


@dataclass(frozen=True)
class ToolLimits:
    """Per-invocation bounds declared by the tool itself.

    These are application-level controls. ``timeout_seconds`` is checked after
    the call returns, so it detects an overlong invocation and cannot interrupt
    one; bounding an in-progress call needs the Phase 10 sandbox. ``None`` for
    ``max_artifact_bytes`` means the tool produces no artifact, which is the
    honest value for every tool in Phase 09.
    """

    max_input_bytes: int
    max_output_bytes: int
    timeout_seconds: int
    max_artifact_bytes: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_input_bytes", self.max_input_bytes),
            ("max_output_bytes", self.max_output_bytes),
            ("timeout_seconds", self.timeout_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ToolDefinitionInvalid(f"{name} must be a positive integer")
        if self.max_input_bytes > MAX_INPUT_BYTES:
            raise ToolDefinitionInvalid(f"max_input_bytes above ceiling {MAX_INPUT_BYTES}")
        if self.max_output_bytes > MAX_OUTPUT_BYTES:
            raise ToolDefinitionInvalid(f"max_output_bytes above ceiling {MAX_OUTPUT_BYTES}")
        if self.timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ToolDefinitionInvalid(
                f"timeout_seconds above ceiling {MAX_TIMEOUT_SECONDS}"
            )
        if self.max_artifact_bytes is not None:
            if (
                isinstance(self.max_artifact_bytes, bool)
                or not isinstance(self.max_artifact_bytes, int)
                or self.max_artifact_bytes <= 0
            ):
                raise ToolDefinitionInvalid(
                    "max_artifact_bytes must be a positive integer or None"
                )


class ToolContext:
    """What an implementation is allowed to see.

    The caller identity and task are already authorized by the time a tool
    runs, so they are passed explicitly rather than re-derived. Database access
    is offered only through :attr:`view`, an owner-scoped read-only accessor:
    no tool implementation ever receives a connection, so a tool cannot widen
    its own access beyond the owner it was already authorized for.
    """

    __slots__ = ("_task_id", "_user_id", "_view")

    def __init__(self, *, user_id: int, task_id: int, view: Any) -> None:
        self._user_id = user_id
        self._task_id = task_id
        self._view = view

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def task_id(self) -> int:
        return self._task_id

    @property
    def view(self) -> Any:
        """Owner-scoped read-only accessor. Never a database connection."""

        return self._view

    def __repr__(self) -> str:
        return f"ToolContext(user_id={self._user_id}, task_id={self._task_id})"


class ToolImplementation(Protocol):
    """A registered tool body: validated arguments in, JSON-ready mapping out."""

    def __call__(
        self, context: ToolContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class ToolDefinition:
    """A registered tool and its complete declared contract."""

    tool_id: str
    title: str
    description: str
    version: str
    input_schema: ToolSchema
    output_schema: ToolSchema
    limits: ToolLimits
    determinism: Determinism
    provenance_fields: frozenset[ProvenanceField]
    implementation: ToolImplementation = field(repr=False, compare=False)
    implementation_id: str
    capability: str | None = None
    filesystem_access: FilesystemAccess = FilesystemAccess.NONE
    network_access: NetworkAccess = NetworkAccess.NONE
    # ``True`` by default, and that default is the security property rather than a
    # convenience. Phase 09 defaulted this to ``False`` because a tool body ran in
    # the ATLAS-X process and needed no confinement; Phase 10B moved every body into
    # the WSL guest, so the opt-out no longer describes anything real. Defaulting to
    # ``False`` would mean the *omission* of a line silently removes a tool from the
    # sandbox -- and an omission is not something a security review reliably notices,
    # whereas an explicit opt-out is. Every tool is therefore confined unless it says
    # otherwise in its own source.
    requires_sandbox: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_tool_id()
        self._validate_capability()
        self._validate_text_fields()
        self._validate_declarations()
        self._validate_provenance_requirements()
        self._validate_implementation()

    def _validate_tool_id(self) -> None:
        if not isinstance(self.tool_id, str):
            raise ToolDefinitionInvalid("tool_id must be a string")
        if not MIN_TOOL_ID_LENGTH <= len(self.tool_id) <= MAX_TOOL_ID_LENGTH:
            raise ToolDefinitionInvalid(
                f"tool_id must be {MIN_TOOL_ID_LENGTH}..{MAX_TOOL_ID_LENGTH} characters"
            )
        if not TOOL_ID_PATTERN.fullmatch(self.tool_id):
            raise ToolDefinitionInvalid(
                "tool_id must be lowercase snake_case with no separators or dots"
            )

    def _validate_capability(self) -> None:
        capability = self.capability or self.tool_id
        if not isinstance(capability, str) or not capability:
            raise ToolDefinitionInvalid("capability must be a non-empty string")
        normalized = normalize_tool_name(capability)
        if normalized is None:
            raise ToolDefinitionInvalid("capability is not a usable name")
        if normalized in PROHIBITED_TOOL_CAPABILITIES:
            # The policy would deny this at dispatch anyway. Refusing it here
            # means a prohibited capability is never registered in the first
            # place, so it cannot appear in a listing or in provenance.
            raise ToolUnsupported(
                f"capability {capability!r} is prohibited and can never be granted"
            )
        if normalized != normalize_tool_name(self.tool_id):
            # Both the declared capability and the tool id are compared in
            # normalized form, because that is the form the policy matches
            # against on both sides: the capability at dispatch and the stored
            # grant. A tool whose two names normalize differently could be
            # granted under one name and dispatched under the other.
            raise ToolDefinitionInvalid(
                "capability must normalize to the same name as the tool id so "
                "grants cannot diverge"
            )
        object.__setattr__(self, "capability", self.tool_id)

    def _validate_text_fields(self) -> None:
        for name, value in (
            ("title", self.title),
            ("description", self.description),
            ("version", self.version),
            ("implementation_id", self.implementation_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ToolDefinitionInvalid(f"{name} must be a non-empty string")
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            raise ToolDefinitionInvalid("version must be an explicit MAJOR.MINOR.PATCH")

    def _validate_declarations(self) -> None:
        if not isinstance(self.input_schema, ToolSchema) or not isinstance(
            self.output_schema, ToolSchema
        ):
            raise ToolDefinitionInvalid("input_schema and output_schema are required")
        if not isinstance(self.limits, ToolLimits):
            raise ToolDefinitionInvalid("limits are required")
        if self.filesystem_access not in ADMISSIBLE_FILESYSTEM_ACCESS:
            # Still refused, and now for a different reason. ``bwrap`` can confine
            # a declared host read or write to an explicit allowlist, so the
            # control the Phase 09 refusal was waiting for exists. What does not
            # exist is any reviewed decision about *which* host paths a tool may
            # be given, and widening this set is a deliberate change to this
            # module rather than something a tool declaration can talk its way
            # into. The approved tools need no host access: they read owner-scoped
            # rows and compute over them.
            raise ToolUnsupported(
                f"filesystem access {self.filesystem_access.value!r} is not permitted; "
                "no tool in this design is given host filesystem access"
            )
        if self.network_access not in ADMISSIBLE_NETWORK_ACCESS:
            raise ToolUnsupported(
                f"network access {self.network_access.value!r} is not permitted; "
                "no network-capable tool exists in this design"
            )
        if self.determinism not in ADMISSIBLE_DETERMINISM:
            raise ToolUnsupported(
                f"determinism {self.determinism.value!r} cannot be declared; "
                "verification and benchmarking require a declared one"
            )
        if not isinstance(self.requires_sandbox, bool):
            raise ToolDefinitionInvalid("requires_sandbox must be a bool")
        if self.limits.max_artifact_bytes is not None and self.output_schema is None:
            raise ToolDefinitionInvalid("max_artifact_bytes requires an output schema")

    def _validate_provenance_requirements(self) -> None:
        if not self.provenance_fields:
            raise ToolDefinitionInvalid("a tool must require at least one provenance field")
        unknown = self.provenance_fields - AVAILABLE_PROVENANCE_FIELDS
        if unknown:
            raise ToolDefinitionInvalid(
                f"unproducible provenance fields: {sorted(f.value for f in unknown)}"
            )
        if ProvenanceField.TOOL_ID not in self.provenance_fields:
            raise ToolDefinitionInvalid("every tool must require tool_id in provenance")
        if ProvenanceField.TOOL_VERSION not in self.provenance_fields:
            raise ToolDefinitionInvalid("every tool must require tool_version")

    def _validate_implementation(self) -> None:
        if not callable(self.implementation):
            raise ToolDefinitionInvalid("implementation must be callable")
        if not isinstance(self.metadata, Mapping):
            raise ToolDefinitionInvalid("metadata must be a mapping")

    @property
    def normalized_capability(self) -> str:
        return self.tool_id

    def invoke(
        self, context: ToolContext, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Call the registered body. Exists for the dispatcher, not for callers.

        This method exists for the in-process conformance harness and for tests.
        It is **not** the dispatch path: since Phase 10B, dispatch reaches a tool
        body only through :class:`atlas.sandbox.supervisor.SandboxSupervisor`,
        which runs it in a separate Linux process. Calling this on the host gives
        an in-process invocation, which is why the supervisor's guest-side worker
        re-resolves the definition from its own frozen registry instead of
        trusting a callable reference crossing the boundary.

        Reaching a body this way still requires already holding a definition, and
        Python has no access control, so this remains a greppable single entry
        point rather than an enforcement boundary.
        """

        return self.implementation(context, arguments)

    def describe(self) -> dict[str, Any]:
        """Serializable metadata for a listing, a UI, or provenance."""

        return {
            "tool_id": self.tool_id,
            "title": self.title,
            "description": self.description,
            "version": self.version,
            "capability": self.capability,
            "determinism": self.determinism.value,
            "filesystem_access": self.filesystem_access.value,
            "network_access": self.network_access.value,
            "requires_sandbox": self.requires_sandbox,
            "implementation_id": self.implementation_id,
            "input_schema": describe(self.input_schema),
            "output_schema": describe(self.output_schema),
            "limits": {
                "max_input_bytes": self.limits.max_input_bytes,
                "max_output_bytes": self.limits.max_output_bytes,
                "max_artifact_bytes": self.limits.max_artifact_bytes,
                "timeout_seconds": self.limits.timeout_seconds,
            },
            "provenance_fields": sorted(f.value for f in self.provenance_fields),
        }

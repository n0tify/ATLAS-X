"""Bounded, scoped tool execution: a real confinement boundary, not a wrapper.

Phase 10B replaces the Phase 09 arrangement in which a registered tool body ran
in the ATLAS-X process, holding a live view onto the caller's rows. A tool body
is now a Linux process inside a WSL guest, in its own user, PID, network, IPC,
UTS, and mount namespaces, with no capabilities, no ambient environment, no
database handle, and exactly one writable directory: the per-execution
workspace. CPU, memory, and process count come from a cgroup v2 leaf; the wall
clock comes from a timeout that signals the process group and then the cgroup.

The module layout follows the trust boundary rather than the call order:

* :mod:`atlas.sandbox.policy` states the confinement as a value, and refuses a
  policy that has more than one writable path or that would expose a denied one.
* :mod:`atlas.sandbox.namespaces` turns that value into a ``bwrap`` argument
  vector. It is stdlib-only and is installed into the guest, so the argv the
  guest runs is the argv the tests assert.
* :mod:`atlas.sandbox.cgroups` writes the four resource-control files and is
  explicit that ``memory.max`` reclaims rather than kills.
* :mod:`atlas.sandbox.environment` builds the worker's environment from a closed
  allowlist, so no host variable and no secret is inherited.
* :mod:`atlas.sandbox.workspace` snapshots the authorized rows through the
  platform's own owner-scoped view, which is what lets a tool read data without
  being handed a connection.
* :mod:`atlas.sandbox.protocol` is the single wire contract, strict in both
  directions.
* :mod:`atlas.sandbox.guest` holds the three processes that exist inside the
  confinement: the launcher that builds it, the worker that calls a tool body
  inside it, and the conformance harness that tries to escape it.
* :mod:`atlas.sandbox.supervisor` is the only component that crosses the
  Windows/Linux boundary, and it has no in-process path.
* :mod:`atlas.sandbox.provision` installs the runtime into the guest.

Unlike the other ATLAS-X packages, this one re-exports its public names
**lazily** through :func:`__getattr__` rather than eagerly.

The reason is an import cycle, and it is worth being explicit rather than
working around it silently. The sandbox error types are part of the platform's
tool error taxonomy and so live in :mod:`atlas.tools.errors`. Importing that
module executes the ``atlas.tools`` package initializer, which re-exports
:mod:`atlas.tools.dispatch`; the dispatcher imports
:mod:`atlas.sandbox.supervisor`; the supervisor imports
:mod:`atlas.sandbox.errors`; and that module wants the tool error types again. A
sandbox failure must be a ``ToolError`` so the dispatcher's existing failure
recording and codes keep working, so that inheritance is not negotiable — which
leaves lazy re-export as the way to break the cycle without splitting the
taxonomy in two.

The cost is that ``from atlas.sandbox import SandboxSupervisor`` resolves at first
use rather than at import time. That is invisible to callers and it keeps the
taxonomy unified, which is the property that matters for the audit record.

Note the asymmetry with :mod:`atlas.tools`, which re-exports eagerly. The
difference is deliberate and follows from which side of the cycle a package sits:
``atlas.tools.dispatch`` no longer imports the supervisor at module scope, so
``atlas.tools`` can be eager, and the Phase 09 control that keeps ``importlib``
out of the tool layer still holds. This package keeps the lazy form because
nothing can be moved out of ``atlas.sandbox.errors`` without splitting the error
taxonomy in two.

Two things are deliberately not here. There is no "run it in-process if the
sandbox is unavailable" branch, and there is no way to describe a policy that
allows network or a second writable path. Both would be small additions and both
would undo the phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - for type checkers and IDEs only
    from atlas.sandbox.environment import ENVIRONMENT_NAMES, build_environment
    from atlas.sandbox.errors import (
        SandboxError,
        SandboxLauncherMissing,
        SandboxProtocolFailure,
        SandboxTimeout,
        SandboxWorkspaceFailure,
        classify_envelope,
    )
    from atlas.sandbox.namespaces import (
        build_argv,
        probe_merged_usr,
        verify_hidden_absent,
        verify_read_only,
    )
    from atlas.sandbox.policy import (
        HIDDEN_PATHS,
        READ_ONLY_PATHS,
        MountKind,
        MountSpec,
        NetworkPolicy,
        SandboxPolicy,
        build_policy,
        derive_limits,
    )
    from atlas.sandbox.protocol import (
        PROTOCOL_VERSION,
        Envelope,
        Limits,
        ProtocolError,
        Request,
        Snapshot,
        Status,
        ViolationKind,
    )
    from atlas.sandbox.result import MemoryReport, SandboxOutcome
    from atlas.sandbox.supervisor import (
        DEFAULT_DISTRO,
        SandboxConfiguration,
        SandboxSupervisor,
        configuration_from_settings,
    )
    from atlas.sandbox.workspace import PARENT_COLUMNS, SNAPSHOT_RESOURCES, build_snapshots

#: Public name -> the submodule that defines it. Resolved on first access so that
#: importing this package costs nothing and cannot participate in a cycle.
_EXPORTS: dict[str, str] = {
    "ENVIRONMENT_NAMES": "atlas.sandbox.environment",
    "build_environment": "atlas.sandbox.environment",
    "SandboxError": "atlas.sandbox.errors",
    "SandboxLauncherMissing": "atlas.sandbox.errors",
    "SandboxProtocolFailure": "atlas.sandbox.errors",
    "SandboxTimeout": "atlas.sandbox.errors",
    "SandboxWorkspaceFailure": "atlas.sandbox.errors",
    "classify_envelope": "atlas.sandbox.errors",
    "build_argv": "atlas.sandbox.namespaces",
    "probe_merged_usr": "atlas.sandbox.namespaces",
    "verify_hidden_absent": "atlas.sandbox.namespaces",
    "verify_read_only": "atlas.sandbox.namespaces",
    "HIDDEN_PATHS": "atlas.sandbox.policy",
    "READ_ONLY_PATHS": "atlas.sandbox.policy",
    "MountKind": "atlas.sandbox.policy",
    "MountSpec": "atlas.sandbox.policy",
    "NetworkPolicy": "atlas.sandbox.policy",
    "SandboxPolicy": "atlas.sandbox.policy",
    "build_policy": "atlas.sandbox.policy",
    "derive_limits": "atlas.sandbox.policy",
    "PROTOCOL_VERSION": "atlas.sandbox.protocol",
    "Envelope": "atlas.sandbox.protocol",
    "Limits": "atlas.sandbox.protocol",
    "ProtocolError": "atlas.sandbox.protocol",
    "Request": "atlas.sandbox.protocol",
    "Snapshot": "atlas.sandbox.protocol",
    "Status": "atlas.sandbox.protocol",
    "ViolationKind": "atlas.sandbox.protocol",
    "MemoryReport": "atlas.sandbox.result",
    "SandboxOutcome": "atlas.sandbox.result",
    "DEFAULT_DISTRO": "atlas.sandbox.supervisor",
    "SandboxConfiguration": "atlas.sandbox.supervisor",
    "SandboxSupervisor": "atlas.sandbox.supervisor",
    "configuration_from_settings": "atlas.sandbox.supervisor",
    "PARENT_COLUMNS": "atlas.sandbox.workspace",
    "SNAPSHOT_RESOURCES": "atlas.sandbox.workspace",
    "build_snapshots": "atlas.sandbox.workspace",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    return list(__all__)

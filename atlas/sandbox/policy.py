"""The confinement declaration for one sandboxed invocation.

This module is the *statement* of what a tool may touch. Nothing here enforces
anything: :mod:`atlas.sandbox.namespaces` turns this declaration into a
``bwrap`` argument vector, :mod:`atlas.sandbox.cgroups` turns the limits into
cgroup files, and the launcher runs it. Keeping the declaration separate from
the enforcement is what makes the guarantee reviewable — the policy is a value
that can be printed, compared, and asserted against in a test, rather than
control flow buried in a subprocess call.

Two rules are enforced in :meth:`SandboxPolicy.__post_init__` rather than
documented and hoped for:

* **The workspace is the only writable location.** Any other writable path is a
  construction-time error. A single writable root is what makes "a tool wrote
  somewhere it should not have" detectable by inspection rather than by
  filesystem monitoring.
* **A denied path may not contain the workspace, and the workspace may not
  contain a denied path.** Without this, a policy that denied ``/`` and also
  mounted ``/`` would pass every individual field check and expose everything.
  These two are exactly the mistakes that turn a declared guarantee into a
  silent one, so they are refused before a request is ever built.

There is no permissive constructor. Every field is required, there is no
"unknown mount kind" fallback, and :data:`NETWORK_POLICY` has a single member.
Adding a second network policy is a source change to this file, reviewed with
whatever control justifies it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Iterable, Mapping, Sequence

from atlas.sandbox.protocol import (
    CEILING_ARTIFACT_BYTES,
    CEILING_CPU_CORES,
    CEILING_MEMORY_MB,
    CEILING_OUTPUT_BYTES,
    CEILING_PIDS_MAX,
    CEILING_TIMEOUT_SECONDS,
    FLOOR_MEMORY_MB,
    FLOOR_PIDS_MAX,
    PROTOCOL_VERSION,
    Limits,
)

__all__ = [
    "HIDDEN_PATHS",
    "MountKind",
    "MountSpec",
    "NetworkPolicy",
    "READ_ONLY_PATHS",
    "SYSTEM_READ_ONLY",
    "SandboxPolicy",
    "WORKSPACE_PATH",
]

#: The single writable location inside the sandbox, and the only path a tool
#: body can write to at all. ``/tmp`` is a separate private tmpfs, so "writable"
#: means "writable and durable enough to be collected as an artifact", not
#: "writable anywhere".
WORKSPACE_PATH: Final = "/workspace"

INPUT_SUBDIR: Final = "input"
OUTPUT_SUBDIR: Final = "output"
TMP_SUBDIR: Final = "tmp"


class NetworkPolicy(str, Enum):
    """What the sandboxed process may do with a network.

    ``DENY_ALL`` is the only member. A fresh network namespace with no
    interfaces other than a loopback that is never brought up, and no
    ``resolv.conf``, is the control. There is deliberately no
    ``ALLOW_HOST`` escape hatch to configure away: the requirement is that no
    tool can reach the internet, a LAN, a proxy, or a host loopback service, and
    an enum with one value makes "which networks are allowed" a question this
    codebase cannot currently answer with anything but "none".
    """

    DENY_ALL = "deny_all"


class MountKind(str, Enum):
    """How one path appears inside the sandbox."""

    #: Present, read-only, from the guest filesystem.
    RO_BIND = "ro_bind"
    #: Present, writable. Only the workspace may use this.
    RW_BIND = "rw_bind"
    #: Empty, writable, discarded when the process exits.
    TMPFS = "tmpfs"
    #: A fresh ``proc``.
    PROC = "proc"
    #: A minimal ``dev``.
    DEV = "dev"
    #: Present as a symlink, for merged-``/usr`` layouts.
    SYMLINK = "symlink"
    #: An empty directory, so a parent bind has somewhere to land.
    EMPTY_DIR = "empty_dir"
    #: An empty directory that cannot be written to.
    #:
    #: Separate from :attr:`EMPTY_DIR` because ``--dir`` produces a directory the
    #: sandboxed uid owns and can write to, which is almost never what is meant
    #: for a placeholder. ``/etc`` is the case in point: it exists only to give the
    #: three ``ld.so`` files somewhere to land, and leaving it writable let a tool
    #: body drop files into a path that reads as host configuration. It is not an
    #: escape on its own — the directory is private to the namespace and discarded
    #: with it — but it is a writable path that exists for no reason, and it
    #: contradicted what the conformance probe asserts about it.
    RO_EMPTY_DIR = "ro_empty_dir"


#: Read-only guest paths every sandboxed invocation gets. ``/usr`` is the
#: interpreter and the standard library; the three ``ld.so`` paths are the only
#: part of ``/etc`` a dynamically linked Python needs, and they are bound
#: individually rather than by binding ``/etc``, because binding ``/etc`` would
#: hand the process ``resolv.conf``, ``hosts``, and any other host
#: configuration. ``/opt/atlasx`` is the installed payload and interpreter.
SYSTEM_READ_ONLY: Final[tuple[str, ...]] = (
    "/usr",
    "/opt/atlasx/lib",
    "/opt/atlasx/venv",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
)

#: Paths that must not exist inside the sandbox at all. Each is asserted absent
#: by the launcher after the namespace is built, so "we did not bind it" is
#: backed by "we looked and it is not there". ``/mnt`` and ``/media`` are the
#: WSL mount points for the Windows drives, which is where a project checkout,
#: a ``.env`` file, and the application database live on this platform.
HIDDEN_PATHS: Final[tuple[str, ...]] = (
    "/mnt",
    "/media",
    "/srv",
    "/home",
    "/root",
    "/run",
    "/var/lib/atlasx",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/hostname",
)

#: Paths that are *supposed* to exist inside the sandbox and must be unreachable
#: for writing. This is a separate list because "must not exist" and "must not be
#: writable" are different controls, and conflating them is a mistake that has
#: already been made once here: ``/proc/sys`` was listed as hidden, which made
#: every legitimate invocation fail closed, because a ``--proc`` mount *always*
#: contains ``/proc/sys``. Removing the entry without adding it here would have
#: turned a false positive into a silent hole, because ``/proc/sys`` on this
#: kernel is writable from inside the namespace and a write to
#: ``/proc/sys/kernel/core_pattern`` lands on the host — the process-id
#: namespace does not virtualise non-namespaced sysctls, and ``--unshare-user``
#: does not make procfs read-only on its own.
#:
#: So ``/proc`` is mounted and then remounted read-only by :mod:`atlas.sandbox.namespaces`,
#: and these paths are asserted unwritable rather than absent. The check is on
#: write access to an *existing* sysctl, not on the presence of a directory,
#: because a create-in-directory probe would be refused by procfs itself and
#: would therefore pass on a sandbox that is fully vulnerable.
READ_ONLY_PATHS: Final[tuple[str, ...]] = (
    "/proc/sys",
    "/proc/sysrq-trigger",
)


@dataclass(frozen=True)
class MountSpec:
    """One path in the sandbox's mount plan.

    ``source`` is a guest path and is only meaningful for bind and symlink kinds.
    It is never a Windows path: the guest has no way to express one, and a
    policy that tried to smuggle a host path in here would fail at the first
    real launch rather than silently mounting something reachable.
    """

    kind: MountKind
    path: str
    source: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MountKind):
            raise ValueError("mount kind must be a MountKind")
        if not _is_absolute_clean(self.path):
            raise ValueError(f"mount path must be absolute and normalized: {self.path!r}")
        if self.kind in (MountKind.RO_BIND, MountKind.RW_BIND):
            if self.source is None or not _is_absolute_clean(self.source):
                raise ValueError(f"bind mount {self.path!r} needs an absolute source")
        elif self.kind is MountKind.SYMLINK:
            if not self.source:
                raise ValueError(f"symlink {self.path!r} needs a target")
        elif self.source is not None:
            raise ValueError(f"mount kind {self.kind.value!r} takes no source")


def _is_absolute_clean(path: str) -> bool:
    if not isinstance(path, str) or not path.startswith("/"):
        return False
    if path == "/":
        return False
    if path.endswith("/") or "//" in path:
        return False
    if "/../" in path or path.endswith("/..") or "/./" in path:
        return False
    return ".." not in path.split("/")


def _is_prefix(parent: str, child: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("/") + "/")


@dataclass(frozen=True)
class SandboxPolicy:
    """A complete, validated confinement declaration for one invocation."""

    mounts: tuple[MountSpec, ...]
    hidden_paths: tuple[str, ...]
    network: NetworkPolicy
    limits: Limits
    environment_names: tuple[str, ...]
    read_only_paths: tuple[str, ...] = READ_ONLY_PATHS
    workspace: str = WORKSPACE_PATH
    protocol_version: int = PROTOCOL_VERSION
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.network is not NetworkPolicy.DENY_ALL:
            raise ValueError("only NetworkPolicy.DENY_ALL is implemented")
        if self.protocol_version != PROTOCOL_VERSION:
            raise ValueError("policy protocol version does not match the runtime")
        if self.workspace != WORKSPACE_PATH:
            raise ValueError("the workspace path is fixed by the worker contract")
        if not self.mounts:
            raise ValueError("a sandbox with no mounts is not a confinement")
        if not self.environment_names:
            raise ValueError("at least the worker's own fixed environment is required")

        paths = [mount.path for mount in self.mounts]
        if len(paths) != len(set(paths)):
            raise ValueError("two mounts claim the same path")

        writable = [m.path for m in self.mounts if m.kind is MountKind.RW_BIND]
        if writable != [self.workspace]:
            raise ValueError(
                f"the workspace must be the only writable path, found {writable!r}"
            )
        for mount in self.mounts:
            if mount.kind in (MountKind.TMPFS, MountKind.EMPTY_DIR) and mount.path == "/":
                raise ValueError("a tmpfs or empty dir may not be the whole root")

        for hidden in self.hidden_paths:
            if not _is_absolute_clean(hidden):
                raise ValueError(f"hidden path must be absolute and clean: {hidden!r}")
            if _is_prefix(self.workspace, hidden):
                raise ValueError(
                    f"hidden path {hidden!r} is inside the workspace and would be "
                    "unreachable by construction rather than by policy"
                )
            for mount in self.mounts:
                if mount.kind in (MountKind.RO_BIND, MountKind.RW_BIND):
                    if _is_prefix(mount.path, hidden):
                        raise ValueError(
                            f"hidden path {hidden!r} would be exposed by the bind "
                            f"at {mount.path!r}"
                        )

        for name in self.environment_names:
            if not name.isidentifier() or name.startswith("_"):
                raise ValueError(f"environment name is not passable: {name!r}")

        for guarded in self.read_only_paths:
            if not _is_absolute_clean(guarded):
                raise ValueError(
                    f"read-only path must be absolute and clean: {guarded!r}"
                )
            # ``guarded`` is annotated as a loop variable, so the name is reused
            # here for the resolved mount; ``found`` avoids shadowing that type.
            found = self.mount_for(guarded)
            if found is None:
                raise ValueError(
                    f"read-only path {guarded!r} is not reachable in the mount plan, "
                    "so guarding it would be a check on nothing"
                )
            if found.kind is not MountKind.PROC and found.kind not in (
                MountKind.RO_BIND,
                MountKind.RO_EMPTY_DIR,
            ):
                raise ValueError(
                    f"read-only path {guarded!r} resolves to a {found.kind.value!r} "
                    "mount, which the plan does not make read-only"
                )

    def mount_for(self, path: str) -> MountSpec | None:
        """The mount that determines ``path``, if any."""

        best: MountSpec | None = None
        for mount in self.mounts:
            if path == mount.path or _is_prefix(mount.path, path):
                if best is None or len(mount.path) > len(best.path):
                    best = mount
        return best

    def is_writable(self, path: str) -> bool:
        """Whether a sandboxed process could write to ``path``."""

        mount = self.mount_for(path)
        return mount is not None and mount.kind in (MountKind.RW_BIND, MountKind.TMPFS)

    def describe(self) -> dict[str, object]:
        """A printable summary, for the report and for assertions in tests."""

        return {
            "protocol_version": self.protocol_version,
            "network": self.network.value,
            "workspace": self.workspace,
            "mounts": [
                {"kind": m.kind.value, "path": m.path, "source": m.source}
                for m in self.mounts
            ],
            "hidden_paths": list(self.hidden_paths),
            "read_only_paths": list(self.read_only_paths),
            "environment_names": list(self.environment_names),
            "limits": self.limits.as_json(),
        }


def _clamp(value: int, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < low:
        raise ValueError(f"{name} must be at least {low}")
    if value > high:
        raise ValueError(f"{name} must be at most {high}")
    return value


def derive_limits(
    *,
    timeout_seconds: int,
    memory_mb: int = 1024,
    pids_max: int = 256,
    cpu_cores: float = 1.0,
    max_output_bytes: int = 1024 * 1024,
    max_artifact_bytes: int = 16 * 1024 * 1024,
) -> Limits:
    """Build validated limits, refusing anything unbounded or out of range.

    ``memory_mb`` has no "unlimited" sentinel. That is deliberate: cgroup v2
    ``memory.max`` caps and reclaims rather than killing, so an unset or
    unlimited value would not mean "no bound", it would mean "no bound that this
    system can demonstrate". The floor is enforced too, because a cap below what
    the interpreter needs to start produces a confusing ``SIGKILL`` instead of a
    useful memory-limit report.
    """

    if isinstance(cpu_cores, bool) or not isinstance(cpu_cores, (int, float)):
        raise ValueError("cpu_cores must be a number")
    cores = float(cpu_cores)
    if not 0 < cores <= CEILING_CPU_CORES:
        raise ValueError(f"cpu_cores must be in (0, {CEILING_CPU_CORES}]")
    return Limits(
        timeout_seconds=_clamp(
            timeout_seconds, 1, CEILING_TIMEOUT_SECONDS, "timeout_seconds"
        ),
        memory_mb=_clamp(memory_mb, FLOOR_MEMORY_MB, CEILING_MEMORY_MB, "memory_mb"),
        pids_max=_clamp(pids_max, FLOOR_PIDS_MAX, CEILING_PIDS_MAX, "pids_max"),
        cpu_cores=cores,
        max_output_bytes=_clamp(
            max_output_bytes, 1, CEILING_OUTPUT_BYTES, "max_output_bytes"
        ),
        max_artifact_bytes=_clamp(
            max_artifact_bytes, 1, CEILING_ARTIFACT_BYTES, "max_artifact_bytes"
        ),
    )


def default_mounts(
    workspace: str = WORKSPACE_PATH, workspace_source: str | None = None
) -> tuple[MountSpec, ...]:
    """The mount plan a worker needs, independent of the invocation.

    Assumes a merged ``/usr`` layout (Ubuntu 24.04), which the launcher confirms
    at runtime and adjusts for: the symlink entries for ``/bin``, ``/sbin``,
    ``/lib``, and ``/lib64`` are replaced by binds when the host is not merged.

    ``workspace_source`` is the guest path of the directory to expose as
    ``workspace``. It is separate from ``workspace`` because those are different
    things: the worker contract fixes the name it sees at ``/workspace``, while
    the directory that holds it lives under ``/var/lib/atlasx/workspaces`` and
    changes per invocation. Binding ``/workspace`` to itself would be what bwrap
    is asked to do if the two were collapsed, and it fails with "can't find
    source path" — the run dies before the tool starts, which is at least a
    loud failure rather than a permissive one.
    """

    return (
        MountSpec(MountKind.RO_BIND, "/usr", "/usr"),
        MountSpec(MountKind.SYMLINK, "/bin", "usr/bin"),
        MountSpec(MountKind.SYMLINK, "/sbin", "usr/sbin"),
        MountSpec(MountKind.SYMLINK, "/lib", "usr/lib"),
        MountSpec(MountKind.SYMLINK, "/lib64", "usr/lib64"),
        MountSpec(MountKind.RO_EMPTY_DIR, "/etc"),
        MountSpec(MountKind.RO_BIND, "/etc/ld.so.cache", "/etc/ld.so.cache"),
        MountSpec(MountKind.RO_BIND, "/etc/ld.so.conf", "/etc/ld.so.conf"),
        MountSpec(MountKind.RO_BIND, "/etc/ld.so.conf.d", "/etc/ld.so.conf.d"),
        MountSpec(MountKind.RO_BIND, "/opt/atlasx/lib", "/opt/atlasx/lib"),
        MountSpec(MountKind.RO_BIND, "/opt/atlasx/venv", "/opt/atlasx/venv"),
        MountSpec(MountKind.PROC, "/proc"),
        MountSpec(MountKind.DEV, "/dev"),
        MountSpec(MountKind.TMPFS, "/tmp"),
        # ``MountSpec`` takes (kind, path, source): the path is what the worker
        # sees, the source is what the guest has. The two are equal only when no
        # separate source was supplied.
        MountSpec(MountKind.RW_BIND, workspace, workspace_source or workspace),
    )


def build_policy(
    *,
    limits: Limits,
    environment_names: Sequence[str],
    workspace: str = WORKSPACE_PATH,
    workspace_source: str | None = None,
    extra_read_only: Iterable[str] = (),
    extra_hidden: Iterable[str] = (),
    read_only_paths: Sequence[str] = READ_ONLY_PATHS,
) -> SandboxPolicy:
    """Assemble a validated :class:`SandboxPolicy` from the standard plan.

    ``extra_read_only`` and ``extra_hidden`` exist so a caller can tighten the
    plan. They cannot loosen it: the constructor still refuses a writable path
    anywhere but the workspace and still refuses a hidden path that a bind would
    expose.

    ``workspace_source`` is the guest directory to expose at ``workspace``; see
    :func:`default_mounts`.
    """

    mounts = list(default_mounts(workspace, workspace_source))
    known = {mount.path for mount in mounts}
    for path in extra_read_only:
        if not _is_absolute_clean(path):
            raise ValueError(f"extra read-only path is not clean: {path!r}")
        if path in known:
            continue
        mounts.append(MountSpec(MountKind.RO_BIND, path, path))
        known.add(path)
    hidden = tuple(dict.fromkeys((*HIDDEN_PATHS, *extra_hidden)))
    return SandboxPolicy(
        mounts=tuple(mounts),
        hidden_paths=hidden,
        network=NetworkPolicy.DENY_ALL,
        limits=limits,
        environment_names=tuple(dict.fromkeys(environment_names)),
        read_only_paths=tuple(dict.fromkeys(read_only_paths)),
        workspace=workspace,
    )

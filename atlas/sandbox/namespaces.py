"""Turning a :class:`~atlas.sandbox.policy.SandboxPolicy` into a ``bwrap`` call.

This module is stdlib-only on purpose. It is installed into the guest as
``atlasx_namespaces.py`` and executed there, so it must not import anything from
``atlas`` — the guest's ``atlas`` tree is a curated payload, and a namespace
builder that could not import would be a namespace builder that cannot run at
the moment it is most needed. The Windows side imports the same file, which is
what lets a test assert the exact argument vector that the guest will use.

The argument vector is the enforcement, so it is written out explicitly rather
than assembled from flags. A reader should be able to see, in one pass, that
there is an unprivileged user namespace, a PID namespace, a network namespace,
no capabilities, a cleared environment, one writable bind, and no route to the
host drives. Anything not visible in :func:`build_argv` is not happening.

Two details are load-bearing and easy to lose:

* **The merged-``/usr`` symlinks are decided at runtime, in the guest.** Ubuntu
  24.04 has ``/bin -> usr/bin``; a distribution that does not needs a real bind
  there instead. Guessing wrong produces either a missing ``/bin`` or a bind that
  silently does nothing, so the layout is probed and :func:`build_argv` takes the
  answer as an argument.
* **``--clearenv`` plus explicit ``--setenv``.** Without the clear, the worker
  would inherit the launcher's environment, which is the one place a host secret
  could reach a tool body. With it, the environment is exactly the list the
  policy names.
"""

from __future__ import annotations

import os
from typing import Callable, Final, Iterable, Sequence

from atlas.sandbox.policy import MountKind, MountSpec, SandboxPolicy

__all__ = [
    "MERGED_USR_SYMLINKS",
    "TMPFS_BYTES",
    "TMPFS_MODE",
    "build_argv",
    "probe_merged_usr",
    "unreachable_paths",
    "verify_hidden_absent",
    "verify_read_only",
]

#: Size of the private ``/tmp``. Small on purpose: a tool that needs scratch
#: space should use the workspace, and an unbounded scratch area is a way to turn
#: a memory cap into a disk fill.
TMPFS_BYTES: Final = 16 * 1024 * 1024
TMPFS_MODE: Final = 0o1777

#: Mode for a placeholder directory that must not be writable. Read and execute
#: only: enough for the read-only binds that land inside it to resolve, not
#: enough for the sandboxed uid to add to it.
RO_DIR_MODE: Final = 0o555

#: Paths that are symlinks on a merged-``/usr`` distribution. Each is replaced by
#: a bind when the probe says the target is a real directory.
MERGED_USR_SYMLINKS: Final[tuple[tuple[str, str], ...]] = (
    ("/bin", "usr/bin"),
    ("/sbin", "usr/sbin"),
    ("/lib", "usr/lib"),
    ("/lib64", "usr/lib64"),
)

#: Namespaces every invocation gets. Written out rather than using
#: ``--unshare-all`` so that removing one is a visible edit and so the exact set
#: is assertable on a bubblewrap build that does not accept the umbrella flag.
UNSHARE_FLAGS: Final[tuple[str, ...]] = (
    "--unshare-user",
    "--unshare-pid",
    "--unshare-net",
    "--unshare-ipc",
    "--unshare-uts",
    "--unshare-cgroup",
)


def probe_merged_usr(is_symlink: Callable[[str], bool] | None = None) -> bool:
    """Whether the guest has the merged-``/usr`` layout.

    ``is_symlink`` is injectable so the decision can be tested for both layouts
    without a distribution that has the other one. In production it is
    :func:`os.path.islink`.
    """

    check = is_symlink or os.path.islink
    return all(check(path) for path, _ in MERGED_USR_SYMLINKS)


def _mount_args(
    mount: MountSpec, *, merged_usr: bool, tmpfs_bytes: int
) -> list[str]:
    kind = mount.kind

    if kind is MountKind.RO_BIND:
        return ["--ro-bind", mount.source or mount.path, mount.path]
    if kind is MountKind.RW_BIND:
        return ["--bind", mount.source or mount.path, mount.path]
    if kind is MountKind.TMPFS:
        # The two modifiers are not symmetric, and getting this wrong is a
        # runtime failure rather than a lint error, so the shape is pinned here.
        #
        # ``--size BYTES`` applies to the ``--tmpfs`` that comes *after* it and
        # bwrap exits with "must be followed by --tmpfs" if none does.
        # ``--chmod MODE PATH`` is an independent operation that takes the path
        # as its own argument, so it must *follow* the tmpfs and repeat the path;
        # putting it before would make bwrap consume the ``--tmpfs`` token as the
        # path. ``--chmod`` also wants a bare octal string, since ``oct()`` emits
        # a ``0o`` prefix it rejects.
        return [
            "--size",
            str(tmpfs_bytes),
            "--tmpfs",
            mount.path,
            "--chmod",
            format(TMPFS_MODE, "o"),
            mount.path,
        ]
    if kind is MountKind.PROC:
        # ``--proc`` on its own gives a *writable* procfs, and that is a real
        # escape rather than a hardening gap: the PID namespace does not
        # virtualise non-namespaced sysctls, so a write from inside lands on the
        # host. Measured on this host with the unguarded form — a uid-65534
        # process with ``--cap-drop ALL`` and every namespace unshared wrote
        # ``core-escaped-probe`` to ``/proc/sys/kernel/core_pattern`` and the host
        # read the new value back. ``--unshare-user`` does not change this and
        # ``--proc`` is not the control people assume it is.
        #
        # ``--remount-ro`` takes the mount path as its own argument, so the order
        # here matters: it has to follow the ``--proc`` that created the mount.
        # Read access is unaffected, which is all an interpreter needs from
        # ``/proc``.
        return ["--proc", mount.path, "--remount-ro", mount.path]
    if kind is MountKind.DEV:
        return ["--dev", mount.path]
    if kind is MountKind.EMPTY_DIR:
        return ["--dir", mount.path]
    if kind is MountKind.RO_EMPTY_DIR:
        # ``--chmod`` takes the mode and the path as separate arguments and has to
        # follow the ``--dir`` that created the path, for the same reason
        # ``--size`` has to precede ``--tmpfs``: bwrap consumes the next two
        # tokens positionally and the wrong order fails at runtime rather than
        # being caught by anything.
        return ["--dir", mount.path, "--chmod", format(RO_DIR_MODE, "o"), mount.path]
    if kind is MountKind.SYMLINK:
        if not merged_usr:
            # The target is a real directory on a split-``/usr`` system, so a
            # symlink would point at nothing. Bind it instead.
            return ["--ro-bind", "/" + (mount.source or "").lstrip("/"), mount.path]
        return ["--symlink", mount.source or "", mount.path]
    raise ValueError(f"unhandled mount kind {kind!r}")


def build_argv(
    policy: SandboxPolicy,
    *,
    command: Sequence[str],
    uid: int,
    gid: int,
    merged_usr: bool,
    argv0: Sequence[str] = ("bwrap",),
    environment: Iterable[tuple[str, str]] = (),
    tmpfs_bytes: int = TMPFS_BYTES,
) -> list[str]:
    """Build the complete ``bwrap`` argument vector for one invocation.

    ``command`` is the whole tail: the interpreter and its arguments. It is a
    sequence rather than three named parameters so that the conformance harness
    can be confined by exactly the same code path as a tool worker instead of
    having a parallel builder that could drift from it.

    ``environment`` is the full environment the process will see. It is passed
    here rather than computed inside so the caller can assert, before launching,
    that the set contains nothing the policy forbids and nothing the policy did
    not name.
    """

    if uid == 0 or gid == 0:
        raise ValueError("the sandboxed process may not run as uid or gid 0")
    if not command:
        raise ValueError("a sandbox needs a command to run")

    allowed = set(policy.environment_names)
    for name, _ in environment:
        if name not in allowed:
            raise ValueError(
                f"environment variable {name!r} is not named by the policy; the "
                "worker would see something the policy does not account for"
            )

    argv: list[str] = list(argv0)
    argv.extend(UNSHARE_FLAGS)
    argv.extend(["--uid", str(uid), "--gid", str(gid)])
    argv.append("--cap-drop")
    argv.append("ALL")
    argv.append("--new-session")
    argv.append("--die-with-parent")
    argv.append("--hostname")
    argv.append("atlasx-sandbox")
    argv.append("--clearenv")
    for name, value in environment:
        argv.extend(["--setenv", name, value])

    for mount in policy.mounts:
        argv.extend(_mount_args(mount, merged_usr=merged_usr, tmpfs_bytes=tmpfs_bytes))

    argv.extend(["--chdir", policy.workspace])
    argv.extend(["--", *command])
    return argv


def unreachable_paths(policy: SandboxPolicy, paths: Iterable[str]) -> tuple[str, ...]:
    """Which of ``paths`` the mount plan makes unreachable.

    This is the policy's own opinion, computed without launching anything. The
    launcher re-checks the same paths inside the real namespace with
    :func:`verify_hidden_absent`, so the declaration and the observed filesystem
    are compared rather than one standing in for the other.
    """

    found: list[str] = []
    for path in paths:
        mount = policy.mount_for(path)
        if mount is None:
            continue
        if mount.kind in (MountKind.RO_BIND, MountKind.RW_BIND, MountKind.TMPFS):
            found.append(path)
    return tuple(found)


def verify_hidden_absent(
    policy: SandboxPolicy, *, exists: Callable[[str], bool] | None = None
) -> tuple[str, ...]:
    """Check the namespace really does not expose the denied paths.

    Returns the paths that were found to exist. An empty tuple is the pass
    condition, and the launcher turns a non-empty one into a
    ``filesystem_escape`` violation rather than proceeding: a sandbox that was
    built wrong is worse than one that never started, because the run would
    otherwise report success for a control that is not there.
    """

    check = exists or (lambda path: os.path.exists(path))
    present = [path for path in policy.hidden_paths if check(path)]
    return tuple(present)


def verify_read_only(
    paths: Iterable[str], *, writable: Callable[[str], bool] | None = None
) -> tuple[str, ...]:
    """Which guarded paths are still writable. An empty tuple is the pass condition.

    This asks about permission rather than performing a write, and that
    distinction is the whole point: the probe for this control has to be able to
    detect the failure *without causing it*. A sysctl is a live interface into
    the host kernel, so a "check" that opened ``/proc/sys/kernel/core_pattern``
    for writing would either corrupt the host when the sandbox is broken or be
    indistinguishable from the thing it is testing. :func:`os.access` observes the
    mount mode that ``--remount-ro`` set and reports on it without touching it.
    """
    check = writable or (lambda path: os.access(path, os.W_OK))
    return tuple(path for path in paths if check(path))

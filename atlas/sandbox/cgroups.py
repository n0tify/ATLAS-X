"""cgroup v2 resource control for one sandboxed invocation.

Installed into the guest as ``atlasx_cgroups.py`` and run there as root, because
creating a cgroup requires privilege the worker will not have. The launcher
calls in, gets a directory path back, and puts the ``bwrap`` process into it;
from that point on the whole descendant tree is bounded by four files.

What each control does, and what it does not:

``pids.max``
    Hard and immediate. A ``fork`` past the cap fails with ``EAGAIN`` inside the
    namespace, so a fork bomb stops at a fixed process count. This is a genuine
    kill-equivalent control, not a rate limit.

``cpu.max``
    A bandwidth ceiling over a period, so a spinning process is throttled rather
    than stopped. A process that computes without ever blocking will still be
    slowed, not killed.

``memory.max``
    A cap that the kernel enforces by reclaiming, and by invoking the OOM killer
    when reclaim cannot free enough. This is **not** a guaranteed kill. A workload
    that stays under the cap by giving pages back never triggers the OOM killer,
    which is exactly what was measured on this host: a 128 MiB cap with thousands
    of ``max`` events and zero ``oom_kill``. The cap is real and worth setting; it
    is not a substitute for the wall-clock kill, and the timeout path in
    :mod:`atlas.sandbox.guest.launcher` is what actually guarantees termination.

``memory.swap.max = 0``
    Set alongside the memory cap so pages cannot be pushed to swap to stay under
    ``memory.max``. Without it, "capped at N" could mean "resident set is capped
    at N but total footprint is not".

``memory.oom.group = 1``
    Makes the OOM killer treat the cgroup as one indivisible unit, so when it
    does fire it takes the whole invocation rather than an arbitrary member.

The module is stdlib-only and writes files directly. That is deliberate: a
helper library would be one more thing that has to be correct in the guest
before any control works, and the entire API here is eight files in a directory.
"""

from __future__ import annotations

import errno
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Final, Mapping, Sequence

__all__ = [
    "REQUIRED_CONTROLLERS",
    "CgroupHandle",
    "CgroupUnavailable",
    "CgroupUsage",
    "cgroup_root",
    "controllers_available",
    "enable_controllers",
    "exec_in_group",
    "joiner_source",
    "write_joiner",
]

#: Where the unified hierarchy is mounted. Confirmed at runtime rather than
#: assumed, because a guest could plausibly mount it elsewhere.
DEFAULT_CGROUP_ROOT: Final = "/sys/fs/cgroup"

#: Parent of every per-invocation cgroup. Kept one level deep so
#: ``/sys/fs/cgroup`` keeps its own root semantics and no other software on the
#: guest collides with our directory.
SANDBOX_CGROUP_NAME: Final = "atlasx"


class CgroupUnavailable(RuntimeError):
    """The unified hierarchy is not usable.

    Raised rather than degrading. A run without cgroups would have no memory cap
    and no process cap, so continuing would mean reporting a sandbox that does
    not have the controls its policy claims.
    """


def cgroup_root(root: str = DEFAULT_CGROUP_ROOT) -> str:
    """Return the cgroup v2 mount point, or refuse.

    cgroup v1 is detected and rejected rather than partially supported: the
    controls this subsystem depends on are specified for v2, and a v1 host would
    need a different implementation rather than a flag.
    """

    controllers = os.path.join(root, "cgroup.controllers")
    if not os.path.isfile(controllers):
        if os.path.isdir(os.path.join(root, "memory")):
            raise CgroupUnavailable(
                "cgroup v1 is mounted; this subsystem requires cgroup v2"
            )
        raise CgroupUnavailable(f"no cgroup v2 hierarchy at {root}")
    # Reading it is the availability test: the file only exists on a unified
    # hierarchy, and its contents are what the caller needs next anyway.
    with open(controllers, "r", encoding="ascii"):
        return root


def controllers_available(root: str | None = None) -> frozenset[str]:
    """Controllers this hierarchy can delegate to child cgroups."""

    base = cgroup_root(root or DEFAULT_CGROUP_ROOT)
    with open(os.path.join(base, "cgroup.controllers"), "r", encoding="ascii") as handle:
        return frozenset(handle.read().split())


#: Controllers every invocation must be able to enforce. A cgroup that cannot
#: hold all three is refused rather than accepted with fewer: the policy
#: promises a memory cap, a process cap, and a CPU ceiling, and honouring two of
#: the three would report a sandbox that does not have the controls it claims.
REQUIRED_CONTROLLERS: Final = ("cpu", "memory", "pids")


def _read(path: str) -> str:
    with open(path, "r", encoding="ascii") as handle:
        return handle.read()


def enable_controllers(parent: str, wanted: Sequence[str]) -> frozenset[str]:
    """Ask ``parent`` to delegate controllers to *its* children.

    Two things make this easy to get wrong, and both were observed on this
    guest before this function was written:

    * **Delegation is per-directory and one level at a time.** A controller
      appears in a child's files only if that child's *own* parent lists it in
      ``cgroup.subtree_control``. Enabling the controllers at ``/sys/fs/cgroup``
      only makes them available to our ``atlasx`` directory; the per-invocation
      cgroup is a child of ``atlasx``, so ``atlasx`` has to delegate too. Doing
      it at one level is the reason a leaf can come up with a controller list
      that does not match what the hierarchy advertises.
    * **It must happen before the child is created.** The kernel snapshots the
      delegation state into the child at ``mkdir`` time, so a child made before
      the parent enabled a controller does not gain it afterwards.

    Returns what the directory reports as delegated afterwards, which is the
    only trustworthy answer: a write that "succeeded" on an already-enabled
    controller is indistinguishable from one that took effect.
    """

    target = os.path.join(parent, "cgroup.subtree_control")
    if not os.path.isfile(target):
        raise CgroupUnavailable(f"{parent} has no cgroup.subtree_control")

    current = frozenset(_read(target).split())
    missing = [name for name in wanted if name not in current]
    if missing:
        try:
            with open(target, "w", encoding="ascii") as handle:
                handle.write(" ".join(f"+{name}" for name in missing))
        except OSError as exc:
            raise CgroupUnavailable(
                f"{parent} refused to delegate {missing!r}: {exc}"
            ) from exc
    return frozenset(_read(target).split())


@dataclass(frozen=True)
class CgroupUsage:
    """Observed cgroup accounting for a finished invocation."""

    peak_bytes: int | None
    current_bytes: int | None
    events: Mapping[str, int]

    def as_json(self) -> dict[str, object]:
        return {
            "peak_bytes": self.peak_bytes,
            "current_bytes": self.current_bytes,
            "events": dict(self.events),
        }


class CgroupHandle:
    """One per-invocation cgroup, created and destroyed by the launcher."""

    __slots__ = ("_path", "_enabled")

    def __init__(self, path: str, enabled: tuple[str, ...]) -> None:
        self._path = path
        self._enabled = enabled

    @property
    def path(self) -> str:
        return self._path

    @property
    def enabled_controllers(self) -> tuple[str, ...]:
        return self._enabled

    def file(self, name: str) -> str:
        return os.path.join(self._path, name)

    def write(self, name: str, value: str) -> None:
        """Write one control file, tolerating a controller that is absent.

        A missing ``cpu.max`` is a real reduction in what is enforced, so the
        caller checks :attr:`enabled_controllers` and reports it. Swallowing the
        error without recording it is what would turn a partial control into a
        silent one.
        """

        with open(self.file(name), "w", encoding="ascii") as handle:
            handle.write(value)

    def has(self, name: str) -> bool:
        return os.path.exists(self.file(name))

    def adopt(self, pid: int) -> None:
        """Move an *already-running* ``pid`` into this cgroup.

        This bounds ``pid`` and anything it forks from now on. It does **not**
        retroactively bound children that already exist, because cgroup
        membership is inherited at ``fork`` and nothing walks a subtree
        afterwards. That distinction is not academic: moving the launcher into
        the cgroup after starting it left a worker that had already forked
        entirely outside the limit, and the run reported success. Use
        :func:`exec_in_group` to start a process inside the cgroup instead.
        """

        with open(self.file("cgroup.procs"), "w", encoding="ascii") as handle:
            handle.write(str(pid))

    def members(self) -> frozenset[int]:
        """Which pids are in this cgroup right now."""

        try:
            with open(self.file("cgroup.procs"), "r", encoding="ascii") as handle:
                return frozenset(
                    int(token) for token in handle.read().split() if token.strip()
                )
        except (OSError, ValueError):
            return frozenset()

    def kill(self) -> bool:
        """Kill every task in the cgroup.

        The backstop for anything that escaped the process group, which a
        double-forked daemon can do. Returns whether the kill was available;
        ``cgroup.kill`` needs cgroup v2 with the kernel that added it, and
        :mod:`atlas.sandbox.guest.launcher` treats its absence as a reason to
        lean harder on the process-group kill rather than as success.
        """

        if not self.has("cgroup.kill"):
            return False
        try:
            with open(self.file("cgroup.kill"), "w", encoding="ascii") as handle:
                handle.write("1")
        except OSError:
            return False
        return True

    def usage(self) -> CgroupUsage:
        """Read peak usage and the event counters.

        Read after the worker exits, so ``memory.peak`` reflects the whole run
        rather than an instantaneous sample. ``memory.events`` is what makes the
        memory behaviour reportable: a nonzero ``max`` with a zero
        ``oom_kill`` is the documented evidence that the cap throttled without
        killing.
        """

        peak: int | None = None
        current: int | None = None
        for name, target in (("memory.peak", "peak"), ("memory.current", "current")):
            if not self.has(name):
                continue
            try:
                with open(self.file(name), "r", encoding="ascii") as handle:
                    raw = handle.read().strip()
            except OSError:
                continue
            if raw == "max":
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            if target == "peak":
                peak = value
            else:
                current = value

        events: dict[str, int] = {}
        if self.has("memory.events"):
            try:
                with open(self.file("memory.events"), "r", encoding="ascii") as handle:
                    for line in handle:
                        key, _, raw = line.partition(" ")
                        try:
                            events[key.strip()] = int(raw.strip())
                        except ValueError:
                            continue
            except OSError:
                events = {}
        return CgroupUsage(peak_bytes=peak, current_bytes=current, events=events)

    def remove(self) -> None:
        """Delete the cgroup directory.

        Only succeeds once it is empty, which is a useful property: a failure
        here means something is still running, and the launcher reports that
        rather than claiming a clean teardown.
        """

        try:
            os.rmdir(self._path)
        except OSError as exc:
            if exc.errno not in (errno.ENOENT, errno.EBUSY, errno.ENOTEMPTY):
                raise

    @property
    def removed(self) -> bool:
        return not os.path.exists(self._path)


def create(
    *,
    execution_id: str,
    memory_mb: int,
    pids_max: int,
    cpu_cores: float,
    root: str | None = None,
) -> CgroupHandle:
    """Create and configure the cgroup for one invocation.

    ``cpu_cores`` is converted to a ``cpu.max`` quota and period. A fractional
    core is expressed as a quota below the period rather than by rounding, so a
    request for a quarter core really does get a quarter core's worth of
    bandwidth per period.
    """

    base = cgroup_root(root or DEFAULT_CGROUP_ROOT)

    # Every directory between the mount and the leaf has to delegate, in order,
    # and each delegation has to be in place before the next directory is made.
    # The root is delegated first so our own directory can hold controllers at
    # all; the leaf then gets them from our directory, not from the root.
    base_delegated = enable_controllers(base, REQUIRED_CONTROLLERS)
    if not set(REQUIRED_CONTROLLERS) <= base_delegated:
        raise CgroupUnavailable(
            f"{base} cannot delegate {sorted(set(REQUIRED_CONTROLLERS) - base_delegated)!r}; "
            "this hierarchy cannot enforce the declared limits"
        )

    parent = os.path.join(base, SANDBOX_CGROUP_NAME)
    try:
        os.mkdir(parent, 0o755)
    except FileExistsError:
        pass
    except OSError as exc:
        raise CgroupUnavailable(f"cannot create {parent}: {exc}") from exc

    parent_delegated = enable_controllers(parent, REQUIRED_CONTROLLERS)
    if not set(REQUIRED_CONTROLLERS) <= parent_delegated:
        raise CgroupUnavailable(
            f"{parent} cannot delegate {sorted(set(REQUIRED_CONTROLLERS) - parent_delegated)!r}; "
            "this hierarchy cannot enforce the declared limits"
        )

    # Created last, so it inherits the delegation state above.
    path = os.path.join(parent, execution_id)
    try:
        os.mkdir(path, 0o755)
    except OSError as exc:
        raise CgroupUnavailable(f"cannot create cgroup {path}: {exc}") from exc

    # What the leaf itself advertises, which is the set that can actually be
    # written. Reading the parent's view instead would report controls that the
    # leaf may not have.
    available = controllers_available(path)
    if not set(REQUIRED_CONTROLLERS) <= available:
        try:
            os.rmdir(path)
        except OSError:
            pass
        raise CgroupUnavailable(
            f"the new cgroup does not offer {sorted(set(REQUIRED_CONTROLLERS) - available)!r}; "
            "this hierarchy cannot enforce the declared limits"
        )

    handle = CgroupHandle(path, tuple(name for name in REQUIRED_CONTROLLERS if name in available))
    enabled: list[str] = []

    if "memory" in available and handle.has("memory.max"):
        handle.write("memory.max", str(memory_mb * 1024 * 1024))
        enabled.append("memory.max")
        if handle.has("memory.swap.max"):
            handle.write("memory.swap.max", "0")
            enabled.append("memory.swap.max")
        if handle.has("memory.oom.group"):
            handle.write("memory.oom.group", "1")
            enabled.append("memory.oom.group")

    if "pids" in available and handle.has("pids.max"):
        handle.write("pids.max", str(pids_max))
        enabled.append("pids.max")

    if "cpu" in available and handle.has("cpu.max"):
        period = 100_000
        quota = max(1_000, int(round(period * cpu_cores)))
        handle.write("cpu.max", f"{quota} {period}")
        enabled.append("cpu.max")

    handle._enabled = tuple(enabled)
    return handle


#: Written into the guest so a process can place *itself* in a cgroup before it
#: execs. It has to be a separate program from the launcher: the launcher is
#: already running by the time it knows the cgroup path, and joining a cgroup
#: requires writing one's own pid, which only the process being moved can do
#: safely. ``--`` separates the cgroup path from the command so a path cannot be
#: mistaken for an argument, and the join is verified rather than assumed.
#: The guest's interpreter is pinned to an absolute path rather than ``env
#: python3``, so the helper does not depend on the ``PATH`` it will be asked to
#: run with. The shebang is required: the launcher execs this file directly, and
#: without one the kernel reports "Exec format error" rather than a usable
#: diagnosis.
_JOIN_SOURCE: Final = """\
#!/opt/atlasx/venv/bin/python3
import os
import sys

target, separator, command = sys.argv[1], sys.argv[2], sys.argv[3:]
if separator != "--" or not command:
    sys.stderr.write("usage: cgroup-join CGROUP_PROCS -- COMMAND [ARG...]\\n")
    raise SystemExit(2)
with open(target, "w", encoding="ascii") as handle:
    handle.write(str(os.getpid()))
# Confirm the move took effect before exec'ing: if it did not, the command about
# to run would be unbounded, and failing here is the only point where that is
# still knowable.
with open(target, "r", encoding="ascii") as handle:
    if str(os.getpid()) not in handle.read().split():
        sys.stderr.write("the cgroup did not accept this process\\n")
        raise SystemExit(1)
os.execvp(command[0], command)
"""


def joiner_source() -> str:
    """The joiner's program text.

    Public so that provisioning can install the exact source the launcher relies
    on. It is a function rather than a bare constant so a test can assert what
    gets written without reaching into a private name, and so the "one source of
    truth" property is enforced by the import graph instead of by convention.
    """

    return _JOIN_SOURCE


def write_joiner(directory: str, name: str = "cgroup-join") -> str:
    """Install the self-joining helper and return its path."""

    path = os.path.join(directory, name)
    with open(path, "w", encoding="ascii") as handle:
        handle.write(_JOIN_SOURCE)
    os.chmod(path, 0o755)
    return path


def exec_in_group(
    *,
    handle: CgroupHandle,
    command: Sequence[str],
    joiner: str,
    **kwargs: Any,
) -> subprocess.Popen[bytes]:
    """Start ``command`` already inside ``handle``'s cgroup.

    This exists because joining after the fact does not work. cgroup membership
    is inherited at ``fork``, so a launcher that spawns a process and then writes
    its pid to ``cgroup.procs`` has bounded only that pid and whatever it forks
    later. A supervisor that forks a worker — which is exactly what ``bwrap``
    does while it builds namespaces — has a child that is already outside the
    limit by the time the write happens. Measured on this host: a 96 MiB cap with
    a worker that allocated 3200 MiB without refusing and left
    ``memory.events`` all zero, while the same workload in a plainly-placed
    process was OOM-killed at exactly 96 MiB.

    The fix is to have the process place *itself* before ``exec``. The helper
    writes its own pid, verifies the kernel accepted it, and only then execs the
    real command, so there is no window in which the command runs unbounded.
    ``kwargs`` are passed through to :class:`subprocess.Popen`.
    """

    if not command:
        raise ValueError("cannot start an empty command")
    if not os.path.isfile(joiner):
        raise CgroupUnavailable(f"the cgroup joiner is missing at {joiner}")
    return subprocess.Popen(  # noqa: S603 - argv assembled from the cgroup path
        [joiner, handle.file("cgroup.procs"), "--", *command],
        **kwargs,
    )

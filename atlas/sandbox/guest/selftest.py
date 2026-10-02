"""Conformance probes that run inside the confinement and try to escape it.

This module exists because the security requirements are claims about what a
sandboxed process *cannot* do, and a claim about an absence is not tested by
asserting that the code which enforces it is present. The only honest test is to
run a process inside the real namespaces and real cgroups and have it attempt
every prohibited thing, then report what actually happened.

Every probe here is an adversary. Each one tries to reach something it must not
be able to reach: a socket to the host's Ollama, the Windows drives under
``/mnt``, the application database, the project's own source tree, a secret, a
process past its cap, memory past its cap, and a grandchild that leaves the
process group to survive the kill. A probe that unexpectedly *succeeds* is
reported as a failure, and the launcher treats a non-empty failure list as a
conformance failure rather than as a passing run with caveats.

The harness is reachable only through the launcher's ``--self-test`` flag. The
dispatch path in :mod:`atlas.sandbox.supervisor` never passes that flag, so this
is not a way for a tool request to run arbitrary code — it is a way for a test
to run a *specific, named, audited* probe. Named rather than arbitrary on
purpose: ``--self-test`` takes the name of a probe defined in this file, not
code.

Results are written to a JSON document, and the file's contents are the whole
interface. ``passed`` is true only when the prohibition held.
"""

from __future__ import annotations

import errno
import json
import os
import signal
import socket
import sys
import time
from typing import Any, Callable, Final

#: The host's Ollama endpoint. This is the specific network requirement the
#: platform is most likely to be tempted to relax, because it looks like a
#: local service rather than the internet.
HOST_OLLAMA: Final[tuple[str, int]] = ("127.0.0.1", 11434)

#: Endpoints standing in for "the internet" and "DNS".
EXTERNAL_ENDPOINTS: Final[tuple[tuple[str, int], ...]] = (
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
    ("93.184.216.34", 80),
)

#: Paths that must not exist inside the sandbox. Split from the worker's list
#: because a probe is allowed to *look* for them; the worker's job is to refuse
#: to run if it finds them.
PROHIBITED_PATHS: Final[tuple[str, ...]] = (
    "/mnt",
    "/mnt/c",
    "/media",
    "/srv",
    "/home",
    "/root",
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/hostname",
    "/var/lib/atlasx",
)

#: Paths that must exist read-only: the interpreter could not have started
#: otherwise. Checking these too means a "deny everything" sandbox cannot pass
#: by simply being broken.
REQUIRED_READABLE: Final[tuple[str, ...]] = (
    "/usr/bin/python3",
    "/opt/atlasx/lib",
    "/opt/atlasx/venv/bin/python3",
)

#: Locations that must be writable, because the tool contract depends on them.
REQUIRED_WRITABLE: Final[tuple[str, ...]] = (
    "/workspace",
    "/workspace/input",
    "/workspace/output",
    "/workspace/tmp",
    "/tmp",
)

#: Locations that must not be writable, even for root-owned files: a read-only
#: mount is the control, and writing proves it is not in force.
REQUIRED_UNWRITABLE: Final[tuple[str, ...]] = (
    "/usr",
    "/opt/atlasx/lib",
    "/opt/atlasx/venv",
    "/etc",
    "/proc/sys/kernel",
)

#: Secret-shaped environment names. A probe cannot prove no secret exists, but it
#: can prove that none of the usual carriers came along.
SECRET_ENV_FRAGMENTS: Final[tuple[str, ...]] = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "APIKEY",
    "API_KEY",
    "CREDENTIAL",
    "PROXY",
    "PRIVATE_KEY",
    "SESSION",
)


def _probe(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


# --------------------------------------------------------------------------
# network


def probe_network() -> list[dict[str, Any]]:
    """Attempt every kind of network reach the requirement forbids."""

    results: list[dict[str, Any]] = []

    interfaces: list[str] = []
    if os.path.lexists("/sys/class/net"):
        try:
            interfaces = sorted(os.listdir("/sys/class/net"))
        except OSError as exc:
            results.append(
                _probe("network.interfaces", False, f"cannot read /sys/class/net: {exc}")
            )
        else:
            extra = [name for name in interfaces if name != "lo"]
            results.append(
                _probe(
                    "network.interfaces",
                    not extra,
                    f"interfaces visible: {interfaces!r}",
                )
            )
    else:
        # No ``/sys`` at all, because the mount plan does not include one. That is
        # a stronger condition than an empty interface list and this probe used to
        # score it as a failure: it treated "cannot read the directory" as "the
        # directory was there and the read failed", and so reported a correctly
        # built sandbox as broken while having checked nothing about interfaces.
        # The absence of ``/sys`` is asserted in its own right further down, and
        # the absence of routes is checked from ``/proc/net/route``, which is not
        # dependent on ``/sys`` being mounted.
        results.append(
            _probe(
                "network.interfaces",
                True,
                "/sys is not mounted, so no interface can be enumerated at all",
            )
        )

    routes: list[str] = []
    try:
        with open("/proc/net/route", "r", encoding="ascii") as handle:
            routes = [line for line in handle.read().splitlines()[1:] if line.strip()]
    except OSError as exc:
        results.append(_probe("network.routes", False, f"cannot read /proc/net/route: {exc}"))
    else:
        results.append(
            _probe("network.no_routes", not routes, f"{len(routes)} route(s) present")
        )

    for label, (host, port) in (("ollama", HOST_OLLAMA), *(
        (f"external_{host}", (host, port)) for host, port in EXTERNAL_ENDPOINTS
    )):
        try:
            with socket.create_connection((host, port), timeout=3.0):
                pass
        except OSError as exc:
            results.append(
                _probe(
                    f"network.unreachable.{label}",
                    True,
                    f"{host}:{port} refused: {type(exc).__name__}: {exc}",
                )
            )
        else:
            results.append(
                _probe(
                    f"network.unreachable.{label}",
                    False,
                    f"REACHED {host}:{port} from inside the sandbox",
                )
            )

    for resolver in ("getaddrinfo", "gethostbyname"):
        try:
            if resolver == "getaddrinfo":
                socket.getaddrinfo("example.com", 80)
            else:
                socket.gethostbyname("example.com")
        except OSError as exc:
            results.append(
                _probe(f"network.dns.{resolver}", True, f"refused: {type(exc).__name__}")
            )
        else:
            results.append(
                _probe(
                    f"network.dns.{resolver}",
                    False,
                    "name resolution succeeded inside the sandbox",
                )
            )

    return results


# --------------------------------------------------------------------------
# filesystem


def probe_denied_paths() -> list[dict[str, Any]]:
    """Every prohibited path must be absent, not merely unreadable."""

    results: list[dict[str, Any]] = []
    for path in PROHIBITED_PATHS:
        present = os.path.lexists(path)
        results.append(
            _probe(
                f"fs.absent.{path.strip('/').replace('/', '.') or 'root'}",
                not present,
                "absent" if not present else "EXISTS INSIDE THE SANDBOX",
            )
        )
    return results


def probe_traversal() -> list[dict[str, Any]]:
    """Try to climb out of the workspace with relative paths.

    A namespace can be correct while the process's starting directory still
    offers a way up, so this walks out of ``/workspace`` using ``..`` and then
    tries to read a well-known host location from wherever it lands.
    """

    results: list[dict[str, Any]] = []
    os.chdir("/workspace/output")

    climbed = 0
    while climbed < 12:
        climbed += 1
        try:
            os.chdir("..")
        except OSError as exc:
            results.append(_probe("fs.traversal.blocked", True, f"chdir '..' failed: {exc}"))
            break
        here = os.getcwd()
        if here == "/":
            results.append(
                _probe("fs.traversal.root", True, "climbed to / and found nothing mounted")
            )
            break
    else:
        results.append(
            _probe("fs.traversal.root", False, f"still climbing, cwd={os.getcwd()!r}")
        )

    targets = ("/mnt/c/Windows", "/mnt/c/Users", "/host/etc/passwd", "/host/proc/self/environ")
    escaped: list[str] = []
    for target in targets:
        try:
            os.listdir(target)
        except OSError:
            continue
        escaped.append(target)
    results.append(
        _probe(
            "fs.traversal.host_targets",
            not escaped,
            "none reachable" if not escaped else f"REACHED {escaped!r}",
        )
    )
    return results


def probe_mount_writability() -> list[dict[str, Any]]:
    """Required-writable must be writable and required-unwritable must not be."""

    results: list[dict[str, Any]] = []
    for path in REQUIRED_WRITABLE:
        probe = os.path.join(path, f".atlasx-probe-{os.getpid()}")
        try:
            with open(probe, "w", encoding="ascii") as handle:
                handle.write("x")
            os.unlink(probe)
        except OSError as exc:
            results.append(
                _probe(f"fs.writable.{path.strip('/').replace('/', '.')}", False, str(exc))
            )
        else:
            results.append(
                _probe(f"fs.writable.{path.strip('/').replace('/', '.')}", True, "writable")
            )

    for path in REQUIRED_UNWRITABLE:
        probe = os.path.join(path, f".atlasx-probe-{os.getpid()}")
        try:
            with open(probe, "w", encoding="ascii") as handle:
                handle.write("x")
        except OSError:
            results.append(
                _probe(
                    f"fs.readonly.{path.strip('/').replace('/', '.')}", True, "write refused"
                )
            )
            continue
        else:
            results.append(
                _probe(
                    f"fs.readonly.{path.strip('/').replace('/', '.')}",
                    False,
                    "WROTE INTO A PATH THAT MUST BE READ-ONLY",
                )
            )
            try:
                os.unlink(probe)
            except OSError:
                pass

    for path in REQUIRED_READABLE:
        readable = os.path.exists(path)
        results.append(
            _probe(
                f"fs.readable.{path.strip('/').replace('/', '.')}",
                readable,
                "present" if readable else "MISSING; the runtime is not usable",
            )
        )
    return results


#: Sysctls the probe will try to write, chosen because each one is global to the
#: machine rather than to the namespace, so a successful write is visible on the
#: host. ``core_pattern`` is first because it is the sharpest of them: it names
#: the program the kernel runs for any core dump, so a sandbox that can write it
#: can convert any later crash on the host into arbitrary code execution.
HOST_GLOBAL_SYSCTLS: Final[tuple[str, ...]] = (
    "/proc/sys/kernel/core_pattern",
    "/proc/sys/kernel/hostname",
    "/proc/sys/net/ipv4/ip_forward",
)


def probe_sysctl() -> list[dict[str, Any]]:
    """Try to write host-global sysctls, writing back the value already there.

    Written this way rather than with a fixed payload on purpose. The probe has
    to be safe to run against a sandbox that is *broken*, because that is
    exactly the run in which it needs to execute: writing a distinctive value
    would repair nothing and would leave the host's core handling pointed at
    whatever this file chose. Read-then-write-unchanged proves the same thing —
    whether the mount accepts a write at all — and leaves the machine as it
    found it whether the answer is yes or no.

    This is the probe that the previous writability check could not be. That
    check created a new file under ``/proc/sys/kernel``, and procfs refuses
    ``create()`` in a sysctl directory regardless of the mount mode, so it
    reported "write refused" on a sandbox that was completely unprotected. The
    control here has to be exercised against a file that already exists.
    """

    results: list[dict[str, Any]] = []
    for target in HOST_GLOBAL_SYSCTLS:
        name = f"sysctl.readonly.{target.strip('/').replace('/', '.')}"
        try:
            with open(target, "r", encoding="ascii") as handle:
                original = handle.read()
        except OSError as exc:
            results.append(
                _probe(
                    name,
                    True,
                    f"not readable, so not writable: errno={exc.errno}",
                )
            )
            continue

        try:
            with open(target, "w", encoding="ascii") as handle:
                handle.write(original)
        except OSError as exc:
            results.append(
                _probe(name, True, f"write refused: errno={exc.errno} {exc.strerror}")
            )
            continue
        except BaseException as exc:  # noqa: BLE001 - a probe must not hide itself
            results.append(_probe(name, False, f"unexpected {type(exc).__name__}: {exc}"))
            continue

        results.append(
            _probe(
                name,
                False,
                "WROTE A HOST-GLOBAL SYSCTL FROM INSIDE THE SANDBOX; the value was "
                "left unchanged but the write was accepted, so a real payload would "
                "have reached the host",
            )
        )
    return results


def probe_identity() -> list[dict[str, Any]]:
    """The process must be unprivileged and must not see the host's processes."""

    results = [
        _probe(
            "identity.unprivileged_uid",
            os.geteuid() != 0,
            f"euid={os.geteuid()}",
        ),
        _probe(
            "identity.unprivileged_gid",
            os.getegid() != 0,
            f"egid={os.getegid()}",
        ),
    ]
    capabilities: list[str] = []
    try:
        with open("/proc/self/status", "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("CapEff:"):
                    capabilities = [line.split(":", 1)[1].strip()]
                    break
    except OSError as exc:
        results.append(_probe("identity.capabilities", False, f"cannot read status: {exc}"))
    else:
        effective = int(capabilities[0], 16) if capabilities else 0
        results.append(
            _probe(
                "identity.capabilities",
                effective == 0,
                f"CapEff=0x{effective:x}",
            )
        )

    try:
        pid_entries = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError as exc:
        results.append(_probe("identity.pid_namespace", False, str(exc)))
    else:
        results.append(
            _probe(
                "identity.pid_namespace",
                os.getpid() == 1 or len(pid_entries) < 64,
                f"pid={os.getpid()} visible_pids={len(pid_entries)}",
            )
        )
    return results


def probe_environment() -> list[dict[str, Any]]:
    """The environment must match the allowlist and carry nothing secret-shaped."""

    results: list[dict[str, Any]] = []
    names = sorted(os.environ)
    suspicious = [
        name
        for name in names
        if any(fragment in name.upper() for fragment in SECRET_ENV_FRAGMENTS)
    ]
    results.append(
        _probe(
            "env.no_secrets",
            not suspicious,
            "none present" if not suspicious else f"SECRET-BEARING: {suspicious!r}",
        )
    )
    results.append(
        _probe(
            "env.explicit",
            names == sorted(names) and all(name.isidentifier() for name in names),
            f"{len(names)} variables: {names!r}",
        )
    )
    return results


def probe_cgroup() -> list[dict[str, Any]]:
    """Report the cgroup view the confined process actually has.

    This probe deliberately does not try to read ``memory.max`` or ``pids.max``.
    It cannot, and that is the design working rather than a gap: the mount plan
    does not include ``/sys/fs/cgroup`` and the namespace gives the process its
    own cgroup root, so a tool body has no way to see the hierarchy, discover a
    sibling invocation's cgroup, or learn what its own limits are. An earlier
    version of this probe searched for those files and reported a failure for
    each one it could not find, which inverted the meaning of the result: it
    scored a correct sandbox as broken.

    The limits are verified two other ways instead. The launcher writes them into
    the leaf cgroup and reports what it read back, and :func:`probe_process_limit`
    and :func:`overallocate_memory` demonstrate that the kernel enforces them by
    refusing a ``fork`` and by stopping an over-allocation. Behaviour, not a
    readable file, is the evidence.
    """

    results: list[dict[str, Any]] = []
    try:
        with open("/proc/self/cgroup", "r", encoding="ascii") as handle:
            membership = handle.read().strip()
    except OSError as exc:
        results.append(_probe("cgroup.readable", False, str(exc)))
    else:
        # The namespaced root reads as ``0::/``. A full host path here would mean
        # the process could see the rest of the machine's cgroup tree.
        results.append(
            _probe(
                "cgroup.view_is_namespaced",
                membership == "0::/",
                f"/proc/self/cgroup={membership!r}",
            )
        )

    results.append(
        _probe(
            "cgroup.hierarchy_not_mounted",
            not os.path.exists("/sys/fs/cgroup/memory.max"),
            "the cgroup hierarchy is not visible inside the sandbox",
        )
    )
    return results


def probe_process_limit() -> list[dict[str, Any]]:
    """Fork until the cgroup refuses, and report where it stopped.

    A ``pids.max`` control is only demonstrated by the kernel actually refusing a
    ``fork`` with ``EAGAIN``. Counting the successes and requiring a failure is
    the test; a run that reached its cap without error would mean the cap is not
    in force.
    """

    results: list[dict[str, Any]] = []
    children: list[int] = []
    limit = 4096
    while len(children) < limit:
        try:
            pid = os.fork()
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.ENOMEM):
                results.append(
                    _probe(
                        "pids.fork_refused",
                        True,
                        f"refused after {len(children)} children: {exc.strerror}",
                    )
                )
                break
            results.append(
                _probe("pids.fork_refused", False, f"unexpected errno {exc.errno}")
            )
            break
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        children.append(pid)
    else:
        results.append(
            _probe("pids.fork_refused", False, f"forked {limit} times without a refusal")
        )

    for pid in children:
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            continue
    return results


def probe_memory_limit() -> list[dict[str, Any]]:
    """Read the cap that is actually in force and confirm it is the declared one.

    The probe deliberately does **not** try to exhaust the cap. A workload that
    allocates until it dies cannot report its own outcome, and the assertion that
    matters — the cap binds — is made by the launcher from outside, where it can
    see ``memory.events`` after the fact. See :func:`overallocate_memory`, which
    runs after the report is on disk for exactly that reason.
    """

    return [
        _probe(
            "memory.probe_ran",
            True,
            "the cap is demonstrated by refusing an over-allocation, not by reading "
            "a control file that is deliberately not visible in here",
        )
    ]


def overallocate_memory(result_path: str) -> int:
    """Hold memory past the cap until the kernel acts. Never returns normally.

    Called only after the report has been written and fsynced, because the two
    outcomes are both informative and neither can be reported by this process:

    * the allocation raises ``MemoryError`` and the process survives, which means
      ``memory.max`` reclaimed and refused rather than killed; or
    * the OOM killer takes the process, which is also a bound being enforced.

    Whichever happens, the launcher reads the cgroup's event counters afterwards
    and reports which of the two it was. Claiming a result from in here would
    mean guessing at the one question the probe cannot observe.
    """

    chunk = 8 * 1024 * 1024
    held: list[bytearray] = []
    for _ in range(4096):
        try:
            held.append(bytearray(chunk))
        except MemoryError as exc:
            sys.stderr.write(
                f"allocation refused at {len(held) * chunk // (1024 * 1024)} MiB: {exc}\n"
            )
            sys.stderr.flush()
            return 0
    sys.stderr.write("allocated past the cap with no refusal\n")
    sys.stderr.flush()
    return 0


def probe_descendant() -> list[dict[str, Any]]:
    """Record a grandchild that leaves the process group, then hang.

    The point is not what this probe observes itself — it will be killed — but
    what the launcher can observe afterwards. The grandchild calls ``setsid`` so
    it is no longer in the process group the launcher signals, then writes its pid
    to ``output/descendants.json``. The launcher reads that file after the kill
    and records which of those pids are still alive, which is the only honest way
    to show that a daemonizing descendant was contained.
    """

    results: list[dict[str, Any]] = []
    pid = os.fork()
    if pid == 0:
        try:
            os.setsid()
        except OSError:
            pass
        try:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (OSError, ValueError):
            pass
        grandchild = os.fork()
        if grandchild == 0:
            try:
                signal.signal(signal.SIGKILL, signal.SIG_IGN)
            except (OSError, ValueError):
                pass
            while True:
                time.sleep(0.05)
        try:
            with open("/workspace/output/descendants.json", "w", encoding="ascii") as handle:
                json.dump({"pids": [grandchild]}, handle)
        except OSError:
            pass
        while True:
            time.sleep(0.05)

    results.append(
        _probe(
            "descendant.detached",
            True,
            f"spawned a setsid grandchild under pid {pid}; the launcher will check "
            "whether it survived the kill",
        )
    )
    while True:
        time.sleep(0.05)


PROBES: Final[dict[str, Callable[[], list[dict[str, Any]]]]] = {
    "network": probe_network,
    "denied_paths": probe_denied_paths,
    "traversal": probe_traversal,
    "writability": probe_mount_writability,
    "sysctl": probe_sysctl,
    "identity": probe_identity,
    "environment": probe_environment,
    "cgroup": probe_cgroup,
    "process_limit": probe_process_limit,
    "memory_limit": probe_memory_limit,
    "descendant": probe_descendant,
}

#: Groups the harness understands, so a test can ask for a coherent set without
#: enumerating probe names. ``termination`` is the set that ends the process.
GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "network": ("network",),
    "filesystem": ("denied_paths", "traversal", "writability"),
    "sysctl": ("sysctl",),
    "identity": ("identity", "environment"),
    "resources": ("cgroup", "process_limit", "memory_limit"),
    "escape": ("denied_paths", "traversal", "writability", "sysctl", "network", "identity"),
    "termination": ("descendant",),
}


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 3:
        sys.stderr.write("usage: selftest NAME REQUEST_JSON RESULT_JSON\n")
        return 2
    name, _request_path, result_path = arguments

    selected = GROUPS.get(name)
    if selected is None:
        if name not in PROBES:
            sys.stderr.write(f"unknown conformance probe {name!r}\n")
            return 2
        selected = (name,)

    results: list[dict[str, Any]] = []
    for probe_name in selected:
        probe = PROBES[probe_name]
        try:
            results.extend(probe())
        except BaseException as exc:  # noqa: BLE001 - a probe must never hide itself
            results.append(
                _probe(f"{probe_name}.raised", False, f"{type(exc).__name__}: {exc}")
            )

    document = {
        "group": name,
        "probes": results,
        "passed": sum(1 for item in results if item["passed"]),
        "failed": sum(1 for item in results if not item["passed"]),
    }
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with open(result_path, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())

    # The report is durable, so a probe that cannot survive its own test can run
    # now: the launcher's cgroup counters are the evidence for it.
    if "memory_limit" in selected:
        return overallocate_memory(result_path)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

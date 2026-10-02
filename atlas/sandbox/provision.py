"""Installing the sandbox runtime into the WSL guest.

This is the one-time setup that makes every later invocation possible: a Linux
interpreter, a directory holding the guest-side payload, a launcher entry point,
and a ``wsl.conf`` that turns off Windows interop for this distribution. It is
idempotent and it is run deliberately by an operator, not implicitly on first
dispatch, because a security control that installs itself at the moment it is
first needed is a control whose installation cannot be reviewed.

What gets installed into the guest is a *curated* copy of the ``atlas`` package,
not the whole tree. The distinction is the point:

* Copied verbatim, because they are stdlib-only and are the code that must be
  identical on both sides: the protocol, the policy, the namespace builder, the
  cgroup controls, the environment allowlist, the launcher, the worker, the
  snapshot view, the conformance harness, and the tool definition, schema, and
  error modules the tool bodies import.
* Generated as empty stubs, because the real versions pull in the Windows host:
  ``atlas/tools/__init__.py`` re-exports the dispatcher and the registry, and
  ``atlas/security/__init__.py`` re-exports the identity resolver and the
  authorization service. Importing either in the guest would drag pydantic, the
  database layer, and the whole host dependency set into a process that is
  supposed to have none of it.
* Not installed at all: ``atlas/tools/context.py``. Its real ``OwnedTaskView``
  opens SQLite. The guest's equivalent is
  :class:`atlas.sandbox.guest.view.SnapshotView`, which implements the same
  interface over a read-only snapshot. Shipping the original would put a database
  accessor inside the sandbox, which is the single thing the design forbids.

The payload is made read-only to everyone but root, so the unprivileged worker
cannot rewrite the module it is executing. A worker able to edit the enforcement
code is not confined by it.

The payload travels as a tar on stdin rather than as a shell command line, so no
filename from this process is ever handed to a shell in the guest. The one place
a shell is used is the interpreter-existence probe, and that is a literal string
with no interpolated input.

Run it with ``python -m atlas.sandbox.provision [distribution]``.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import tarfile
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Sequence

from atlas.sandbox import cgroups

__all__ = [
    "COPIED_MODULES",
    "GENERATED_STUBS",
    "ProvisionReport",
    "main",
    "payload_digest",
    "provision",
]

DEFAULT_DISTRIBUTION: Final = "Ubuntu-24.04"

#: Repository files copied into the guest verbatim, as repo path -> guest path
#: relative to the payload root. Every one of these imports only the standard
#: library and other entries in this table; ``tests/test_sandbox.py`` asserts
#: that by importing them with the host package tree absent.
COPIED_MODULES: Final[tuple[tuple[str, str], ...]] = (
    ("atlas/__init__.py", "atlas/__init__.py"),
    ("atlas/security/policy.py", "atlas/security/policy.py"),
    ("atlas/tools/errors.py", "atlas/tools/errors.py"),
    ("atlas/tools/schema.py", "atlas/tools/schema.py"),
    ("atlas/tools/definition.py", "atlas/tools/definition.py"),
    ("atlas/tools/builtin/__init__.py", "atlas/tools/builtin/__init__.py"),
    (
        "atlas/tools/builtin/artifact_metadata.py",
        "atlas/tools/builtin/artifact_metadata.py",
    ),
    (
        "atlas/tools/builtin/json_shape_inspect.py",
        "atlas/tools/builtin/json_shape_inspect.py",
    ),
    (
        "atlas/tools/builtin/numeric_summary.py",
        "atlas/tools/builtin/numeric_summary.py",
    ),
    (
        "atlas/tools/builtin/task_graph_summary.py",
        "atlas/tools/builtin/task_graph_summary.py",
    ),
    (
        "atlas/tools/builtin/text_statistics.py",
        "atlas/tools/builtin/text_statistics.py",
    ),
    ("atlas/sandbox/protocol.py", "atlas/sandbox/protocol.py"),
    ("atlas/sandbox/policy.py", "atlas/sandbox/policy.py"),
    ("atlas/sandbox/namespaces.py", "atlas/sandbox/namespaces.py"),
    ("atlas/sandbox/cgroups.py", "atlas/sandbox/cgroups.py"),
    ("atlas/sandbox/environment.py", "atlas/sandbox/environment.py"),
    ("atlas/sandbox/guest/view.py", "atlas/sandbox/guest/view.py"),
    ("atlas/sandbox/guest/worker.py", "atlas/sandbox/guest/worker.py"),
    ("atlas/sandbox/guest/selftest.py", "atlas/sandbox/guest/selftest.py"),
    ("atlas/sandbox/guest/launcher.py", "atlas/sandbox/guest/launcher.py"),
)

#: Package initializers generated as empty files. Each real one re-exports host
#: components the guest must not have; see the module docstring.
GENERATED_STUBS: Final[tuple[str, ...]] = (
    "atlas/security/__init__.py",
    "atlas/sandbox/__init__.py",
    "atlas/sandbox/guest/__init__.py",
    "atlas/tools/__init__.py",
)

STUB_BODY: Final = '"""ATLAS-X guest stub. See atlas.sandbox.provision."""\n'

#: The manifest written next to the payload so the guest's installed bytes can
#: be compared with the source they came from.
MANIFEST_NAME: Final = "atlasx-payload-manifest.json"

#: Written to ``/etc/wsl.conf`` in the ATLAS-X distribution. Interop is the
#: bridge that lets a Linux process start a Windows executable; with it off, a
#: guest process cannot reach a Windows binary even if something else exposed the
#: drives. The namespace hiding in ``bwrap`` is the primary control and this is
#: the second one, applied at the distribution level.
WSL_CONF: Final = """\
# Managed by ATLAS-X (atlas.sandbox.provision). Edits will be overwritten.
[interop]
enabled=false
appendWindowsPath=false

[automount]
enabled=true
options=ro,noatime
"""

#: The guest-side entry point. A Python script with an absolute shebang rather
#: than a shell wrapper, so the supervisor can ``--exec`` it directly: nothing is
#: concatenated into a command line and there is no shell between the
#: supervisor's argv and the launcher's ``main``. It also fixes ``sys.path``
#: itself rather than relying on the caller having set ``PYTHONPATH``, which
#: removes one way for the guest to import from the wrong directory.
LAUNCHER_SHIM: Final = '''\
#!/opt/atlasx/venv/bin/python3
"""ATLAS-X guest launcher entry point. Installed by atlas.sandbox.provision."""

import sys

sys.path.insert(0, "/opt/atlasx/lib")

from atlas.sandbox.guest.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
'''

#: Environment for ``wsl.exe`` on the provisioning path. Explicit rather than
#: inherited so the host's application secret is not present in the child.
WSL_ENVIRONMENT: Final[dict[str, str]] = {
    "PATH": r"C:\Windows\System32;C:\Windows",
    "SystemRoot": r"C:\Windows",
}

PAYLOAD_ROOT: Final = "/opt/atlasx/lib"
BIN_ROOT: Final = "/opt/atlasx/bin"
VENV_ROOT: Final = "/opt/atlasx/venv"
LAUNCHER_PATH: Final = f"{BIN_ROOT}/atlasx-launcher"
#: Installed by :func:`atlas.sandbox.cgroups.write_joiner`. The launcher execs
#: the confined command through this rather than adopting it afterwards, so the
#: process is in its cgroup before it exists as a bounded workload.
JOINER_PATH: Final = f"{BIN_ROOT}/cgroup-join"
WORKSPACE_ROOT: Final = "/var/lib/atlasx/workspaces"


@dataclass(frozen=True)
class ProvisionReport:
    """What provisioning did, so an operator can see rather than assume."""

    distribution: str
    payload_files: int
    payload_digest: str
    interop_disabled: bool
    venv_created: bool
    steps: tuple[str, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "distribution": self.distribution,
            "payload_files": self.payload_files,
            "payload_digest": self.payload_digest,
            "interop_disabled": self.interop_disabled,
            "venv_created": self.venv_created,
            "steps": list(self.steps),
        }


def repository_root() -> Path:
    """The checkout root, located from this file rather than the process cwd.

    Provisioning is run from anywhere: ``python -m atlas.sandbox.provision`` in
    another directory has to install the same bytes, not whatever happens to be
    in front of it.
    """

    return Path(__file__).resolve().parents[2]


def _collect_members(root: Path) -> list[tuple[str, bytes]]:
    """Read every payload file, refusing to proceed on a missing one."""

    members: list[tuple[str, bytes]] = []
    for relative, guest_relative in COPIED_MODULES:
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(
                f"{relative} is listed for installation but does not exist at {source}"
            )
        if guest_relative != relative:
            raise ValueError(
                f"{relative} installs to {guest_relative}; this provisioner only "
                "supports identity mappings, so a mismatch is a bug in the table"
            )
        members.append((relative, source.read_bytes()))
    for relative in GENERATED_STUBS:
        members.append((relative, STUB_BODY.encode("utf-8")))
    return sorted(members)


def payload_digest(members: Sequence[tuple[str, bytes]]) -> str:
    """A stable digest of the payload contents.

    Two provisions of identical source produce identical digests, which is what
    makes "the guest is running this code" a checkable statement rather than an
    assumption. Member order is normalized first, so the digest depends on content
    and not on directory iteration order.
    """

    digest = sha256()
    for name, data in sorted(members):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(data).digest())
    return digest.hexdigest()


def build_payload(members: Sequence[tuple[str, bytes]]) -> bytes:
    """Package the payload as a deterministic gzipped tar.

    Fixed mtimes, fixed ownership, and a read-only mode on every member, so the
    bytes on the wire are a function of the source alone.
    """

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", compresslevel=9) as archive:
        for name, data in sorted(members):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o444
            info.uid = 0
            info.gid = 0
            info.uname = "root"
            info.gname = "root"
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _wsl(
    arguments: Sequence[str], stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(  # noqa: S603 - argv is built from literals here
        ["wsl.exe", *arguments],
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=600,
        env=dict(WSL_ENVIRONMENT),
        close_fds=True,
        check=False,
    )


def provision(
    distribution: str = DEFAULT_DISTRIBUTION, *, terminate: bool = True
) -> ProvisionReport:
    """Install the sandbox runtime into ``distribution``.

    Safe to re-run: every step either creates something absent or overwrites a
    file this module owns, so an upgrade is the same command as an install.
    """

    root = repository_root()
    members = _collect_members(root)
    digest = payload_digest(members)
    tarball = build_payload(members)
    steps: list[str] = []

    def run(
        *arguments: str, stdin: bytes | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[bytes]:
        completed = _wsl(
            [
                "--distribution",
                distribution,
                "--user",
                "root",
                "--exec",
                *arguments,
            ],
            stdin=stdin,
        )
        if check and completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"{' '.join(arguments[:4])} failed in {distribution} "
                f"(exit {completed.returncode}): {detail[:600]}"
            )
        return completed

    run("/usr/bin/mkdir", "-p", PAYLOAD_ROOT, BIN_ROOT, VENV_ROOT, WORKSPACE_ROOT)
    steps.append(f"created {PAYLOAD_ROOT}, {BIN_ROOT}, {VENV_ROOT}, {WORKSPACE_ROOT}")

    run("/usr/bin/tar", "-xzf", "-", "-C", PAYLOAD_ROOT, stdin=tarball)
    steps.append(f"unpacked {len(members)} payload files into {PAYLOAD_ROOT}")

    manifest = json.dumps(
        {
            "digest": digest,
            "files": [name for name, _ in members],
            "generator": "atlas.sandbox.provision",
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")
    run("/usr/bin/tee", f"{PAYLOAD_ROOT}/{MANIFEST_NAME}", stdin=manifest)
    steps.append(f"wrote the payload manifest with digest {digest[:16]}")

    run("/usr/bin/tee", LAUNCHER_PATH, stdin=LAUNCHER_SHIM.encode("utf-8"))
    run("/usr/bin/chmod", "0755", LAUNCHER_PATH)
    steps.append(f"installed {LAUNCHER_PATH}")

    # Written from the same module the launcher calls at run time, so the helper
    # in the guest and the one this code was tested with cannot drift apart.
    joiner_source = cgroups.joiner_source()
    run("/usr/bin/tee", JOINER_PATH, stdin=joiner_source.encode("ascii"))
    run("/usr/bin/chmod", "0755", JOINER_PATH)
    steps.append(f"installed {JOINER_PATH}")

    run("/usr/bin/chmod", "-R", "a-w", PAYLOAD_ROOT)
    run("/usr/bin/chown", "-R", "root:root", PAYLOAD_ROOT, BIN_ROOT)
    steps.append("made the payload read-only and root-owned")

    probe = run(
        "/bin/sh", "-c", f"test -x {VENV_ROOT}/bin/python3", check=False
    )
    venv_created = probe.returncode != 0
    if venv_created:
        run(
            "/usr/bin/python3",
            "-m",
            "venv",
            "--without-pip",
            "--copies",
            VENV_ROOT,
        )
        run("/usr/bin/chown", "-R", "root:root", VENV_ROOT)
        steps.append(f"created the virtual environment at {VENV_ROOT}")
    else:
        steps.append(f"reused the existing virtual environment at {VENV_ROOT}")

    run("/usr/bin/tee", "/etc/wsl.conf", stdin=WSL_CONF.encode("utf-8"))
    steps.append("wrote /etc/wsl.conf with interop and appendWindowsPath disabled")

    run("/usr/bin/chmod", "0711", WORKSPACE_ROOT)
    steps.append(f"set {WORKSPACE_ROOT} to mode 0711")

    if terminate:
        subprocess.run(  # noqa: S603
            ["wsl.exe", "--terminate", distribution],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=180,
            env=dict(WSL_ENVIRONMENT),
            close_fds=True,
            check=False,
        )
        steps.append("restarted the distribution so wsl.conf takes effect")

    return ProvisionReport(
        distribution=distribution,
        payload_files=len(members),
        payload_digest=digest,
        interop_disabled=True,
        venv_created=venv_created,
        steps=tuple(steps),
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    distribution = arguments[0] if arguments else DEFAULT_DISTRIBUTION
    try:
        report = provision(distribution)
    except (RuntimeError, OSError, FileNotFoundError) as exc:
        sys.stderr.write(f"provisioning failed: {exc}\n")
        return 1
    sys.stdout.write(f"provisioned {report.distribution}\n")
    for step in report.steps:
        sys.stdout.write(f"  - {step}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

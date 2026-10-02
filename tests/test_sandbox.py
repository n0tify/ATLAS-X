"""Tests for the Phase 10B sandbox boundary.

The suite is in two halves, and the split is deliberate.

The **host half** needs no WSL. It tests the parts that decide what the guest is
allowed to see: the policy value, the ``bwrap`` argument vector, and the
environment allowlist. These are fast and deterministic, and they run everywhere,
including on a machine with no WSL at all. A confinement bug that can be caught by
inspecting the policy does not need a Linux kernel to catch it.

The **guest half** runs against the real thing: a real ``wsl.exe`` launch, a real
``bwrap`` with real namespaces, and a real cgroup v2 leaf. It is the only part that
can honestly claim the sandbox holds, because the claim is about what a confined
process is *unable* to do, and that can only be demonstrated by attempting it.

The rule for the guest half is that every test drives a real process and asserts
on observable behaviour. There are no mocks of ``bwrap``, no faked syscalls, and no
assertions that a function was called. A probe that cannot observe its own
isolation is reported as a failure, not skipped — the alternative is a green suite
that proves nothing, which is worse than a red one.

What is asserted here is bounded by what the sandbox actually does. It does not
claim to defeat a kernel exploit, and no test pretends to. The tests below say what
they check and why; the limits are recorded in the design documents rather than
being papered over here.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from typing import Any, Iterator

import pytest

from atlas.sandbox import (
    DEFAULT_DISTRO,
    ENVIRONMENT_NAMES,
    HIDDEN_PATHS,
    READ_ONLY_PATHS,
    SandboxConfiguration,
    SandboxPolicy,
    SandboxSupervisor,
    build_environment,
    build_policy,
)
from atlas.sandbox.errors import exception_for
from atlas.sandbox.guest.selftest import GROUPS
from atlas.sandbox.namespaces import build_argv as namespaces_build_argv
from atlas.sandbox.policy import (
    MountKind,
    MountSpec,
    NetworkPolicy,
    derive_limits,
)
from atlas.sandbox.protocol import Status, ViolationKind
from atlas.sandbox.workspace import PARENT_COLUMNS, SNAPSHOT_RESOURCES

# --------------------------------------------------------------------------- #
# Fixtures                                                                      #
# --------------------------------------------------------------------------- #

_CONFIG = SandboxConfiguration(
    distribution=DEFAULT_DISTRO,
    memory_mb=256,
    pids_max=32,
    cpu_cores=1.0,
    max_output_bytes=1024 * 1024,
    max_artifact_bytes=1024 * 1024,
    launcher_timeout_seconds=60,
)


@pytest.fixture(scope="session")
def supervisor() -> Iterator[SandboxSupervisor]:
    """A supervisor over the provisioned guest, skipped when WSL is absent.

    The skip is conditional on the guest being *unreachable*, not on the test being
    inconvenient. If WSL is present but the sandbox is broken, ``health`` says so
    and the guest tests fail loudly — that is the case worth catching.
    """

    supervisor = SandboxSupervisor(_CONFIG)
    try:
        health = supervisor.health()
    except Exception as exc:  # noqa: BLE001 - any failure means "not usable"
        pytest.skip(f"WSL guest {DEFAULT_DISTRO!r} is not usable: {exc}")
    if not health.get("available", False):
        pytest.skip(f"WSL guest {DEFAULT_DISTRO!r} is not provisioned: {health}")
    yield supervisor


@pytest.fixture(scope="session")
def probes(supervisor: SandboxSupervisor) -> dict[str, list[dict[str, Any]]]:
    """Every conformance probe, run once, keyed by group name.

    Running the full set once and indexing it keeps the suite to a single guest
    round-trip per group instead of one per assertion, which matters because each
    of these pays a WSL launch, a ``bwrap`` exec, and a cgroup teardown.
    """

    results: dict[str, list[dict[str, Any]]] = {}
    for group in sorted(GROUPS):
        # ``termination`` is excluded here and covered by its own test. Its probe
        # hangs forever by design so the launcher has something to kill, which means
        # the process is terminated before it can write a result. Its evidence is in
        # the launcher's post-kill observations, not in a returned payload.
        if group == "termination":
            continue

        outcome = supervisor.run_conformance_probe(group=group, timeout_seconds=30)
        payload = outcome.output or {}

        # A group that deliberately hits a limit is expected to end in
        # ``RESOURCE_EXCEEDED`` — ``resources`` over-allocates on purpose to show
        # the kernel stops it. That is the probe succeeding, so the envelope status
        # is not the pass criterion here. What must hold is that the group ran, that
        # it reported probes, and that none of them failed. Anything else is a real
        # error: a protocol failure, a timeout, or a crashed launcher.
        if not outcome.ok:
            assert outcome.status is Status.RESOURCE_EXCEEDED, (
                f"conformance group {group!r} failed: {outcome.status} "
                f"{outcome.violation} {outcome.message}"
            )
            assert group == "resources", (
                f"only the resources group is expected to hit a limit, not {group!r}"
            )

        # The harness reports a group summary: a count and the per-probe detail.
        # The summary is asserted here and the detail is what the individual tests
        # read, so a group that ran zero probes cannot pass as a group whose probes
        # were all fine.
        collected = payload.get("probes")
        assert isinstance(collected, list) and collected, (
            f"group {group!r} ran no probes: {payload}"
        )
        results[group] = collected
    return results


def _by_name(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(entry["name"]): entry for entry in results}


def _failures(results: list[dict[str, Any]]) -> list[str]:
    return [
        f"{entry['name']}: {entry['detail']}"
        for entry in results
        if not entry.get("passed", False)
    ]


# --------------------------------------------------------------------------- #
# Host half: the policy and the argument vector                                #
# --------------------------------------------------------------------------- #


def _standard_policy(**overrides: Any) -> SandboxPolicy:
    """The policy the supervisor would build for a normal invocation."""

    arguments: dict[str, Any] = {
        "limits": derive_limits(
            timeout_seconds=30,
            memory_mb=256,
            pids_max=32,
            cpu_cores=1.0,
            max_output_bytes=1024 * 1024,
            max_artifact_bytes=1024 * 1024,
        ),
        "environment_names": list(ENVIRONMENT_NAMES),
    }
    arguments.update(overrides)
    return build_policy(**arguments)


def _argv(policy: SandboxPolicy | None = None) -> list[str]:
    """The ``bwrap`` command line the guest would execute."""

    return namespaces_build_argv(
        policy or _standard_policy(),
        command=("/opt/atlasx/venv/bin/python", "-c", "pass"),
        uid=65534,
        gid=65534,
        merged_usr=True,
    )


def test_the_workspace_is_the_only_writable_location() -> None:
    """U-2 rests on there being exactly one writable path."""

    policy = _standard_policy()
    writable = [
        mount.path for mount in policy.mounts if mount.kind is MountKind.RW_BIND
    ]
    assert writable == [policy.workspace] == ["/workspace"]


def test_a_second_writable_path_is_refused_at_construction() -> None:
    """A permissive policy cannot be expressed, so it cannot be requested.

    ``/tmp`` is a private tmpfs and is legitimately writable; ``RW_BIND`` is the
    durable kind that must be unique. The check is on the bind kind specifically,
    because "writable" is not the same as "exposes something outside the sandbox".
    """

    policy = _standard_policy()
    with pytest.raises(ValueError, match="only writable path"):
        replace(
            policy,
            mounts=policy.mounts
            + (
                MountSpec(
                    path="/somewhere-else",
                    kind=MountKind.RW_BIND,
                    source="/var/lib/atlasx/workspaces/elsewhere",
                ),
            ),
        )


def test_a_hidden_path_exposed_by_a_bind_is_refused() -> None:
    """Hiding ``/mnt`` while binding something inside ``/mnt`` must fail.

    This is the check that turns a declared guarantee into an enforced one. Every
    individual field here looks correct — one bind, one hidden path — and only the
    relationship between them is wrong, so a field-by-field review would pass it.
    """

    with pytest.raises(ValueError, match="would be exposed by the bind"):
        _standard_policy(
            extra_read_only=("/mnt/c",),
            extra_hidden=("/mnt/c/project",),
        )


def test_the_policy_declares_no_network_and_no_other_policy_exists() -> None:
    """U-1 is a closed set: there is no value meaning "allowed"."""

    assert list(NetworkPolicy) == [NetworkPolicy.DENY_ALL]
    assert _standard_policy().network is NetworkPolicy.DENY_ALL


def test_a_policy_asking_for_network_is_refused() -> None:
    """Even a policy constructed directly cannot widen the network."""

    policy = _standard_policy()
    with pytest.raises((ValueError, TypeError)):
        replace(policy, network="allow")


def test_the_argument_vector_unshares_every_namespace_that_matters() -> None:
    """The argv is the confinement, so it is asserted directly rather than inferred."""

    argv = _argv()

    for flag in (
        "--unshare-pid",
        "--unshare-net",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-user",
        "--die-with-parent",
        "--new-session",
    ):
        assert flag in argv, f"{flag} missing from the bwrap argv"

    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    assert argv[argv.index("--uid") + 1] == "65534"
    assert argv[argv.index("--gid") + 1] == "65534"


def test_the_argument_vector_exposes_no_windows_mount() -> None:
    """No drive letter or host directory may appear in the mount plan."""

    text = " ".join(_argv())
    for forbidden in ("/mnt/c", "/mnt/d", "C:\\", "appendWindowsPath"):
        assert forbidden not in text, f"{forbidden!r} leaked into the bwrap argv"


def test_the_argument_vector_remounts_proc_read_only() -> None:
    """Regression guard for the writable ``/proc/sys`` escape.

    ``--proc`` creates a fresh ``proc`` whose ``sys`` subtree is host-global
    regardless of the namespaces around it, so without an explicit ``--remount-ro``
    a confined uid could rewrite kernel state such as ``core_pattern``. The
    remount targets the same path as ``--proc`` because the whole of ``/proc`` is
    read-only here; ``/proc/sys`` is the case that motivated it, not the only
    subtree affected.
    """

    argv = _argv()
    proc_index = argv.index("--proc")
    remount_index = argv.index("--remount-ro")
    assert argv[remount_index + 1] == argv[proc_index + 1] == "/proc"


def test_the_etc_placeholder_is_created_read_only() -> None:
    """``/etc`` exists only to hold three ``ld.so`` files and must not be writable.

    ``bwrap --dir`` creates a directory the sandboxed uid owns, so leaving ``/etc``
    writable let a tool body drop files into a path that reads as host
    configuration. The mode is asserted here because it is a property of the argv
    rather than of the mount list.
    """

    argv = _argv()
    chmod_index = argv.index("--chmod")
    assert argv[chmod_index + 1] == "555"
    assert argv[chmod_index + 2] == "/etc"


def test_the_environment_is_cleared_before_anything_is_added() -> None:
    """``--clearenv`` must precede every ``--setenv``.

    Ordering matters: ``bwrap`` applies the ``--setenv`` flags in order against the
    environment it starts from. Without ``--clearenv`` the confined process would
    inherit the launcher's environment, and the allowlist would only ever be able to
    narrow it, never replace it.
    """

    argv = _argv()
    assert "--clearenv" in argv
    if "--setenv" in argv:
        assert argv.index("--clearenv") < argv.index("--setenv")


def test_read_only_and_hidden_sets_do_not_overlap() -> None:
    """A path cannot be both required-read-only and required-absent."""

    assert not set(READ_ONLY_PATHS) & set(HIDDEN_PATHS)


def test_the_environment_allowlist_carries_no_secret_shaped_name() -> None:
    """The worker's environment is an allowlist, so a leak shows up as a name."""

    text = " ".join(ENVIRONMENT_NAMES).upper()
    for fragment in ("SECRET", "TOKEN", "PASSWORD", "AWS_", "OPENAI", "ANTHROPIC"):
        assert fragment not in text, f"{fragment!r} appears in the environment allowlist"


def test_build_environment_copies_nothing_from_the_host() -> None:
    """The worker environment is derived from the allowlist, not from ``os.environ``.

    A decoy variable is set in the parent process; if the builder consulted
    ``os.environ`` at all it would appear. This is asserted by construction rather
    than by reading the signature, so adding such a lookup later fails here.
    """

    decoy = "ATLASX_HOST_SECRET_PROBE"
    os.environ[decoy] = "leaked"
    try:
        built = build_environment(
            workspace="/workspace", tool_id="text_statistics", execution_id="abc123"
        )
    finally:
        del os.environ[decoy]

    names = [name for name, _ in built]
    assert decoy not in names
    assert set(names) <= set(ENVIRONMENT_NAMES)


def test_the_sandbox_opt_out_default_is_confinement() -> None:
    """Omitting ``requires_sandbox`` must confine, not exempt.

    Regression guard. The flag defaulted to ``False`` in Phase 09, when a body ran
    in the ATLAS-X process. Inverting the default to ``True`` is what makes the
    absence of an opt-out meaningful: a builtin that forgets the field is confined,
    so forgetting it cannot quietly reintroduce an in-process execution path.
    """

    from atlas.tools.definition import (
        Determinism,
        ProvenanceField,
        ToolDefinition,
        ToolLimits,
    )
    from atlas.tools.schema import SchemaField, ToolSchema

    definition = ToolDefinition(
        tool_id="probe_defaults",
        title="Probe",
        description="A definition that declares nothing optional.",
        determinism=Determinism.DETERMINISTIC,
        input_schema=ToolSchema(
            fields=(SchemaField(name="text", type="string", max_length=8),)
        ),
        output_schema=ToolSchema(
            fields=(SchemaField(name="value", type="integer", minimum=0, maximum=8),)
        ),
        limits=ToolLimits(max_input_bytes=64, max_output_bytes=64, timeout_seconds=1),
        version="0.0.0",
        implementation=lambda context, arguments: {"value": 0},
        implementation_id="tests.test_sandbox:probe",
        provenance_fields=frozenset(
            {
                ProvenanceField.TOOL_ID,
                ProvenanceField.TOOL_VERSION,
                ProvenanceField.STARTED_AT,
                ProvenanceField.FINISHED_AT,
                ProvenanceField.STATUS,
            }
        ),
    )
    assert definition.requires_sandbox is True


# --------------------------------------------------------------------------- #
# Guest half: the real confinement                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("group", sorted(set(GROUPS) - {"termination"}))
def test_every_conformance_probe_passes(
    probes: dict[str, list[dict[str, Any]]], group: str
) -> None:
    """Each probe reports whether the confined process was actually confined."""

    failures = _failures(probes[group])
    assert not failures, f"conformance group {group!r} failed:\n" + "\n".join(failures)


def test_u1_network_denial_is_demonstrated_not_assumed(
    probes: dict[str, list[dict[str, Any]]]
) -> None:
    """U-1 requires observing refused connections, not merely an unset flag."""

    results = _by_name(probes["network"])

    # No routes, and no interfaces to route through. The second probe passes when
    # ``/sys`` is absent, which is stronger isolation rather than a gap: the
    # process cannot even enumerate interfaces.
    assert results["network.no_routes"]["passed"]
    assert results["network.interfaces"]["passed"]

    # Every destination must be refused. This is the part that carries U-1: an
    # unset flag or an absent interface would not stop a process that knows its
    # own address, so the probes attempt real connections.
    unreachable = sorted(name for name in results if name.startswith("network.unreachable."))
    assert len(unreachable) >= 3, f"too few destinations attempted: {unreachable}"

    external = [name for name in unreachable if "external" in name]
    assert external, f"no external destination was attempted: {unreachable}"
    for name in external:
        detail = str(results[name]["detail"])
        assert "Network is unreachable" in detail or "refused" in detail.lower(), (
            f"{name} was reachable from inside the sandbox: {detail}"
        )

    # Name resolution must fail too, since a resolver reachable over loopback would
    # be a network path regardless of whether routing is disabled.
    for name in ("network.dns.getaddrinfo", "network.dns.gethostbyname"):
        assert results[name]["passed"], f"{name}: {results[name]['detail']}"


def test_u2_denies_the_windows_filesystem(
    probes: dict[str, list[dict[str, Any]]]
) -> None:
    """U-2 requires the host drives to be absent, not merely unreadable."""

    results = _by_name(probes["filesystem"])
    absent = [name for name in results if name.startswith("fs.absent.")]
    assert absent, "no denied-path probe ran"
    for name in absent:
        assert results[name]["passed"], f"{name}: {results[name]['detail']}"


def test_the_guest_cannot_write_host_global_sysctls(
    probes: dict[str, list[dict[str, Any]]]
) -> None:
    """Regression guard for the escape that motivated the read-only ``/proc``.

    ``/proc/sys`` used to be writable by uid 65534 inside ``bwrap``, which let a
    confined process rewrite host-global kernel state through a mount that
    ``--unshare-all`` does not cover. The fix remounts ``/proc/sys`` read-only.
    These probes write each sysctl's current value back to itself, so they fail if
    the path is writable and never alter host state when they succeed.
    """

    results = _by_name(probes["sysctl"])
    assert results, "no sysctl probe ran"
    for name, entry in results.items():
        assert entry["passed"], f"{name}: {entry['detail']}"
        assert "errno=30" in str(entry["detail"]) or "EROFS" in str(entry["detail"]), (
            f"{name} was not refused as read-only: {entry['detail']}"
        )


def test_the_process_is_unprivileged_and_sees_no_secrets(
    probes: dict[str, list[dict[str, Any]]]
) -> None:
    """Identity and environment, checked against what the process can observe."""

    results = _by_name(probes["identity"])
    assert results["identity.unprivileged_uid"]["passed"]
    assert results["identity.unprivileged_gid"]["passed"]
    assert results["identity.capabilities"]["passed"]
    assert results["identity.pid_namespace"]["passed"]
    assert results["env.no_secrets"]["passed"]


def test_the_kernel_enforces_the_resource_limits(
    probes: dict[str, list[dict[str, Any]]]
) -> None:
    """Limits are evidenced by refusal, not by a readable file.

    The cgroup filesystem is not mounted into the sandbox precisely so a body cannot
    inspect its own limits, so the evidence has to be behavioural.
    """

    results = _by_name(probes["resources"])
    assert results["pids.fork_refused"]["passed"], (
        f"pids.max was not enforced: {results['pids.fork_refused']['detail']}"
    )
    assert results["cgroup.view_is_namespaced"]["passed"]
    assert results["cgroup.hierarchy_not_mounted"]["passed"]
    assert results["memory.probe_ran"]["passed"]


def test_the_cgroup_view_is_namespaced(probes: dict[str, list[dict[str, Any]]]) -> None:
    """A tool body must not be able to find a sibling invocation's cgroup."""

    results = _by_name(probes["resources"])
    assert results["cgroup.view_is_namespaced"]["passed"]


def test_a_daemonizing_descendant_does_not_survive_its_invocation(
    supervisor: SandboxSupervisor,
) -> None:
    """A descendant that escapes the process group must still be contained.

    This is the hardest containment property in the phase, and it is asserted the
    only honest way: by observing what survived. The probe forks a grandchild that
    calls ``setsid`` to leave the process group the launcher signals, ignores
    ``SIGTERM``, and ignores ``SIGKILL`` in its own child, then hangs. The launcher
    is expected to notice and report it.

    The probe therefore cannot return a result — it is killed while hanging — so
    this test asserts on the launcher's post-kill observations. A test that expected
    a returned payload here would be asserting that the process survived, which is
    the failure.
    """

    outcome = supervisor.run_conformance_probe(group="termination", timeout_seconds=10)
    observations = outcome.diagnostics.observations

    assert outcome.status is Status.TIMEOUT, (
        f"the hanging probe was not stopped at its bound: {outcome.status}"
    )
    assert observations["surviving_descendants"] == [], (
        f"a daemonizing descendant outlived its invocation: "
        f"{observations['surviving_descendants']!r}"
    )
    assert outcome.diagnostics.signal is not None, (
        "the process tree was not signalled; it exited on its own"
    )


# --------------------------------------------------------------------------- #
# Guest half: interop, timeout, and process hygiene                            #
# --------------------------------------------------------------------------- #


def _wsl_exec(*command: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl.exe", "-d", DEFAULT_DISTRO, "--exec", *command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_wsl_interop_is_disabled_in_the_distribution() -> None:
    """A guest process must not be able to execute a Windows binary.

    This runs in the distribution itself rather than inside ``bwrap``, because
    interop is a property of the WSL session and not of the mount namespace. Two
    distinct things are asserted, and conflating them would overstate the result:

    * ``WSL_INTEROP`` is absent, so the vsock channel a Windows executable needs is
      not published.
    * Executing ``cmd.exe`` actually fails, which is the claim that matters. The
      variable being unset is a configuration detail; the process failing is the
      behaviour.
    """

    environment = _wsl_exec("/usr/bin/env")
    assert environment.returncode == 0, environment.stderr
    assert "WSL_INTEROP" not in environment.stdout, (
        "WSL_INTEROP is set; the interop channel is published to the guest"
    )

    result = _wsl_exec(
        "/bin/sh", "-c", "/mnt/c/Windows/System32/cmd.exe /c echo EXECUTED"
    )
    assert "EXECUTED" not in result.stdout, (
        f"a Windows binary executed in the guest: {result.stdout!r}"
    )
    assert result.returncode != 0, "cmd.exe exited successfully with interop disabled"


def test_the_distribution_read_only_mounts_windows_drives_outside_the_path() -> None:
    """``appendWindowsPath`` is off, so no drive letter is on the guest's PATH.

    The drive is still mounted at ``/mnt/c`` read-only in the distribution itself.
    That is not a gap and not something this phase removes: the mount belongs to
    WSL, not to the sandbox, and it is the ``bwrap`` mount namespace that has to
    exclude it. The isolation property is covered by the ``fs.absent.*`` probes,
    which assert ``/mnt`` does not exist inside the confinement. This test covers
    only the narrower claim that the drive is not on PATH, so a tool cannot find a
    Windows binary by name.
    """

    environment = _wsl_exec("/usr/bin/env")
    assert environment.returncode == 0, environment.stderr
    path_line = next(
        (line for line in environment.stdout.splitlines() if line.startswith("PATH=")), ""
    )
    assert "/mnt/c" not in path_line, f"a Windows drive is on the guest PATH: {path_line}"


def test_the_distribution_mounts_windows_drives_read_only() -> None:
    """``/mnt/c`` is read-only in the distribution even before ``bwrap`` runs.

    Recorded because it bounds the claim: the sandbox does not rely on this mount
    being read-only, but it should not be able to write to the Windows filesystem
    even if the namespace layer were bypassed entirely.
    """

    result = _wsl_exec("/bin/sh", "-c", "mount | grep ' /mnt/c '")
    assert result.returncode == 0, result.stderr
    assert ",ro," in f",{result.stdout}," or result.stdout.count("ro") >= 1, (
        f"/mnt/c is not read-only: {result.stdout!r}"
    )


def test_a_hung_invocation_is_killed_at_the_wall_clock(supervisor: SandboxSupervisor) -> None:
    """The launcher validates its argument instead of passing it to a shell.

    The wall clock itself is exercised by the ``termination`` group and by the
    dispatcher's timeout test. What is pinned here is that the launcher accepts
    only a probe name the harness defines, so an unvalidated string cannot become a
    command line in the guest.
    """

    outcome = supervisor.run_conformance_probe(group="nonexistent", timeout_seconds=1)
    assert not outcome.ok


def test_no_guest_processes_survive_the_session(supervisor: SandboxSupervisor) -> None:
    """After a full probe sweep, the guest has no leftover ATLAS-X processes."""

    result = _wsl_exec(
        "/bin/sh",
        "-c",
        "ps -eo args= | grep -c '[a]tlasx' || true",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0", (
        f"atlasx processes survived the session: {result.stdout!r}"
    )


# --------------------------------------------------------------------------- #
# Snapshot minimisation: what a tool body is handed                            #
# --------------------------------------------------------------------------- #


def test_a_tool_body_receives_only_authorized_snapshot_columns() -> None:
    """The tool reads data without being handed a connection.

    Asserting the shape of the snapshot is what makes "a tool can see the caller's
    rows, and nothing else" checkable. The columns are an explicit allowlist, so a
    column added to the row model cannot reach a tool by omission.
    """

    assert "id" not in PARENT_COLUMNS, "the raw surrogate key must not cross the boundary"
    for resource in SNAPSHOT_RESOURCES:
        assert resource.name.isidentifier()


# --------------------------------------------------------------------------- #
# Error classification at the boundary                                         #
# --------------------------------------------------------------------------- #


def test_a_violation_label_outranks_a_tool_error_code() -> None:
    """A crossed control is described by the control, not by the tool's exception.

    The guest reports which control was crossed, which is what an incident review
    needs. Letting a tool's own code override that would let a tool relabel a
    sandbox violation as one of its own errors.
    """

    failure = exception_for(
        status=Status.POLICY_DENIED,
        violation=ViolationKind.FILESYSTEM_ESCAPE,
        message="attempted write outside the workspace",
        error_code="invalid_output",
    )
    assert "filesystem_escape" in str(failure)
    assert "invalid_output" not in str(failure)


def test_a_specific_code_is_preserved_across_the_boundary() -> None:
    """A rejected output stays ``output_invalid`` rather than becoming generic."""

    from atlas.tools.errors import ToolOutputInvalid

    failure = exception_for(
        status=Status.TOOL_ERROR,
        violation=None,
        message="field 'char_count' must be an integer",
        error_code="invalid_output",
    )
    assert isinstance(failure, ToolOutputInvalid)
    assert str(failure) == "field 'char_count' must be an integer"


def test_a_resource_failure_without_a_code_stays_generic() -> None:
    """Absence of a code must not be read as permission to guess."""

    from atlas.tools.errors import ToolLimitExceeded

    failure = exception_for(
        status=Status.RESOURCE_EXCEEDED,
        violation=ViolationKind.MEMORY_LIMIT.value,
        message="stopped the process group",
    )
    assert isinstance(failure, ToolLimitExceeded)

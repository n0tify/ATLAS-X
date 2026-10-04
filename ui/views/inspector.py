"""System Inspector - the actual implementation status of each core component.

The twelve rows below are the whole point of this page, so the way each status
is decided matters more than how it looks.

A status is never asserted. Each row names a module and a public entry point,
and the row is filled in by probing that entry point at runtime:

* ``Implemented`` - the module imports and the named public service class is
  present. The evidence cell says exactly what was probed.
* ``Not implemented`` - the module does not expose the named entry point. For
  ``atlas.provenance`` and ``atlas.evaluation`` this is a real, current finding:
  both packages are one-line docstrings with no exports, so the probe fails.

Where the core exposes a live measurement rather than mere presence, the row
shows the measurement: the number of registered tools, the permission matrix
size, the verifier's rule coverage. Where a status would require running
something expensive or that would change system state, the row says so instead
of guessing - sandbox health is a real ``wsl.exe`` probe and is therefore only
reported when the operator asks for it, and end-to-end coverage is a property of
the test suite rather than of a running process.
"""

from __future__ import annotations

import importlib
from typing import Any, NamedTuple

import streamlit as st

from ui.presentation import NO_DATA, NOT_IMPLEMENTED, definition_list, not_implemented
from ui.runtime import Workspace

IMPLEMENTED = "Implemented"


class Component(NamedTuple):
    """One inspector row: a name, what to probe, and how to describe the probe."""

    name: str
    module: str
    entry_point: str
    probe: str


COMPONENTS: tuple[Component, ...] = (
    Component(
        "Authentication",
        "atlas.auth.service",
        "AuthService",
        "import + class present",
    ),
    Component(
        "Authorization",
        "atlas.security.service",
        "AuthorizationService",
        "import + class present",
    ),
    Component(
        "Tools",
        "atlas.tools.registry",
        "ToolRegistry",
        "import + class present",
    ),
    Component(
        "Sandbox",
        "atlas.sandbox.supervisor",
        "SandboxSupervisor",
        "import + class present",
    ),
    Component(
        "Planner",
        "atlas.planner.service",
        "PlannerService",
        "import + class present",
    ),
    Component(
        "Executor",
        "atlas.executor.service",
        "ExecutorService",
        "import + class present",
    ),
    Component(
        "Verifier",
        "atlas.verifier.service",
        "VerifierService",
        "import + class present",
    ),
    Component(
        "Provenance",
        "atlas.provenance",
        "ProvenanceService",
        "import + class present",
    ),
    Component(
        "Failure Classification",
        "atlas.failure.service",
        "FailureService",
        "import + class present",
    ),
    Component(
        "Recovery",
        "atlas.recovery.service",
        "RecoveryService",
        "import + class present",
    ),
    Component(
        "Artifacts",
        "atlas.artifact.service",
        "ArtifactService",
        "import + class present",
    ),
)


def probe(component: Component) -> tuple[str, str]:
    """Return ``(status, evidence)`` for one component, from a live import."""

    try:
        module = importlib.import_module(component.module)
    except Exception as exc:  # noqa: BLE001 - the failure text is the evidence
        return NOT_IMPLEMENTED, f"import failed: {type(exc).__name__}: {exc}"

    if hasattr(module, component.entry_point):
        return IMPLEMENTED, f"`{component.module}.{component.entry_point}` present"
    return (
        NOT_IMPLEMENTED,
        f"`{component.module}` exposes no `{component.entry_point}` "
        f"(public names: {', '.join(sorted(getattr(module, '__all__', ()))) or 'none'})",
    )


def policy_facts(services: Workspace) -> list[tuple[str, object]]:
    """The real authorization matrix, read from the policy module."""

    from atlas.security.policy import (
        OWNERSHIP_UNDECIDED,
        PERMITTED_OPERATIONS,
        PROHIBITED_TOOL_CAPABILITIES,
    )

    return [
        ("Resource kinds in the matrix", len(PERMITTED_OPERATIONS)),
        (
            "Permitted (resource, operation) pairs",
            sum(len(operations) for operations in PERMITTED_OPERATIONS.values()),
        ),
        ("Never-grantable tool capabilities", len(PROHIBITED_TOOL_CAPABILITIES)),
        (
            "Resources with no established owner",
            ", ".join(sorted(resource.value for resource in OWNERSHIP_UNDECIDED)) or "none",
        ),
    ]


def verifier_facts(services: Workspace) -> list[tuple[str, object]]:
    """Real verifier rule coverage against the real frozen registry."""

    registered = set(services.registry.capabilities())
    covered = set(services.rules.tool_ids())
    uncovered = sorted(registered - covered)
    return [
        ("Registered tools", len(registered)),
        ("Tools with a verification rule", len(registered & covered)),
        (
            "Registered tools with no rule",
            ", ".join(uncovered) if uncovered else "none",
        ),
        (
            "Note",
            "A tool with no rule cannot produce a PASS; the verifier fails it "
            "with a no-rule code.",
        ),
    ]


def sandbox_health(services: Workspace) -> dict[str, Any]:
    """Probe the guest on demand and remember the result with its as-of time."""

    if "inspector.sandbox_health" in st.session_state:
        return dict(st.session_state["inspector.sandbox_health"])

    if st.button("Probe sandbox guest", key="inspector.probe_sandbox"):
        with st.spinner("Probing the WSL guest..."):
            health = dict(services.sandbox.health())
        from atlas.util import utcnow_iso

        health["as_of"] = utcnow_iso()
        st.session_state["inspector.sandbox_health"] = health
        return health

    st.caption(
        "Not probed. `SandboxSupervisor.health()` starts a `wsl.exe` process and "
        "may take up to 60 seconds, so it is never run implicitly."
    )
    return {}


def render(services: Workspace) -> None:
    st.title("System Inspector")
    st.caption(
        "Each row is produced by probing the named module and public entry point "
        "in this process. No row is asserted, and nothing here is a projection "
        "of what the documentation claims."
    )

    records: list[dict[str, Any]] = []
    for component in COMPONENTS:
        status, evidence = probe(component)
        records.append(
            {"component": component.name, "status": status, "evidence": evidence}
        )

    records.append(
        {
            "component": "E2E",
            "status": "Not queryable at runtime",
            "evidence": (
                "End-to-end coverage is a property of `tests/test_phase18_e2e.py` "
                "under pytest, not of a running process. No core API reports it, "
                "so this surface does not assert a result. Run the suite to observe it."
            ),
        }
    )

    st.dataframe(
        records,
        hide_index=True,
        width="stretch",
        column_config={
            "component": st.column_config.TextColumn("Component", width="medium"),
            "status": st.column_config.TextColumn("Status", width="small"),
            "evidence": st.column_config.TextColumn("Evidence", width="large"),
        },
    )

    section = st.container()
    with section:
        st.subheader("Sandbox")
        health = sandbox_health(services)
        if not health:
            st.text(NO_DATA)
        else:
            st.json(health, expanded=True)
            st.caption(
                "Returned by `SandboxSupervisor.health()`. An unavailable guest is a "
                "reported state, not a bypass: every dispatch still fails closed."
            )

    with st.container():
        st.subheader("Authorization matrix")
        definition_list(policy_facts(services))
        st.caption(
            "Read from `atlas.security.policy`. Declared here is enforced by "
            "`AuthorizationService`; this surface does not re-derive any decision."
        )

    with st.container():
        st.subheader("Verifier rule coverage")
        definition_list(verifier_facts(services))

    with st.container():
        st.subheader("Absent from the core")
        not_implemented(
            "A cross-task, owner-scoped provenance audit view.",
            detail=(
                "Provenance rows are reachable per task through "
                "`AuthorizationService.list_owned_resources`, but no core call "
                "aggregates them across a user's tasks."
            ),
        )
        not_implemented(
            "A provenance chain verification call.",
            detail=(
                "`ProvenanceRepo.verify_chain_for_task` exists in storage but has no "
                "session-token wrapper, so no owner-scoped surface may call it."
            ),
        )
        not_implemented(
            "Artifact content serving.",
            detail="`ArtifactService` records metadata and never returns file content.",
        )
        not_implemented(
            "Evaluation and benchmarks.",
            detail="`atlas.evaluation` is a one-line stub with no exports.",
        )

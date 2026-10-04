"""Home / Dashboard - orientation in real system state, and nothing else.

There is no decorative telemetry here. Every tile is a number the core returned
for this session's authenticated user, and every tile names the call it came
from. Tiles that have no backing call are named as absent in an expander rather
than shown as zero, because a zero reads as a measurement and would be a
fabricated result.

There are also no actions here beyond navigation and refresh. Nothing on this
page starts, stops, cancels, or retries work.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from atlas import __version__
from atlas.util import utcnow_iso
from ui.presentation import (
    TASK_STATUSES,
    definition_list,
    denied,
    metrics_or_markers,
    no_data,
    not_implemented,
    status_badge,
)
from ui.runtime import Workspace, current_token
from ui.views.tasks import Refused, read

UNAVAILABLE_TILES: tuple[tuple[str, str], ...] = (
    (
        "Execution throughput",
        "`execution_runs` has no aggregate call and this surface does not compute one "
        "from rows it did not fetch.",
    ),
    (
        "Pass rate",
        "A pass rate over all users would be a cross-user aggregate, which the "
        "owner-scoped service will not produce.",
    ),
    (
        "Artifact volume",
        "`ArtifactService.list_for_task` is per task; there is no per-user total.",
    ),
    (
        "Benchmark and experiment results",
        "`atlas.evaluation` is a stub and `evaluation_runs` has no owner column.",
    ),
)


def render_identity(services: Workspace) -> Any:
    identity = services.identity(current_token())
    st.subheader("Session")
    if identity is None:
        no_data("no valid session")
        return None

    definition_list(
        [
            ("username", identity.username),
            ("user_id", identity.user_id),
            ("session_id", identity.session_id),
            ("expires_at", identity.expires_at),
        ]
    )
    st.caption(
        "Resolved by `AuthorizationService.authenticate` on this render. The token "
        "stays in server-side session state and is never placed in the browser, a "
        "URL, or a client-side store."
    )
    return identity


def render_metrics(services: Workspace, identity: Any) -> None:
    st.subheader("Real system state")
    try:
        tasks = read(lambda: services.authorization.list_tasks(current_token()))
    except Refused as exc:
        denied(exc)
        return

    counts = {status: 0 for status in TASK_STATUSES}
    for record in tasks:
        counts[status_badge(record.get("status"))] = (
            counts.get(status_badge(record.get("status")), 0) + 1
        )
    terminal = sum(
        count for status, count in counts.items() if status in ("succeeded", "failed")
    )

    metrics_or_markers(
        [
            ("Tasks owned", len(tasks), "AuthorizationService.list_tasks"),
            ("Registered tools", len(services.registry), "default_registry()"),
            ("Tool grants held", len(services.grants.list_for_user(identity.user_id)),
             "ToolGrantRepo.list_for_user"),
            ("Tools with a verification rule", len(set(services.rules.tool_ids())),
             "RuleRegistry.tool_ids()"),
        ],
        not_implemented_tiles=UNAVAILABLE_TILES,
    )

    st.markdown("**Task status distribution**")
    st.caption(
        "Counted from the rows returned for this user. Status values are counted "
        "verbatim; the vocabulary is the one in `atlas.storage.task_status`."
    )
    st.dataframe(
        [{"status": status, "tasks": counts.get(status, 0)} for status in sorted(counts)]
        + ([{"status": "terminal (succeeded + failed)", "tasks": terminal}] if tasks else []),
        hide_index=True,
        width="stretch",
    )
    if not tasks:
        no_data("this account owns no tasks")

    with st.expander("Unrecognized stored statuses"):
        st.caption(
            "A stored status outside the documented vocabulary is counted under its "
            "raw value above and is never coerced into a neighbouring state."
        )


def render_build(services: Workspace) -> None:
    st.subheader("Build")
    definition_list(
        [
            ("atlas.__version__", __version__),
            ("environment", services.environment),
            ("database_path", str(services.settings.database_path)),
            ("schema is applied by", "Database.initialize() -> init_db()"),
            ("rendered at", utcnow_iso()),
        ]
    )
    st.caption(
        "The timestamp is this render's time, not a system measurement. It is labelled "
        "so it cannot be read as one."
    )


def render_absent() -> None:
    st.markdown("#### Not present in this build")
    not_implemented(
        "Benchmarks and experiments.",
        detail="No evaluation harness exists; `atlas.evaluation` is a stub package.",
    )
    not_implemented(
        "Provenance chain integrity.",
        detail=(
            "No session-token surface exposes `ProvenanceRepo.verify_chain_for_task`, so "
            "the workspace cannot assert that a chain is intact."
        ),
    )
    not_implemented(
        "Artifact content.",
        detail="Artifact content is recorded but never served by a core service.",
    )
    not_implemented(
        "A living system map or animation layer.",
        detail=(
            "Nothing on this page moves, and no progress indicator is shown, because "
            "there is no recorded event to animate."
        ),
    )


def render(services: Workspace) -> None:
    st.title("ATLAS-X")
    st.caption(
        "A local-first research platform for reliable, verifiable, secure multi-step "
        "agents. This workspace reads the core; it never decides, and it never invents."
    )

    identity = render_identity(services)
    if identity is None:
        return

    render_metrics(services, identity)
    render_build(services)
    render_absent()

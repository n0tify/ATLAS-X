"""Security & Provenance - effective configuration and recorded provenance.

Three things are shown, and each is a read the core sanctioned:

* ``Settings.safe_dump()`` - the only secret-safe configuration projection. It
  excludes ``application_secret_key``, and this surface does not re-implement
  field filtering, so there is no second place where a field could be forgotten.
* The authorization matrix and the never-grantable capability list from
  ``atlas.security.policy``, labelled as *declared* policy and attributed to the
  component that enforces it.
* The caller's own provenance events, per task, through
  ``AuthorizationService.list_owned_resources``.

Three things are explicitly absent and are named rather than faked:

* No configuration can be changed here. The display is read-only, so there is no
  setting a browser could alter.
* No provenance event can be edited, reordered, or deleted. Re-layout on this
  page is presentation only.
* ``provenance_events.detail_json`` is shown as a JSON tree. It is an unredacted
  caller-supplied document, and no redaction policy for it exists yet, so this
  surface presents it as data and applies no filtering of its own rather than
  pretending a policy it does not have.
"""

from __future__ import annotations

import streamlit as st

from atlas.security.policy import (
    OWNERSHIP_UNDECIDED,
    PERMITTED_OPERATIONS,
    PROHIBITED_TOOL_CAPABILITIES,
    Resource,
)
from ui.presentation import (
    definition_list,
    denied,
    empty_or_table,
    no_data,
    not_implemented,
    stored_json,
)
from ui.runtime import Workspace, current_token, effective_configuration
from ui.views.tasks import Refused, owned, read

PROVENANCE_FIELDS = (
    "sequence_no",
    "event_type",
    "actor",
    "tool_id",
    "invocation_id",
    "chain_digest",
    "created_at",
)


def render_configuration(services: Workspace) -> None:
    st.subheader("Effective configuration")
    st.caption(
        "Read-only, from `Settings.safe_dump()`. `application_secret_key` is excluded "
        "by the projection itself. Nothing on this page can change a setting."
    )
    configuration = effective_configuration(services)
    definition_list(sorted(configuration.items()))
    st.caption(
        "The application secret is required when environment='production' and is "
        "unused by any current code. It is not a signing or encryption key."
    )


def render_policy() -> None:
    st.subheader("Declared authorization policy")
    st.caption(
        "Declared here, enforced by `AuthorizationService`. This surface renders the "
        "declaration and never re-derives a decision from it."
    )
    definition_list(
        [
            ("Resource kinds", len(PERMITTED_OPERATIONS)),
            (
                "Permitted (resource, operation) pairs",
                sum(len(operations) for operations in PERMITTED_OPERATIONS.values()),
            ),
            ("Never-grantable capabilities", len(PROHIBITED_TOOL_CAPABILITIES)),
            (
                "Resources with no established owner",
                ", ".join(sorted(resource.value for resource in OWNERSHIP_UNDECIDED))
                or "none",
            ),
            (
                "Prohibited capabilities",
                ", ".join(sorted(PROHIBITED_TOOL_CAPABILITIES)),
            ),
        ]
    )

    st.markdown("**Permission matrix**")
    st.dataframe(
        [
            {
                "resource": resource.value,
                "operations": ", ".join(sorted(operation.value for operation in operations)),
            }
            for resource, operations in sorted(
                PERMITTED_OPERATIONS.items(), key=lambda item: item[0].value
            )
        ],
        hide_index=True,
        width="stretch",
    )


def render_grants(services: Workspace) -> None:
    st.subheader("Caller grant position")
    user_id = st.session_state.get("atlasx.user_id")
    if not isinstance(user_id, int):
        no_data("no authenticated identity")
        return

    grants = [dict(record) for record in services.grants.list_for_user(user_id)]
    definition_list(
        [
            ("Registry ready for grants", services.grants.registry_ready),
            ("Grant records", len(grants)),
            ("Capabilities held", len(services.grants.capabilities_for(user_id))),
        ]
    )
    empty_or_table(
        grants,
        ("id", "tool_name", "scope", "granted_by", "created_at"),
        what="this user holds no grant records",
    )
    st.caption(
        "Read-only. Deny-by-default means absence of a grant is a real state, not a "
        "gap in the display."
    )


def render_provenance(services: Workspace) -> None:
    st.subheader("Provenance")
    st.caption(
        "Owner-scoped reads. Events with neither a task nor an execution are denied to "
        "every caller, so they cannot appear here."
    )

    try:
        tasks = read(lambda: services.authorization.list_tasks(current_token()))
    except Refused as exc:
        denied(exc)
        return

    if not tasks:
        no_data("this account owns no tasks, so there is no provenance to audit")
        return

    labels = {int(task["id"]): f"#{task['id']}  {task.get('title')}" for task in tasks}
    selected = st.selectbox(
        "Audit a task's provenance",
        options=list(labels),
        format_func=lambda value: labels[value],
        key="security.provenance_task",
    )

    try:
        events = owned(services, current_token(), Resource.PROVENANCE_EVENT, selected)
    except Refused as exc:
        denied(exc)
        return

    empty_or_table(events, PROVENANCE_FIELDS, what="this task has no provenance events")

    for record in events:
        with st.expander(f"event {record.get('sequence_no')} detail"):
            stored_json(record.get("detail_json"), "provenance_events.detail_json")

    st.caption(
        "Append-only. This page exposes no control that edits, reorders, or deletes an "
        "event, and no control that re-runs or repairs one."
    )


def render_gaps() -> None:
    st.markdown("#### Absent from the core")
    not_implemented(
        "A cross-task, owner-scoped provenance audit.",
        detail=(
            "Provenance rows are reachable per task, but no core call aggregates them "
            "across a user's tasks, so this page does not attempt it."
        ),
    )
    not_implemented(
        "Chain verification.",
        detail=(
            "`ProvenanceRepo.verify_chain_for_task` exists in storage but has no "
            "session-token wrapper. A digest column is displayed; whether the chain is "
            "intact is not asserted."
        ),
    )
    not_implemented(
        "A redaction policy for `provenance_events.detail_json`.",
        detail=(
            "The column is an unredacted caller-supplied document. This surface shows "
            "it as data and applies no filtering, rather than implying a policy that "
            "does not exist."
        ),
    )
    not_implemented(
        "CSRF protection for this browser surface.",
        detail="No browser-facing application existed before this one; the posture is undecided.")


def render(services: Workspace) -> None:
    st.title("Security & Provenance")
    st.caption(
        "Read-only. This page cannot change a setting, alter a record, or decide an "
        "authorization outcome."
    )
    render_configuration(services)
    render_policy()
    render_grants(services)
    render_provenance(services)
    render_gaps()


"""Tools — the frozen registry, and the caller's own grant position.

Two sources, both real:

* ``ToolRegistry.describe_all()`` is the metadata projection the registry builds
  from the definitions themselves. It reads a description, it does not call a
  tool body. No tool is invoked from this page.
* ``ToolGrantRepo.list_for_user`` / ``capabilities_for`` is the caller's own
  grant position, read for the authenticated user id that the core resolved.

There is no grant, revoke, enable, or edit control here, and there will not be
one. A permission change is a core operation with audit requirements; a control
that appeared to change one from a browser would be a control whose only
enforcement was the button.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from ui.presentation import (
    NO_DATA,
    definition_list,
    empty_or_table,
    not_implemented,
    stored_json,
)
from ui.runtime import Workspace

REGISTRY_FIELDS = (
    "tool_id",
    "title",
    "version",
    "determinism",
    "filesystem_access",
    "network_access",
    "requires_sandbox",
    "implementation_id",
)

GRANT_FIELDS = ("id", "tool_name", "scope", "granted_by", "created_at")


def registry_facts(services: Workspace) -> list[tuple[str, object]]:
    return [
        ("Registered tools", len(services.registry)),
        ("Registry frozen", services.registry.frozen),
        (
            "Frozen means",
            "the tool set cannot change while the process runs, so a grant "
            "decided against one tool set cannot be spent against another",
        ),
    ]


def prohibited_capabilities() -> list[tuple[str, object]]:
    from atlas.security.policy import PROHIBITED_TOOL_CAPABILITIES

    return [
        ("Never-grantable capabilities", ", ".join(sorted(PROHIBITED_TOOL_CAPABILITIES))),
        (
            "Enforced by",
            "`atlas.security.policy.decide_tool_invocation`, which normalizes the "
            "name before comparing, so a re-spelling cannot slip past",
        ),
    ]


def grant_facts(services: Workspace, user_id: int) -> list[tuple[str, object]]:
    granted = services.grants.list_for_user(user_id)
    capabilities = services.grants.capabilities_for(user_id)
    return [
        ("Registry ready for grants", services.grants.registry_ready),
        ("Grant records held", len(granted)),
        ("Capabilities held", len(capabilities)),
    ]


def render(services: Workspace) -> None:
    st.title("Tools")
    st.caption(
        "Built by `default_registry()` at application start and frozen. Listing the "
        "registry reads metadata only; no tool implementation is reachable from this page."
    )

    definition_list(registry_facts(services))

    definitions = services.registry.describe_all()

    st.subheader("Registered tools")
    empty_or_table(
        definitions,
        REGISTRY_FIELDS,
        what="the registry is empty",
        column_config={
            "requires_sandbox": st.column_config.CheckboxColumn("Sandboxed"),
            "tool_id": st.column_config.TextColumn("Tool id", width="medium"),
            "title": st.column_config.TextColumn("Title", width="medium"),
        },
    )

    covered = set(services.rules.tool_ids())
    if definitions:
        st.caption(
            "Verification rule present for: "
            + (", ".join(sorted(covered)) if covered else NO_DATA)
        )

    st.subheader("Caller grant position")
    st.caption(
        "Read-only. There is no grant, revoke, or enable control on this page by design: "
        "hiding a control is cosmetic and the core is what refuses."
    )
    user_id = st.session_state.get("atlasx.user_id")
    if not isinstance(user_id, int):
        st.text(NO_DATA)
    else:
        definition_list(grant_facts(services, user_id))
        grants = [dict(record) for record in services.grants.list_for_user(user_id)]
        empty_or_table(grants, GRANT_FIELDS, what="this user holds no grant records")
        if not grants:
            st.info(
                "Absence of a grant is a legitimate display state. Tool invocation "
                "is deny-by-default, so every capability above is currently refused."
            )

    st.subheader("Prohibited capabilities")
    definition_list(prohibited_capabilities())

    st.subheader("Declaration")
    st.caption(
        "A declared limit is what the definition says; enforcement happens in the "
        "dispatcher and the sandbox guest. This surface labels the two apart and "
        "does not claim a limit is applied because it is declared."
    )

    if definitions:
        selected = st.selectbox(
            "Inspect one tool",
            options=[str(record["tool_id"]) for record in definitions],
            key="tools.selected",
        )
        record: dict[str, Any] | None = next(
            (item for item in definitions if str(item["tool_id"]) == selected), None
        )
        if record is None:
            not_implemented("no definition matched the selected id")
            return
        st.markdown(f"**{record['title']}**")
        st.text(str(record["description"]))
        definition_list(
            [
                ("tool_id", record["tool_id"]),
                ("version", record["version"]),
                ("capability", record["capability"]),
                ("determinism", record["determinism"]),
                ("filesystem_access", record["filesystem_access"]),
                ("network_access", record["network_access"]),
                ("requires_sandbox", record["requires_sandbox"]),
                ("implementation_id", record["implementation_id"]),
                (
                    "limits",
                    ", ".join(
                        f"{key}={value}" for key, value in sorted(dict(record["limits"]).items())
                    ),
                ),
                (
                    "provenance_fields",
                    ", ".join(str(item) for item in record["provenance_fields"]),
                ),
            ]
        )
        st.markdown("**Input schema**")
        stored_json(record["input_schema"])
        st.markdown("**Output schema**")
        stored_json(record["output_schema"])

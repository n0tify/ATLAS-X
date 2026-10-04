"""Tasks - the caller's own tasks, and what the core recorded about them.

Every figure on this page comes from an owner-scoped service call made with the
session token. The page never counts a status it invented, never renders a
status the core did not store, and never shows a ``pending`` or ``failed`` state
as though a record existed for it.

Two things are deliberately absent:

* **No lifecycle control.** There is no start, pause, resume, cancel, retry, or
  re-run button. A cancel affordance in particular would imply a cancellation
  mechanism; none exists in the model, no column holds it, and no service
  performs it. A button that appears to do it and does not is worse than no
  button.
* **No client-side derivation.** The counts in the summary are counted from the
  rows the core returned for this user. They are labelled with the call they came
  from rather than presented as system-wide telemetry.
"""

from __future__ import annotations

from typing import Any, Callable, Collection, Mapping, Sequence

import streamlit as st

from atlas.security.errors import AuthorizationError
from atlas.security.policy import Resource
from atlas.storage.verification_repo import RESULT_FAIL, RESULT_PASS
from ui.presentation import (
    TASK_STATUSES,
    definition_list,
    denied,
    empty_or_table,
    no_data,
    not_implemented,
    stored,
    stored_json,
    unrecognized,
)
from ui.runtime import Workspace, current_token

#: The values the verifier writes to ``verifications.result``, taken from the
#: repository that owns the column rather than typed out here.
VERIFICATION_RESULTS = (RESULT_PASS, RESULT_FAIL)

PLAN_FIELDS = ("id", "status", "source", "model_id", "validated", "created_at")
STEP_FIELDS = ("position", "step_key", "action", "tool_id", "status", "failure_category")
EXECUTION_FIELDS = (
    "id",
    "attempt",
    "status",
    "tool_id",
    "invocation_id",
    "origin",
    "started_at",
    "finished_at",
    "error_code",
)
VERIFICATION_FIELDS = (
    "id",
    "execution_id",
    "result",
    "verifier",
    "verifier_version",
    "plan_step_id",
    "artifact_id",
    "created_at",
)
FAILURE_FIELDS = ("id", "execution_id", "category", "error_code", "retryable", "created_at")
ARTIFACT_FIELDS = (
    "id",
    "execution_id",
    "name",
    "kind",
    "size_bytes",
    "checksum",
    "source",
    "verified",
    "created_at",
)
RECOVERY_FIELDS = ("id", "execution_id", "attempt_no", "outcome", "failure_id", "finished_at")
PROVENANCE_FIELDS = (
    "sequence_no",
    "event_type",
    "actor",
    "tool_id",
    "invocation_id",
    "chain_digest",
    "created_at",
)


class Refused(Exception):
    """A core refusal, already reduced to the only text that may be shown.

    ``AuthorizationError.external_message`` is deliberately the same string for
    every reason code, which is what stops a refused lookup from becoming a
    resource-existence oracle. Carrying it as ``external_message`` lets
    :func:`ui.presentation.denied` render it without this module re-deriving or
    explaining a reason it was not given.
    """

    def __init__(self, external_message: str) -> None:
        self.external_message = external_message
        super().__init__(external_message)


def read(call: Callable[[], Sequence[Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Run an owner-scoped core read and return its rows.

    A refusal is raised as :class:`Refused` carrying the core's external message.
    It is never converted into an empty result: a denial and an absent record look
    identical to the reader otherwise, and one of them is a security outcome.
    """

    try:
        records = call()
    except AuthorizationError as exc:
        raise Refused(exc.external_message) from exc
    return [dict(record) for record in records]


def read_one(call: Callable[[], Mapping[str, Any] | None]) -> dict[str, Any] | None:
    try:
        record = call()
    except AuthorizationError as exc:
        raise Refused(exc.external_message) from exc
    return None if record is None else dict(record)


def owned(
    services: Workspace,
    token: object,
    resource: Resource,
    task_id: int,
) -> list[dict[str, Any]]:
    return read(
        lambda: services.authorization.list_owned_resources(
            token, resource=resource, task_id=task_id
        )
    )


def status_label(value: object, vocabulary: Collection[str]) -> str:
    """A stored status, verbatim, annotated when it is outside the vocabulary."""

    return unrecognized(value, vocabulary)


def render_task_list(services: Workspace) -> list[dict[str, Any]]:
    st.subheader("Owned tasks")
    try:
        tasks = read(lambda: services.authorization.list_tasks(current_token()))
    except Refused as exc:
        denied(exc)
        return []

    if not tasks:
        no_data("this account owns no tasks")
        return []

    st.dataframe(
        [
            {
                "id": record.get("id"),
                "title": record.get("title"),
                "status": status_label(record.get("status"), TASK_STATUSES),
                "created_at": record.get("created_at"),
                "updated_at": record.get("updated_at"),
            }
            for record in tasks
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"{len(tasks)} row(s) from `AuthorizationService.list_tasks`, scoped to the "
        "authenticated user. No cross-user aggregate is computed."
    )
    return tasks


def render_summary(
    task: Mapping[str, Any],
    executions: Sequence[Mapping[str, Any]],
    verifications: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    recoveries: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
) -> None:
    st.markdown("#### Counts")
    definition_list(
        [
            ("Stored status (verbatim)", status_label(task.get("status"), TASK_STATUSES)),
            ("Executions", len(executions)),
            ("Verifications", len(verifications)),
            ("Failures", len(failures)),
            ("Recovery attempts", len(recoveries)),
            ("Artifacts", len(artifacts)),
            ("Provenance events", len(events)),
        ]
    )
    st.caption("Counted from the rows returned by the owner-scoped calls on this page.")


def render_plan(services: Workspace, token: object, task_id: int) -> None:
    """Render the head plan, or report the core's refusal verbatim.

    ``plan_head`` signals "this task has no plan" through the *denial* channel,
    with a reason this surface is not given. It is therefore rendered as the
    refusal it is. Reporting it as an absence instead would be a claim about the
    data that the core never made, and the two cases - no plan, and not your task
    - are indistinguishable here by design.
    """

    try:
        head = read_one(lambda: services.authorization.plan_head(token, task_id))
    except Refused as exc:
        denied(exc)
        st.caption(
            "`AuthorizationService.plan_head` refuses when a task has no plan head, and "
            "its reason is not available to this surface. Shown as the refusal the core "
            "returned; no absence is asserted."
        )
        return

    if head is None:
        no_data("this task has no plan")
        return

    st.dataframe(
        [{field: head.get(field) for field in PLAN_FIELDS}],
        hide_index=True,
        width="stretch",
    )
    st.caption(f"Plan id {head.get('id')}; the digest is the one the core recorded.")

    plan_id = int(head["id"])
    try:
        steps = read(lambda: services.authorization.plan_steps(token, plan_id))
    except Refused as exc:
        denied(exc)
        return
    empty_or_table(steps, STEP_FIELDS, what="this plan has no steps")

    with st.expander("Plan document"):
        stored_json(head.get("plan_json"), "plans.plan_json")
    with st.expander("Validation report"):
        stored_json(head.get("validation_json"), "plans.validation_json")


def render_executions(executions: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(
        list(executions), EXECUTION_FIELDS, what="this task has no executions"
    )
    for record in executions:
        with st.expander(f"execution {record.get('id')} detail"):
            stored_json(record.get("result_json"), "executions.result_json")
            stored(record.get("error"), "executions.error")


def render_verifications(verifications: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(
        [
            {**record, "result": status_label(record.get("result"), VERIFICATION_RESULTS)}
            for record in verifications
        ],
        VERIFICATION_FIELDS,
        what="this task has no verification rows",
    )
    for record in verifications:
        with st.expander(f"verification {record.get('id')} detail"):
            stored_json(record.get("detail_json"), "verifications.detail_json")
            stored_json(record.get("evidence_json"), "verifications.evidence_json")
    st.caption(
        "Only a `verifications` row written by the verifier is a verification. This "
        "surface never re-checks a result and offers no check of its own."
    )


def render_failures(failures: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(failures, FAILURE_FIELDS, what="this task has no classified failures")
    for record in failures:
        with st.expander(f"failure {record.get('id')} detail"):
            stored(record.get("diagnosis"), "failures.diagnosis")
            stored_json(record.get("detail_json"), "failures.detail_json")


def render_artifacts(artifacts: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(list(artifacts), ARTIFACT_FIELDS, what="this task has no artifacts")
    for record in artifacts:
        with st.expander(f"artifact {record.get('id')} metadata"):
            stored_json(record.get("metadata_json"), "artifacts.metadata_json")
    not_implemented(
        "Artifact content.",
        detail="`ArtifactService` records metadata and never serves file content.",
    )


def render_recoveries(recoveries: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(
        list(recoveries), RECOVERY_FIELDS, what="this task has no recovery attempts"
    )
    for record in recoveries:
        with st.expander(f"recovery {record.get('id')} detail"):
            stored_json(record.get("detail_json"), "recovery_attempts.detail_json")


def render_provenance(events: Sequence[Mapping[str, Any]]) -> None:
    empty_or_table(
        list(events), PROVENANCE_FIELDS, what="this task has no provenance events"
    )
    for record in events:
        with st.expander(f"event {record.get('sequence_no')} detail"):
            stored_json(record.get("detail_json"), "provenance_events.detail_json")
    st.caption(
        "Provenance is append-only. This surface exposes no control that edits, "
        "reorders, or deletes an event; the layout above is presentation only."
    )


def render_detail(services: Workspace, task: Mapping[str, Any]) -> None:
    token = current_token()
    task_id = int(task["id"])

    st.subheader(f"Task {task_id}")
    definition_list(
        [
            ("id", task.get("id")),
            ("title", task.get("title")),
            ("status (verbatim)", status_label(task.get("status"), TASK_STATUSES)),
            ("created_at", task.get("created_at")),
            ("updated_at", task.get("updated_at")),
            ("verified_at", task.get("verified_at")),
            ("failure_category", task.get("failure_category")),
        ]
    )

    st.markdown("**Goal**")
    stored(task.get("goal"), "Stored goal text, rendered as data.")
    st.caption(
        "Goal text is operator input and plan text is model output. Both are shown as "
        "data and are never interpreted as instructions or markup."
    )

    with st.expander("Stored result"):
        stored_json(task.get("result_json"), "tasks.result_json")

    try:
        executions = read(lambda: services.authorization.executions_for_task(token, task_id))
        verifications = owned(services, token, Resource.VERIFICATION, task_id)
        failures = owned(services, token, Resource.FAILURE, task_id)
        recoveries = owned(services, token, Resource.RECOVERY_ATTEMPT, task_id)
        artifacts = read(lambda: services.artifacts.list_for_task(token, task_id))
        events = owned(services, token, Resource.PROVENANCE_EVENT, task_id)
    except Refused as exc:
        denied(exc)
        return

    render_summary(
        task, executions, verifications, failures, recoveries, artifacts, events
    )

    tabs = st.tabs(
        ["Plan", "Executions", "Verification", "Failures", "Artifacts", "Recovery", "Provenance"]
    )
    with tabs[0]:
        render_plan(services, token, task_id)
    with tabs[1]:
        render_executions(executions)
    with tabs[2]:
        render_verifications(verifications)
    with tabs[3]:
        render_failures(failures)
    with tabs[4]:
        render_artifacts(artifacts)
    with tabs[5]:
        render_recoveries(recoveries)
    with tabs[6]:
        render_provenance(events)


def render_absent() -> None:
    st.markdown("#### Absent from the core")
    not_implemented(
        "Cancellation.",
        detail=(
            "No `cancelled` value exists in `TaskStatus`, no column holds one, and no "
            "service performs one."
        ),
    )
    not_implemented(
        "A `security_blocked` status.",
        detail="No such value exists in the authoritative model, so it is never rendered.",
    )
    not_implemented(
        "Re-running or steering a task from a browser.",
        detail=(
            "There is no session-token surface for the planner or the executor, so no "
            "lifecycle action can be issued from here."
        ),
    )


def render(services: Workspace) -> None:
    st.title("Tasks")
    st.caption(
        "Owner-scoped reads through `AuthorizationService`. Nothing on this page writes, "
        "retries, cancels, or re-runs anything."
    )

    tasks = render_task_list(services)
    if not tasks:
        render_absent()
        not_implemented(
            "Task creation from this surface.",
            detail=(
                "`AuthorizationService.create_task` exists and the core enforces it, but "
                "this workspace is read-only by construction, so no create control is "
                "rendered."
            ),
        )
        return

    labels = {int(task["id"]): f"#{task['id']}  {task.get('title')}" for task in tasks}
    selected = st.selectbox(
        "Inspect a task",
        options=list(labels),
        format_func=lambda value: labels[value],
        key="tasks.selected",
    )
    render_detail(services, next(task for task in tasks if int(task["id"]) == selected))
    render_absent()

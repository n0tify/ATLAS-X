"""Shared display primitives.

The rules in this module come from the standing UI constraints and are the
reason display is not done inline in each view:

* **Verbatim values.** ``tasks.status`` and friends are unconstrained text
  columns. A stored value is rendered as stored. It is classified only if it
  matches a vocabulary the core itself publishes — ``TASK_STATUSES`` here is
  re-exported from ``atlas.storage.task_status`` rather than copied, so this
  surface cannot hold a second, drifting copy of a status vocabulary. A value
  outside the vocabulary is shown raw and labelled, never coerced and never
  hidden.
* **Absent data is stated.** An empty result renders "No data available" and an
  absent capability renders "Not implemented". A plausible zero or a plausible
  sample row is not a truthful substitute for either.
* **Stored text is text.** Every string that came out of the database is
  rendered through :func:`stored`, never as markup. Plan text, tool arguments,
  artifact content, and diagnosis text all originate from a model or a generated
  program and are data, never instructions.
* **No secrets.** Nothing here is given a password hash, a session token, a
  token digest, or ``application_secret_key``. The callers pass projections the
  core already made safe.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import streamlit as st

from atlas.storage.task_status import TASK_STATUSES

#: The two honest markers. Used verbatim wherever a capability or a record is
#: absent, so a reader can tell "absent" from "zero" without interpretation.
NOT_IMPLEMENTED = "Not implemented"
NO_DATA = "No data available"

__all__ = [
    "NO_DATA",
    "NOT_IMPLEMENTED",
    "TASK_STATUSES",
    "column",
    "definition_list",
    "denied",
    "empty_or_table",
    "metrics_or_markers",
    "no_data",
    "not_implemented",
    "rows",
    "status_badge",
    "stored",
    "stored_json",
    "unrecognized",
]


def _cell(value: object) -> str | int | float | bool | None:
    """Coerce one stored value into something a column can hold.

    ``None`` survives as ``None`` because "absent" and "present and empty" are
    different facts and flattening them would lose one. Scalars keep their type so
    a column of ids still sorts numerically. Anything else — a ``Path``, a nested
    mapping, an enum — becomes text, because a column cannot hold a mixture and
    failing to render is a worse answer than rendering the value readably.
    """

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _text(value: object) -> str:
    """Render any scalar as text, keeping absence distinguishable from emptiness."""

    if value is None:
        return "not set"
    if isinstance(value, str):
        return value
    return str(value)


def column(name: str, value: object) -> dict[str, Any]:
    """One cell for :func:`st.dataframe`, preserving ``None`` as missing."""

    return {"column": name, "value": _cell(value)}


def rows(records: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> list[dict[str, Any]]:
    """Project records onto an explicit, fixed column order.

    A field that is absent from a record becomes ``None``. That is a real
    distinction from a field that is present and empty, and it is preserved
    rather than flattened to ``""``.
    """

    return [{field: _cell(record.get(field)) for field in fields} for record in records]


def stored(value: object, label: str | None = None) -> None:
    """Render a stored string as text, never as markup."""

    if label is not None:
        st.caption(label)
    st.text("" if value is None else str(value))


def stored_json(value: object, label: str | None = None) -> None:
    """Render a stored JSON document as a JSON tree.

    ``st.json`` never interprets the value as HTML or as code, which is what
    makes it safe for a provenance event's ``detail_json``.
    """

    if label is not None:
        st.caption(label)
    if value is None or value == "":
        st.text(NO_DATA)
        return
    st.json(value, expanded=False)


def status_badge(value: object) -> str:
    """A stored status, verbatim.

    A value outside the documented vocabulary is returned unchanged and
    annotated by the caller, never mapped onto a nearby member and never
    replaced with a default.
    """

    if value is None:
        return NO_DATA
    return str(value)


def unrecognized(value: object, vocabulary: Iterable[str]) -> str:
    """Mark a stored value that is not in a documented vocabulary."""

    text = status_badge(value)
    if text in set(vocabulary):
        return text
    return f"{text}  (unrecognized value; shown as stored)"


def not_implemented(what: str, *, detail: str | None = None) -> None:
    """State plainly that something does not exist in the core."""

    st.markdown(f"**{NOT_IMPLEMENTED}**: {what}")
    if detail:
        st.caption(detail)


def no_data(what: str) -> None:
    """State plainly that the core returned no rows."""

    st.markdown(f"**{NO_DATA}**: {what}")


def empty_or_table(
    records: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
    *,
    what: str,
    column_config: Mapping[str, Any] | None = None,
) -> None:
    """Render records, or say that there are none. Never renders a fake row."""

    if not records:
        no_data(what)
        return
    st.dataframe(
        rows(records, fields),
        hide_index=True,
        width="stretch",
        column_config=dict(column_config or {}),
    )


def denied(exc: BaseException) -> None:
    """Render a core refusal using only the text the core sanctions.

    ``AuthorizationError.external_message`` is the same string for every denial
    reason, which is deliberate: it is what stops a refused lookup from
    becoming a resource-existence oracle. The reason code is deliberately not
    rendered.
    """

    external = getattr(exc, "external_message", None)
    st.error(str(external) if isinstance(external, str) else "the request was refused")
    st.caption("Refusal reported by the ATLAS-X core. No detail is available to this surface.")


def section(title: str) -> None:
    st.subheader(title)


def definition_list(pairs: Sequence[tuple[str, object]]) -> None:
    """Render label/value pairs as a compact two-column table.

    Values are rendered as text. A definition list is heterogeneous by nature —
    the configuration panel alone mixes strings, integers, floats and a ``Path`` —
    and a single column cannot hold that mixture, so every value is stringified
    here rather than in each caller.
    """

    st.dataframe(
        [{"field": str(label), "value": _text(value)} for label, value in pairs],
        hide_index=True,
        width="stretch",
    )


def metrics_or_markers(
    tiles: Sequence[tuple[str, object, str]],
    *,
    not_implemented_tiles: Sequence[tuple[str, str]] = (),
) -> None:
    """Render available metrics, and name the ones that do not exist.

    Every available tile carries the core call it came from. Every unavailable
    tile is named rather than shown as zero, because a zero reads as a
    measurement and would be a fabricated result.
    """

    columns = st.columns(len(tiles)) if tiles else ()
    for column_widget, (label, value, source) in zip(columns, tiles, strict=True):
        column_widget.metric(label, str(value))
        column_widget.caption(source)

    if not_implemented_tiles:
        with st.expander("Not available in the core today"):
            for label, detail in not_implemented_tiles:
                st.markdown(f"- **{NOT_IMPLEMENTED}**: {label}")
                if detail:
                    st.caption(detail)

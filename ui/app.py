"""ATLAS-X research workspace - Streamlit entry point.

Run it bound to loopback only:

    streamlit run ui/app.py --server.address 127.0.0.1 --server.port 8501

There is no ``0.0.0.0`` bind anywhere in this surface. The core is
owner-scoped and session-authenticated, and this UI is a local research
instrument, so it is reachable from this machine and nowhere else.

The surface is read-only. It has no write path to any record: no task creation,
no lifecycle action, no permission change, no provenance edit. Every value it
shows came back from a core service call made with the session token.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402

from atlas.auth.service import (  # noqa: E402
    AuthenticationFailed,
    AuthError,
    LoginLockedError,
    PasswordRejected,
    UsernameAlreadyExists,
    UsernameRejected,
)
from ui.presentation import not_implemented  # noqa: E402
from ui.runtime import (  # noqa: E402
    PAGE_KEY,
    Workspace,
    current_token,
    sign_in,
    sign_out,
    workspace,
)
from ui.views import dashboard, inspector, security, tasks, tools  # noqa: E402

#: The five destinations, in navigation order. Flat and always visible: no nested
#: tree and no wizard, so "where am I and what is real" is answerable at a glance.
PAGES: tuple[tuple[str, Callable[[Workspace], None]], ...] = (
    ("Home / Dashboard", dashboard.render),
    ("System Inspector", inspector.render),
    ("Tools", tools.render),
    ("Tasks", tasks.render),
    ("Security & Provenance", security.render),
)


def render_login(services: Workspace) -> None:
    """Log in through the core and keep the token server-side."""

    st.title("Sign in")
    st.caption(
        "The token is returned by the core once and held in server-side session state "
        "only. It is never written into the page, a URL, or a client-side store."
    )

    with st.form("atlasx_login", clear_on_submit=False):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in")

    if not submitted:
        return

    if not username or not password:
        st.error("Enter a username and a password.")
        return

    try:
        sign_in(services, username, password)
    except LoginLockedError as exc:
        # Deliberately not merged into the generic branch below: a lockout and a
        # wrong password are different outcomes and must not look alike. Both of
        # these messages are the core's own external wording, so they are shown
        # verbatim rather than rewritten here.
        st.error(f"Sign-in refused: {exc}")
    except AuthenticationFailed as exc:
        st.error(f"Sign-in refused: {exc}")
    except Exception:  # noqa: BLE001 - never let a core traceback vanish
        # Everything else gets a fixed sentence. The exception type and text
        # describe the implementation, not the person signing in, so neither
        # crosses into the browser.
        st.error("Sign-in failed. Please try again.")
    else:
        # Re-run so main() re-reads the token and renders the authenticated
        # surface instead of the sign-in form it just submitted.
        st.rerun()


def render_register(services: Workspace) -> None:
    with st.expander("Create an account"):
        st.caption("Registration is a core operation and applies the core's own rules.")
        with st.form("atlasx_register", clear_on_submit=False):
            # The rules are stated, not enforced here: what a name or password may
            # contain is the core's decision, and this surface only reports it.
            st.caption("Choose a username, 5-32 characters.")
            username = st.text_input("New username", key="register_username")
            st.caption("Minimum 5 characters.")
            password = st.text_input(
                "New password", type="password", key="register_password"
            )
            submitted = st.form_submit_button("Register")

        if not submitted:
            return
        if not username or not password:
            st.error("Enter a username and a password.")
            return
        try:
            services.auth.register(username=username, password=password)
        except (UsernameRejected, PasswordRejected, UsernameAlreadyExists) as exc:
            # These three are the core telling the person what to change, and
            # their wording is written for exactly this. It is rendered as is
            # rather than reworded or second-guessed here.
            st.error(str(exc))
        except AuthError:
            st.error("Registration failed. Please try again.")
        except Exception:  # noqa: BLE001
            # Same reasoning as sign-in above: no exception type, no internal text.
            st.error("Registration failed. Please try again.")
        else:
            st.success("Account created. Sign in with it above.")


def render_sidebar(services: Workspace) -> None:
    st.sidebar.title("ATLAS-X")
    st.sidebar.caption("Research workspace")

    labels = [label for label, _ in PAGES]
    st.sidebar.radio(
        "Destination",
        labels,
        index=labels.index(st.session_state.get(PAGE_KEY, labels[0]))
        if st.session_state.get(PAGE_KEY, labels[0]) in labels
        else 0,
        key=PAGE_KEY,
    )

    st.sidebar.divider()
    if st.sidebar.button("Refresh", width="stretch"):
        st.rerun()
    if st.sidebar.button("Sign out", width="stretch"):
        sign_out(services)
        st.rerun()


def render_gaps_note() -> None:
    with st.expander("What this surface does not do"):
        not_implemented(
            "Writing. There is no create, retry, cancel, grant, or edit control here.",
            detail="Every value shown is read from the core through a service call.",
        )
        not_implemented(
            "A provenance chain integrity verdict.",
            detail="No session-token surface exposes the storage-level chain verifier.",
        )
        not_implemented(
            "Artifact content.",
            detail="Content is recorded by the core but never served by it.",
        )


def main() -> None:
    st.set_page_config(
        page_title="ATLAS-X",
        page_icon=":shield:",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    services = workspace()
    identity = services.identity(current_token())

    if identity is None:
        render_login(services)
        render_register(services)
        return

    render_sidebar(services)
    selected = st.session_state.get(PAGE_KEY, PAGES[0][0])
    for label, render_page in PAGES:
        if label == selected:
            render_page(services)
            break

    st.divider()
    st.caption(
        f"Signed in as {identity.username} (user_id {identity.user_id}). "
        f"Session expires {identity.expires_at}."
    )
    render_gaps_note()


main()

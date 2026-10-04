"""Process-wide wiring between the Streamlit surface and the ATLAS-X core.

Every service used by the workspace is constructed here, once, from the same
public entry points the CLI and the test suite use. Nothing in this module
reaches past a service: no SQL, no repository call, no ``Database.transaction``,
and no tool body. A view that wants a fact asks a service for it.

Three rules are load-bearing here and are the reason this file exists at all:

* **No direct database access.** ``Database`` is constructed only so that the
  services can be built. Every read and every write in the workspace goes
  through a service method that takes a session token, because those are the
  methods that apply the owner predicate.
* **No bypass of authentication or authorization.** ``Workspace.identity()``
  re-validates the session on every call through
  ``AuthorizationService.authenticate``, so a stale or revoked token denies on
  the next render instead of being trusted from a cached decision.
* **No invented data.** ``sandbox_health`` and friends return exactly what the
  core returned. When a core has nothing to say, the views say "No data
  available"; this module never substitutes a placeholder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import streamlit as st

from atlas.artifact.service import ArtifactService
from atlas.auth.service import AuthService
from atlas.config.settings import Settings
from atlas.sandbox.supervisor import SandboxSupervisor, configuration_from_settings
from atlas.security.identity import Identity
from atlas.security.service import AuthorizationService
from atlas.storage.db import Database
from atlas.storage.tool_grants import ToolGrantRepo
from atlas.tools.registry import ToolRegistry, default_registry
from atlas.verifier.rules import RuleRegistry
from atlas.verifier.service import VerifierService

#: Key under which the raw session token is kept. It lives in Streamlit's
#: server-side session state only: never in the browser, never in a query
#: string, never in a client-side store.
TOKEN_KEY = "atlasx.session_token"

#: Key under which the rendered destination is remembered between reruns.
PAGE_KEY = "atlasx.page"


@dataclass(frozen=True)
class Workspace:
    """The core services the workspace reads through, and nothing else."""

    settings: Settings
    authorization: AuthorizationService
    auth: AuthService
    grants: ToolGrantRepo
    registry: ToolRegistry
    artifacts: ArtifactService
    verifier: VerifierService
    rules: RuleRegistry
    sandbox: SandboxSupervisor

    @property
    def environment(self) -> str:
        return self.settings.environment

    def identity(self, token: object) -> Identity | None:
        """The verified caller, or ``None`` when the core refuses the token.

        ``None`` is returned rather than an exception so that a view can render
        a logged-out state. A refusal reason is never surfaced to the browser:
        ``atlas.security.errors.AuthorizationError.external_message`` is the
        only text the core sanctions crossing that boundary.
        """

        try:
            return self.authorization.authenticate(token)
        except Exception:
            return None


@st.cache_resource(show_spinner=False)
def workspace() -> Workspace:
    """Build the core services once per server process.

    ``st.cache_resource`` is the right scope: these objects hold no per-user
    state. The session token lives in session state and is passed to every
    service call, so two browsers never share an identity.
    """

    settings = Settings.from_environ()

    # Constructed for the services to hold. The workspace itself never calls a
    # method on it; see the module docstring.
    database = Database(settings.database_path)
    database.initialize()

    auth = AuthService(database, settings)
    auth.bootstrap()

    grants = ToolGrantRepo(database, registry_ready=True)
    authorization = AuthorizationService(database, auth, tool_grants=grants)
    registry = default_registry()

    verifier = VerifierService(authorization)
    return Workspace(
        settings=settings,
        authorization=authorization,
        auth=auth,
        grants=grants,
        registry=registry,
        artifacts=ArtifactService(authorization),
        verifier=verifier,
        rules=verifier.rules,
        sandbox=SandboxSupervisor(configuration_from_settings(settings)),
    )


def current_token() -> object:
    """The raw session token for this browser session, or a non-string."""

    return st.session_state.get(TOKEN_KEY, "")


def sign_in(workspace_services: Workspace, username: str, password: str) -> dict[str, Any]:
    """Authenticate through the core and keep the token server-side.

    The core returns the raw token exactly once. It is stored here and nowhere
    else. No core error is rewritten: the caller renders whatever the core
    raised, so a lockout cannot be presented as an ordinary bad password.
    """

    result = workspace_services.auth.login(username=username, password=password)
    st.session_state[TOKEN_KEY] = result["token"]
    return result


def sign_out(workspace_services: Workspace) -> None:
    """Revoke the session in the core, then forget the token locally."""

    token = current_token()
    if isinstance(token, str) and token:
        workspace_services.auth.logout(token)
    st.session_state.pop(TOKEN_KEY, None)


def effective_configuration(services: Workspace) -> Mapping[str, Any]:
    """The secret-safe configuration projection.

    ``Settings.safe_dump()`` is the only sanctioned configuration projection and
    it excludes ``application_secret_key``. The workspace does not re-implement
    field filtering.
    """

    return services.settings.safe_dump()

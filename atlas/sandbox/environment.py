"""The exact environment a sandboxed tool body can see.

The rule this module exists to make enforceable is that a tool body inherits
nothing. Not ``PATH`` from the launcher, not ``HOME``, not
``application_secret_key``, not a proxy variable, not whatever a developer left in
their shell. The environment is built here, from constants, and every name in it
is listed in the policy, so the set of variables a tool can read is a value that
can be asserted in a test rather than a consequence of how the process was
started.

That matters more than it looks. Environment variables are the most commonly
forgotten way a secret reaches a subprocess: a launcher started from an
interactive shell has whatever that shell exported, and "we only pass what the
tool needs" is a claim that is very hard to keep true by hand across five tools
and a future sixth. Here the list is closed. :data:`FIXED_NAMES` is the whole
allowlist, :func:`build_environment` refuses anything outside it, and the
workspace-related names are the only ones whose values vary per invocation.

Two defaults are worth calling out because they are policy, not convenience:

* ``PYTHONPATH`` points at the installed payload directory and nothing else, so
  the guest cannot import a module from a directory that merely happens to be in
  the path.
* ``PYTHONHASHSEED=0`` because tools that declare themselves deterministic must
  be deterministic, and Python's per-process string hash seed is one of the ways
  they otherwise would not be.
"""

from __future__ import annotations

import os
from typing import Final, Iterable, Mapping, Sequence

__all__ = [
    "ENVIRONMENT_NAMES",
    "FIXED_VALUES",
    "SECRET_LIKE",
    "VARIABLE_NAMES",
    "as_mapping",
    "build_environment",
    "environment_names",
]

#: Where the guest payload lives, and therefore what ``PYTHONPATH`` may be.
PAYLOAD_DIR: Final = "/opt/atlasx/lib"

#: Variables whose value is fixed for every invocation.
FIXED_VALUES: Final[Mapping[str, str]] = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "TMPDIR": "/tmp",
    "PYTHONPATH": PAYLOAD_DIR,
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "HOME": "/workspace/tmp",
}

#: Variables whose value is derived from the invocation.
VARIABLE_NAMES: Final[tuple[str, ...]] = (
    "ATLASX_WORKSPACE",
    "ATLASX_INPUT",
    "ATLASX_OUTPUT",
    "ATLASX_TMP",
    "ATLASX_TOOL_ID",
    "ATLASX_EXECUTION_ID",
)

#: The complete allowlist. Anything not here does not reach the worker.
ENVIRONMENT_NAMES: Final[tuple[str, ...]] = (
    *FIXED_VALUES,
    *VARIABLE_NAMES,
)

#: Names refused even if a caller names them explicitly. The allowlist already
#: excludes them, so this is a second, independent refusal for the case where
#: somebody widens the allowlist later without noticing. The list is
#: prefix-and-exact rather than a substring test so that a legitimate future
#: variable like ``ATLASX_TOOL_ID`` is not caught by ``ATLAS`` appearing in it.
SECRET_LIKE: Final[tuple[str, ...]] = (
    "ATLAS_APPLICATION_SECRET_KEY",
    "APPLICATION_SECRET_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AZURE_CLIENT_SECRET",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "OPENAI_API_KEY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSH_AUTH_SOCK",
    "GIT_ASKPASS",
    "DOCKER_HOST",
    "KUBECONFIG",
)


def environment_names() -> tuple[str, ...]:
    """Every environment name a sandboxed process may see."""

    return ENVIRONMENT_NAMES


def _refuse(name: str) -> None:
    if name in SECRET_LIKE:
        raise ValueError(
            f"environment variable {name!r} is secret-bearing and is never passed "
            "to a sandboxed tool body"
        )
    if name not in ENVIRONMENT_NAMES:
        raise ValueError(
            f"environment variable {name!r} is not in the sandbox allowlist; add it "
            "to atlas.sandbox.environment deliberately or do not pass it"
        )


def build_environment(
    *,
    workspace: str,
    tool_id: str,
    execution_id: str,
    extra: Iterable[tuple[str, str]] = (),
) -> tuple[tuple[str, str], ...]:
    """Build the worker's complete environment as an ordered tuple of pairs.

    The host environment is not consulted at all, and there is no parameter that
    would let a caller pass one. That is the guarantee: adding a way to forward
    ambient variables would be a change to this function, visible in review,
    rather than a default that quietly widens with every new platform.
    """

    for name, _ in extra:
        _refuse(name)

    values: dict[str, str] = dict(FIXED_VALUES)
    values.update(
        {
            "ATLASX_WORKSPACE": workspace,
            "ATLASX_INPUT": os.path.join(workspace, "input"),
            "ATLASX_OUTPUT": os.path.join(workspace, "output"),
            "ATLASX_TMP": os.path.join(workspace, "tmp"),
            "ATLASX_TOOL_ID": tool_id,
            "ATLASX_EXECUTION_ID": execution_id,
        }
    )
    for name, value in extra:
        _refuse(name)
        values[name] = value

    if not values.keys() <= set(ENVIRONMENT_NAMES):
        unexpected = sorted(values.keys() - set(ENVIRONMENT_NAMES))
        raise ValueError(f"environment names outside the allowlist: {unexpected!r}")
    return tuple(sorted(values.items()))


def as_mapping(
    pairs: Sequence[tuple[str, str]],
) -> Mapping[str, str]:
    """The same environment as a mapping, for assertions and for logging.

    Values are the ones actually used, so a test can compare this against the
    allowlist without re-deriving the policy.
    """

    return dict(pairs)

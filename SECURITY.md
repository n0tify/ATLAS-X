# ATLAS-X Security

This document records the security posture of ATLAS-X. It is a living document,
updated per phase. Authentication (Phase 7) and authorization (Phase 8) are
implemented and documented below. Two other documents are authoritative and
override this one where they overlap: `docs/THREAT_MODEL.md` enumerates every
threat, control, and required negative test, and `docs/AUTHORIZATION_REVIEW.md`
records exactly what the authorization layer does and does not establish.

## Authentication design

- **Password storage:** Argon2id via `argon2-cffi` (`argon2.PasswordHasher`)
  with library defaults. Plaintext passwords are never stored and never logged.
- **Sessions:** opaque tokens generated with `secrets.token_urlsafe(32)`. Only
  the SHA-256 digest of a token is stored in SQLite. Raw tokens exist in memory
  and are returned once at login.
- **Expiry:** sessions carry an explicit `expires_at` (UTC ISO-8601) and are
  validated against it on every use; expired sessions are purged lazily.
- **Cookie guidance:** when a web layer is added, cookies must be `HttpOnly`,
  `SameSite=Lax`, `Path=/`, and `Secure` when HTTPS is available (localhost
  over plain HTTP is accepted only for local single-user development).
- **Rate limiting / lockout:** per-account consecutive-failure tracking with a
  temporary lockout window after `ATLAS_AUTH_MAX_LOGIN_ATTEMPTS` failures, plus
  a small constant delay on every failed authentication attempt to blunt
  username-enumeration timing. Successful login resets the counter.
- **Error behavior:** login failure raises a single generic error regardless of
  whether the account exists.
- **Password change:** re-verifies the old password, stores a fresh hash, and
  revokes all existing sessions for that user.

## Authorization design (Phase 8)

`atlas/security/` holds a deny-by-default authorization layer.
`AuthorizationService` is the single enforcement boundary, and no public method
accepts a caller-supplied `user_id`, so the actor is always derived from a
validated session token.

- **Model:** identity, resource ownership, operation permission, and tool
  permission. There are no roles and no elevation path — ownership is the only
  grant, and `tasks.user_id` cannot be reassigned by any repository.
- **Boundary:** `atlas.security.service.AuthorizationService`. Repositories scope
  rows to an owner; the service decides and raises. Every task-descendant read
  in `atlas/storage/owned_resources.py` carries an owner predicate, and the
  repository exposes no unscoped read.
- **Identity binding:** the actor comes from
  `IdentityResolver.from_session_token`, which delegates expiry and revocation
  to `AuthService.validate_session`. Authentication is a prerequisite for
  authorization and is never treated as permission.
- **Deny by default:** an operation absent from `PERMITTED_OPERATIONS` is
  denied, including operations that exist in the `Operation` enum but are granted
  nowhere. Unknown resource, unknown operation, malformed id, missing identity,
  and unexpected dependency errors all deny.
- **Failure behavior:** every failure raises an `AuthorizationError` subclass
  whose message is always `access denied`, so a caller cannot distinguish
  "not yours" from "does not exist" and cannot use the error as a
  resource-existence oracle. The internal reason code is available for
  diagnostics and is never part of the message.
- **Tool permissions:** `decide_tool_invocation` and
  `require_tool_invocation` answer whether a capability may be invoked and stop
  there. Arbitrary shell, subprocess, Python eval, filesystem, and network
  capability names can never be granted. A tool whose definition requires the
  sandbox, filesystem access, network access, or non-determinism is refused at
  registration, so it cannot be granted either.
- **Not filesystem authorization:** owning a row authorizes no host path, and
  this layer performs no path validation.
- **Known gaps:** `evaluation_runs` has no owner and is denied by name;
  provenance events with no task and no execution are denied to everyone; and
  `AuthService.change_password` is still not bound to a session principal. See
  `docs/AUTHORIZATION_REVIEW.md` §9.

## Tool registry and dispatch (Phase 9)

A capability becomes invokable only through `ToolDispatcher.dispatch`, and the
order inside it is the security property: authenticate, resolve the tool, then
`require_tool_invocation` **before** any input is validated or any implementation
runs. Validating first would let a caller without the grant learn a tool's field
names, bounds, and error phrasing by comparing failures.

- **The registry describes; authorization grants.** Being registered is not
  permission. The registry holds no authorization state, and a tool declaring
  that it is fine is not a substitute for the policy decision.
- **The tool set is code, not data.** Five built-in tools, defined in
  `atlas/tools/builtin/` and frozen at startup. There is no unregister, no
  reload, no request-reachable registration path, and no resolution from a
  caller-supplied string to an implementation. A tool id is a single lowercase
  `snake_case` segment, so it cannot be read as a module path, a file path, or a
  command.
- **No grant means no invocation.** `tool_permissions` holds explicit, scoped,
  revocable rows; the absence of a row is the denial. Reads are owner-scoped in
  SQL, a stored scope outside the `NULL` / `task:<id>` vocabulary is dropped
  rather than repaired, and no grant row holds a secret. Writing a grant is an
  operator action and is not reachable from any session path.
- **Nothing unbounded reaches a tool body.** Every numeric, string, and array
  field must declare its bounds at schema-construction time; input and output
  byte bounds and a per-task call budget are enforced around each call. The call
  budget is counted from the audit log, so restarting the process does not reset
  it.
- **Failures are classified, never swallowed.** An authorization denial raises
  `AuthorizationError` and is never converted into a tool error, so a caller can
  fail closed on the first. A tool that raises, returns something its own output
  schema forbids, or exceeds a bound fails the invocation; output is never
  truncated, because a truncated number is worse than a visible failure.
- **Tool bodies cannot widen their own access.** An implementation receives an
  owner-scoped, read-only snapshot rather than a database connection, so it cannot
  run arbitrary SQL or read another user's rows. Since Phase 10B that snapshot is
  also the only data it can reach: it has no connection and no host path.
- **Provenance records every attempt.** `tool.invoked` is written after
  authorization and before the call; `tool.completed` records the outcome with
  SHA-256 input and output digests and no raw input. Digests identify which
  input ran, so a stored result and a recomputed result compare; nothing is
  signed, so this is not tamper evidence.

## Tool body isolation (Phase 10B)

A tool body is no longer a Python callable in the ATLAS-X process. It is a Linux
process inside the `Ubuntu-24.04` WSL2 distribution, in `bubblewrap` mount, PID,
network, IPC, UTS, user, and cgroup namespaces, with a cgroup v2 leaf. The Windows
supervisor is the only component that crosses the boundary, and it has no
in-process execution path.

- **U-1 network denial is structural.** `--unshare-net` gives the body a network
  namespace with no interfaces and no routes, so there is nothing to route
  through. Verified by attempted connection rather than by reading a flag:
  external addresses and both DNS paths fail with `ENETUNREACH`, and host
  loopback services such as Ollama on `127.0.0.1:11434` are refused with
  `ECONNREFUSED`.
- **U-2 filesystem confinement is structural.** `/workspace` is the only writable
  bind. `/mnt`, `/home`, `/root`, `/run`, `/srv`, and `/media` are asserted absent
  after the namespace is built, and climbing to `/` finds nothing mounted. The
  host project tree, the SQLite database, and any `.env` file live under `/mnt/c`
  and are therefore unreachable.
- **No capabilities, no inherited environment.** `--cap-drop ALL` with uid and gid
  65534, and `--clearenv` followed by a closed allowlist. The host environment is
  never read, so there is no parameter through which a secret could arrive.
- **WSL interop is disabled.** `/etc/wsl.conf` sets `[interop] enabled=false` and
  `appendWindowsPath=false`, so `WSL_INTEROP` is not published, executing
  `cmd.exe` fails, and no drive letter is on the guest's `PATH`.
- **Resources are kernel-enforced.** `memory.max`, `pids.max`, and `cpu.max` are
  written to a per-execution cgroup v2 leaf and read back for the record.
  Enforcement is shown behaviourally — a refused `fork`, a stopped
  over-allocation — because the cgroup filesystem is deliberately not mounted into
  the sandbox, so a body cannot read its own limits.
- **Termination is guaranteed by the wall clock, not by the memory cap.**
  `memory.max` bounds and reclaims; it does not guarantee a process ends. On
  timeout the launcher signals the process group and then the cgroup. Verified
  against a descendant that calls `setsid` to leave the signalled group and
  ignores `SIGTERM` and `SIGKILL`.
- **Fail-closed, with no fallback.** There is no "run it in-process if the guest
  is unavailable" branch. An unavailable guest raises `SandboxUnavailable` and the
  invocation fails. A fallback keyed on availability is a trusted bypass, and
  availability is exactly the condition that lapses.
- **A tool cannot opt out of confinement.** `requires_sandbox` defaults to `True`,
  so omitting it confines rather than exempts, and the dispatcher contains no
  branch that calls a body on the host. The Phase 09 assertion of
  `requires_sandbox is False` was inverted to `True` for every definition.
- **The guest is not trusted to grade itself.** Output is re-validated against the
  host's declared schema and re-bounded after it returns. A tool's own error
  classification crosses the boundary as a code rather than being flattened, and a
  crossed control is reported by the control that was crossed, which a tool cannot
  relabel as one of its own errors.
- **Known limits.** A body that exhausts its memory cap may be killed before it
  reports. Whether a body wrote anywhere *inside* its own workspace is not
  checked; the workspace is per-execution and discarded. Guest-kernel and
  `bubblewrap` escape are out of scope — both are trusted computing base. The
  supervisor remains unconfined, which is the standing A12.5 caveat.

## Guarantees and non-guarantees

ATLAS-X does **not** guarantee:

- Protection against a compromised host or an attacker with local admin rights.
  Everything runs on the operator's own machine; the OS file-permission model
  is the outer boundary for the SQLite database file.
- DDoS-grade rate limiting. The lockout is per-account and enforced in‑process;
  it resets on process restart.
- Multi-factor authentication, account recovery, or email-based identity.
- Security of code generated by the model *beyond the tool-execution path*.
  Tool bodies are confined as described above, but nothing confines code the model
  causes to run inside ATLAS-X itself.
- CSRF protection: no browser-facing web application exists yet; this must be
  addressed when the UI layer is introduced.
- Isolation from code that holds a database connection. Any component able to
  execute SQL directly can bypass every owner predicate. Python-level trust, not
  authorization, is the outer boundary inside the process.
- Complete log redaction at runtime: `SecretsRedactionFilter` exists but is not
  yet attached to application log handlers.
- Containment of a tool body from *code inside ATLAS-X*. `ToolDefinition.implementation`
  is still a plain Python attribute on the host side, so code that already holds a
  `ToolRegistry` can call a body in-process and skip both dispatch and the
  sandbox. The dispatcher has no such branch; the attribute is a leftover of the
  host-side representation. The guarantee is that every *dispatched request* is
  authorized and confined, not that trusted in-process code cannot bypass it.
- Interruption of a slow tool *by the host*. The host's own elapsed budget is
  checked after the call returns. The interruption that does stop a running body is
  the guest-side wall clock, which is the control that is tested.
- Tamper-evident provenance. Digests identify the input that ran, but events are
  neither signed nor chained, so an audit record can still be edited by code
  that holds the database.

## Standing rules

1. Never read or write outside the project directory.
2. Never log passwords, password hashes, raw session tokens, or the application
   secret key.
3. Never return password hashes in any API response.
4. Never construct SQL from user input (parameterized queries only).
5. Never download models automatically or at runtime.
6. Never authorize a request by a caller-supplied actor. Resolve the actor from
   the session token and pass the identity down.
7. Never decide authorization in the UI, a client, or a view function. The UI
   may hide what a user cannot do; the backend must refuse it regardless.
8. Never convert an authorization failure into an allow to keep a flow working.
   When uncertain, deny and report the gap.

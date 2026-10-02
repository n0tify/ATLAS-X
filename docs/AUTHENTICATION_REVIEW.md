# Authentication Review

Status: **Phase 07 review gate.** This is a review of the authentication that is
already implemented. No authentication redesign, authorization implementation,
role or permission model, tool permission, sandbox, planner, verifier, recovery
feature, package installation, model download, provider change, or application
code change was made by this phase. A later Phase 08 addendum is recorded in
§13; it changed nothing in this review.

The review inspected `atlas/auth/password.py`, `atlas/auth/sessions.py`,
`atlas/auth/service.py`, `tests/test_auth.py`, `atlas/config/settings.py`, the
storage/database and repository code, `atlas/security/logging.py`,
`tests/test_config.py`, `SECURITY.md`, `docs/SYSTEM_SPECIFICATION.md`,
`docs/THREAT_MODEL.md`, `docs/CONFIGURATION_REVIEW.md`, and
`docs/STORAGE_REVIEW.md`.

## 1. Authentication Architecture

ATLAS-X currently has a local Python authentication service. It has no browser
endpoint, Streamlit UI, HTTP API, cookie issuance, or external identity
provider. `atlas/cli.py` initializes the database and bootstraps the service; it
does not expose login as a network service.

The implemented flow is:

1. **Registration/user creation:** `AuthService.register()` accepts a username
   and password. It validates a username length of 3–32 characters and allows
   alphanumeric characters, `_`, and `-`; it requires a password of at least
   eight characters. It hashes the password, checks for an existing username,
   creates the user, records a `user.registered` provenance event, and returns
   only a public user projection (`atlas/auth/service.py:49-60`). The database
   schema stores the user ID, username, password hash, lockout state, and
   timestamps.
2. **Password submission:** `login()` receives a username and password as
   Python arguments. There is no HTTP request parser, form boundary, browser
   cookie layer, or external credential service in the inspected code.
3. **User lookup and lock state:** The service reads the user by parameterized
   username. If the user is absent, it applies the configured failure delay and
   raises `AuthenticationFailed("invalid username or password")`. If the account
   has a future `locked_until` value, it raises `LoginLockedError` before
   password verification (`atlas/auth/service.py:62-70`).
4. **Password verification:** For an unlocked existing user, the service calls
   `verify_password()` against the stored Argon2id hash. A false result
   increments the persisted failure counter, sets `locked_until` when the
   threshold is reached, applies the failure delay, and raises the same generic
   `AuthenticationFailed` message used for an unknown user
   (`atlas/auth/service.py:70-82`).
5. **Session creation:** A successful password verification resets the failure
   counter, generates an opaque token, calculates an absolute expiry from
   `auth_session_ttl_minutes`, stores only the token digest with the user ID,
   and returns the raw token together with a public user projection
   (`atlas/auth/service.py:83-95`).
6. **Session validation:** `validate_session()` hashes the submitted token,
   deletes expired and revoked session rows, looks up an unrevoked digest,
   checks the stored expiry, and returns the public user projection. It returns
   `None` for an invalid, revoked, or expired session
   (`atlas/auth/service.py:97-106`). The service establishes an authenticated
   identity; it does not decide whether that identity may access a particular
   resource or tool.
7. **Logout/session invalidation:** `logout()` hashes the supplied token and
   sets `revoked_at` for an active matching session. Repeating logout returns
   `False`; the row is removed later by session cleanup
   (`atlas/auth/service.py:108-110`, `atlas/storage/repositories.py:121-140`).
8. **Password change:** `change_password()` takes a user ID, verifies the
   current password, hashes and stores a new password, and revokes all active
   sessions for that user (`atlas/auth/service.py:112-124`). The method does
   not itself receive or validate a session token; the distinction between a
   service identity argument and an authenticated caller is an authorization
   prerequisite, not an implemented authorization control.
9. **Failed authentication handling:** Unknown users and incorrect passwords
   use the same outward exception text, while a locked account uses a distinct
   `LoginLockedError`. The counter and lockout timestamp are stored in SQLite.
   There is no global or IP-based rate limiter, registration rate limiter, or
   internet-scale identity service.

The storage layer uses parameterized SQL and foreign keys, and user deletion
cascades sessions. Those are persistence relationships, not authorization.

## 2. Password Security

**Hashing algorithm:** `atlas/auth/password.py` uses
`argon2.PasswordHasher`, whose default type is Argon2id. The application does
not implement custom cryptography. The project dependency declaration is
`argon2-cffi>=23.1,<25` in `pyproject.toml`.

**Cost parameters:** `PasswordHasher()` is constructed without explicit
`time_cost`, `memory_cost`, `parallelism`, hash length, or salt length. The
application therefore delegates those values to the installed
`argon2-cffi` defaults; exact numeric cost parameters are not specified in the
ATLAS-X source. This review does not recommend replacing Argon2id merely because
another algorithm is newer. It does identify dependency-version-dependent cost
and reproducibility as an item to document or test.

**Salt handling:** The application does not create, store, or rotate a separate
salt. `PasswordHasher.hash()` produces an encoded Argon2 hash using the
library's salt handling, and the encoded hash is stored as `password_hash`.
The test suite verifies that the stored value has the Argon2id prefix and does
not contain the plaintext password.

**Verification:** `verify_password()` delegates to the library and converts
`Argon2Error` into `False`. Malformed or invalid stored hashes therefore do not
produce a successful login. There is no explicit rehash-on-login check for a
future change in cost parameters.

**Password requirements and storage:** Registration and password change require
at least eight characters. There is no maximum length, normalization policy,
composition rule, breach check, or password-strength estimator. The normal
service path passes plaintext only in memory to the hashing/verification
library; `UserRepo.create()` receives the encoded hash. Plaintext passwords are
not intentionally written to SQLite.

**Plaintext in errors and logs:** The current authentication service contains no
logging calls, and its authentication errors do not include the submitted
password. `UsernameAlreadyExists` includes the username, not a password.
`verify_password()` suppresses Argon2 library errors. This is a current code
observation, not a guarantee for future logging or exception serialization.

**Timing:** An existing user's wrong password incurs an Argon2 verification cost
before the configured delay. An unknown user skips Argon2 verification and only
sleeps for `auth_failure_delay_seconds`. A locked account returns before either
delay. The delay is configurable from 0.0 to 10.0 seconds and defaults to 0.1;
it is not a constant-time or dummy-verification mechanism. No timing test
exists.

**Invalid credentials:** Unknown usernames and incorrect passwords produce the
same `AuthenticationFailed` type and text. Locked accounts produce a different
`LoginLockedError`, so the outward behavior is not uniform. Malformed runtime
types are not normalized at the service boundary; for example, a non-string
username or password can fail before the intended authentication error.

## 3. Session Security

**Identifier generation:** `generate_session_token()` calls
`secrets.token_urlsafe(32)`, producing a URL-safe token from 32 bytes of
cryptographically secure randomness. The test checks that the returned token is
at least 40 characters, but it does not measure entropy or test collision
behavior.

**Storage:** `hash_token()` computes a hexadecimal SHA-256 digest of the UTF-8
token. The raw token is returned once from `login()` and held transiently in
memory; the database stores the digest, user ID, timestamps, and revocation
state. The unique token-digest index and the user foreign key provide database
relationships. SHA-256 is used here as a lookup digest for a high-entropy
random token, not as a password hash; Argon2id remains the password verifier.

**Expiration:** `auth_session_ttl_minutes` defaults to 60 minutes and is
validated from 1 to 1,440 minutes. Expiry is absolute from successful login.
There is no idle timeout, sliding renewal, refresh token, or maximum session
count. `AuthService.validate_session()` checks expiry on every call.

**Logout and invalidation:** Logout marks the matching session revoked rather
than immediately deleting it. Password change revokes all active sessions for
the user. User deletion cascades session rows. Expired and revoked rows are
deleted lazily whenever `validate_session()` is called; there is no background
cleanup job.

**Rotation:** There is no session rotation on use, no rotation after
privilege-sensitive changes, and no session-family/reuse detection. A successful
login creates an additional session without invalidating other sessions. Logout
and password change are the available invalidation mechanisms.

**Cookie attributes:** `atlas/auth/sessions.py` defines guidance/helpers for
`HttpOnly`, `SameSite=Lax`, and `Path=/`, with `Secure` added when the caller
passes `secure=True`. No current UI or HTTP layer calls the helper or creates a
cookie. Therefore secure cookie deployment, cookie lifetime, domain policy,
CSRF behavior, and transport security are not implemented or verified here.
The documented local deployment accepts plaintext localhost HTTP only as a
single-user development posture; it does not provide transport protection.

**Token exposure risks:** The raw token is a credential and is deliberately
returned to the caller. The current service does not log it, and the existing
test checks that the test token does not appear in captured logs. There is no
browser, API, cookie, URL, or TLS boundary yet, so token exposure through those
surfaces remains untested. SQLite contains only the digest, but a process memory
dump, future debug logging, or a caller that logs the login result could expose
the raw token.

**Identity, session state, and authorization:** A valid session establishes an
authenticated user identity and active session state. It does not establish
roles, permissions, ownership of an arbitrary resource, tool access, or
administrator authority. Those are separate authorization decisions.

## 4. Brute-Force Protection

The implemented controls are per-account and persisted in the `users` table:

| Control | Implemented value or behavior |
|---|---|
| Failure threshold | `auth_max_login_attempts`, default 5, validated 1–50 |
| Lockout window | `auth_lockout_minutes`, default 15, validated 1–1,440 minutes |
| Failure delay | `auth_failure_delay_seconds`, default 0.1, validated 0–10 seconds; zero is allowed |
| Counter reset | Successful login resets `failed_login_attempts` and `locked_until` |
| Lockout trigger | The threshold is applied after an incorrect password; a locked account is rejected before password verification |
| Cleanup | Expired/revoked sessions are deleted lazily during session validation; failed-login state has no separate cleanup job |
| Scope | Per account only; no IP, device, global, or network rate limit |
| Persistence | The counter and `locked_until` are written to SQLite and survive a normal process restart as long as the database remains |

Repeated wrong-password attempts eventually produce `LoginLockedError`, even
when the correct password is subsequently supplied before the lock expires.
After the timestamp expires, a correct password can succeed and reset the
counter. There is no explicit administrator unlock operation.

The counter update is not atomic with the initial user read: `login()` reads
the user in one transaction, calculates `attempts`, and writes the new value in
a later transaction. Concurrent attempts can therefore overwrite one another
and fail to count every failure reliably. The existing test suite does not
exercise concurrent failures.

`SECURITY.md` states that lockout is in-process and resets on restart. The
actual repository stores both fields in SQLite, so that statement is not
accurate for the current code unless the database is removed or reset. This is
recorded as a documentation discrepancy; no documentation outside this review
was changed.

The delay is applied for unknown users and incorrect passwords, but not for the
already-locked branch. It is also configurable to zero. These behaviors provide
basic local abuse resistance, not internet-scale rate limiting.

## 5. User Enumeration

ATLAS-X has usernames, not email addresses. An unauthenticated caller may be
able to distinguish accounts through the following paths:

- **Unknown user versus incorrect password:** Both use the same
  `AuthenticationFailed` message and exception type, so the text does not
  distinguish them. The timing path is different: an existing user undergoes
  Argon2 verification before the delay, while an unknown user only sleeps. No
  timing test establishes that the difference is not observable.
- **Locked user:** A locked existing account raises the distinct
  `LoginLockedError("account temporarily locked")`, while an unknown user does
  not. This is an explicit observable distinction.
- **Registration collision:** Registering an existing username raises
  `UsernameAlreadyExists` and includes the submitted username. This reveals
  that the name is already registered. There is no registration rate limit or
  generic collision response.
- **Malformed input:** Invalid registration input raises validation messages
  distinct from login failures. The service does not define a single
  unauthenticated error contract for malformed usernames, passwords, or token
  types.
- **Email enumeration:** Not applicable to the current schema; there is no
  email field or email-based recovery flow.

The existing test `test_login_unknown_user_same_generic_error` checks only the
unknown-user message. It does not compare exception types for every branch,
measure timing, test locked-account behavior, test registration collisions, or
test malformed input. Account enumeration is therefore reduced for one text
path but not comprehensively mitigated.

## 6. Secret Handling

**Passwords:** The normal path hashes a password before `UserRepo.create()` and
stores only the Argon2id result. The public user projection contains `id`,
`username`, and `created_at`, not `password_hash`. `UserRepo.get_by_username()`
and `get_by_id()` do use `SELECT *` and return the full internal row to callers;
they are used for authentication operations and are not safe generic response
projections. The storage review records this data-minimization risk.

**Session tokens:** The raw token is returned by `login()` but only its SHA-256
digest is written to the database. The test verifies that the raw token is not
stored in `token_hash` rows. A future API, UI, logger, exception handler, or
debug traceback could still expose the returned token; no such future path
exists yet.

**Logs and debug output:** The current auth service does not log passwords,
hashes, or tokens. `test_no_auth_secrets_in_logs` captures the test logger and
checks that the test credential, Argon2 marker, and token are absent. This is
useful evidence for the current path, but it does not prove that a runtime
redaction filter is active.

`SecretsRedactionFilter` exists in `atlas/security/logging.py` and is manually
attached in `tests/test_config.py`. The Phase 05 finding remains: no application
logging configuration wires the filter into ATLAS-X handlers. The filter's
presence must not be described as active runtime redaction. It also redacts
only values supplied to it; it cannot discover arbitrary secrets in structured
log records or exception objects.

**Exceptions and responses:** Current authentication exceptions contain generic
messages or a username/lockout reason, not submitted passwords. `LoginLocked`
and duplicate-registration messages are not secret-bearing, but they are
identity signals as described in Section 5. There is no API response serializer
in the inspected code, so response redaction cannot be verified beyond the
service return dictionaries.

**Configuration dumps:** `Settings.safe_dump()` excludes
`application_secret_key`, and the configuration tests cover that behavior. The
application secret is not used by the current authentication service and must
not be described as a session-signing or encryption key. `secret_values()`
returns configured secret values to the caller by design; it is not a logging
path, but callers must not print its result.

**Database and test output:** Password hashes and token digests are stored in
SQLite, whose at-rest protection is the host OS account. The test source
contains synthetic credentials for testing, but this review does not reproduce
them. No encryption, secure deletion, or application-level database redaction is
implemented.

## 7. Authentication vs Authorization Boundary

Successful authentication currently establishes:

- that the submitted password was verified for a user, or
- that a supplied opaque token matches an unrevoked, unexpired session row, and
- the associated user ID and public identity projection for that session.

It does **not** establish:

- that the caller may read or modify a particular task, artifact, execution, or
  evaluation record;
- that the caller has a role, permission, grant, or administrator status;
- that the caller may invoke a tool or execute generated code;
- that a resource ID supplied by the caller is owned by the authenticated user;
- that a filesystem path is safe or that a sandbox boundary exists.

The mandatory boundary statement is:

> Successful authentication establishes identity/session state; it does not
> grant permission to access arbitrary resources or tools.

`TaskRepo` includes `user_id` predicates for a few task operations, but that is
repository-level ownership filtering, not a complete authorization layer.
`AuthService.change_password()` accepts a `user_id` directly and does not
validate a session itself. Phase 08 must bind the authenticated principal to
authorization decisions and must not trust a caller-selected user ID as proof
of permission. No authorization is implemented by this review.

## 8. Threat Model Coverage

The following mapping uses the threats in `docs/THREAT_MODEL.md` that intersect
the authentication boundary.

| Threat | Existing control | Evidence | Residual risk | Missing test or control |
|---|---|---|---|---|
| A1 Unauthorized access / authentication bypass | Argon2id password verification, opaque random sessions, expiry, revocation, generic invalid-credential message, lockout | `password.py`, `sessions.py`, `AuthService.login/validate_session`, auth tests | No authorization or browser boundary; lockout/timing and future caller misuse remain; no direct bypass was found in the current service | Add tests for malformed tokens, empty/non-string inputs, every failure branch, concurrent validation, and a protected-resource gate before Phase 08 |
| A2 Session theft / session compromise | 32-byte secure random token, digest at rest, raw token returned once, logout and password-change revocation | `sessions.py:15-20`, `service.py:83-110`, token/log tests | Token can be replayed until absolute expiry; no rotation, idle timeout, transport, cookie, or UI tests | Define rotation/revocation policy; implement secure cookie/transport boundary before browser exposure; add theft/replay tests |
| A3 Broken object-level authorization | Task reads/deletes include owner predicates | `repositories.py:156-179`, cross-user task test | Only selected helpers are scoped; no central authorization or coverage for other resources | Phase 08 must authorize every resource/action and test cross-user reads, writes, deletes, and identifiers |
| A4 Privilege escalation | No roles or permissions exist; this is explicitly unimplemented | `docs/ARCHITECTURE_RECONCILIATION.md`, current package inventory | High residual risk if authentication is treated as permission | Implement deny-by-default authorization in Phase 08 with negative escalation tests |
| A5 Credential leakage | Argon2id hashes, no plaintext in normal storage, public projection, no current auth logging | `password.py`, `UserRepo.get_public`, auth tests | SQLite is plaintext at the host boundary; internal `SELECT *` helpers and future logs can expose hashes | Keep safe projections, add database/error/log integration tests, and define at-rest/backup handling |
| A6 User enumeration | Same invalid-credential text for unknown user and wrong password; delay setting | `service.py:62-82`, unknown-user test | Locked-account error, registration collision, and timing differences remain distinguishable | Make outward behavior uniform where appropriate; test status, message, and timing; rate-limit or reconsider public registration |
| A7 Replay of privileged operations | Session digest and provenance are available as design elements | `sessions.py`, `provenance_events` schema | No session rotation or execution-level replay guard exists; privileged operations are not implemented | Define session/execution replay policy before tool execution; add replay tests in the owning later phase |
| D2/D3 Secret disclosure and unsafe logging | Redaction filter exists and auth currently emits no logs; auth log test | `atlas/security/logging.py`, `tests/test_config.py`, `test_no_auth_secrets_in_logs` | Filter is not wired into application logging; future structured logs could bypass supplied-secret matching | Wire the filter to runtime handlers, prohibit secret-bearing fields, and add end-to-end logging tests before logging is introduced |

The threat model calls authorization, sandboxing, and several replay controls
planned. This review does not promote those planned controls to implemented
ones.

## 9. Test Coverage

`tests/test_auth.py` contains 18 test functions. The actual coverage is:

- **Registration:** public response omits `password_hash`; duplicate username
  rejection; short-password rejection.
- **Password storage and verification:** successful login, wrong password,
  unknown-user generic message, Argon2id prefix, and absence of the test
  plaintext from the stored hash.
- **Sessions:** successful token creation, token length assertion, digest-only
  storage, round-trip validation, invalid token, manually expired session,
  logout revocation, repeated logout, and password-change revocation.
- **Lockout:** threshold behavior, rejection of the correct password while
  locked, and reset after a successful login.
- **Password change:** wrong current password rejection, old-password failure,
  new-password success, and revocation of an existing session.
- **Cross-user behavior:** two users receive distinct session identities and
  `TaskRepo` prevents one user from reading the other's task. This does not test
  authorization for all resources.
- **Logging:** captured logs do not contain the test password, Argon2 marker,
  or test token.

The following requested areas are not directly covered:

- actual failure-delay duration or a timing-resistance test;
- locked-user versus unknown-user enumeration;
- duplicate-registration enumeration or registration throttling;
- malformed usernames, passwords, tokens, IDs, and non-string inputs;
- max password length, Unicode normalization, or case/identity normalization;
- cookie attributes and actual cookie creation;
- idle timeout, sliding renewal, session rotation, maximum sessions, or replay;
- direct `SessionRepo` expiry semantics and independent cleanup;
- concurrent failed logins or concurrent session operations;
- process restart persistence of lockout state;
- malformed stored timestamps/hashes and database recovery;
- end-to-end runtime wiring of `SecretsRedactionFilter`;
- exception/traceback redaction and safe handling of raw login responses.

The storage tests provide supporting foreign-key, transaction, ownership, and
concurrency baseline coverage, but they are not authentication tests.

## 10. Findings

**CRITICAL**

No CRITICAL finding is identified in the current local authentication service.
This is not a security clearance: there is no browser/API exposure yet, and the
absence of a protected-resource boundary limits the current attack surface.

**HIGH**

| ID | Evidence | Affected component | Security impact | Likelihood | Required control | Blocks Phase 08? | Proposed future phase |
|---|---|---|---|---|---|---|---|
| H-01 | `AuthService` establishes identity only; no authorization package, roles, permissions, or central policy exists; only selected `TaskRepo` methods add owner predicates | Authentication/storage boundary | A caller or future endpoint could mistake login for access to arbitrary tasks, artifacts, or tools, creating BOLA/privilege risk | High once a protected surface is exposed; no such surface exists currently | Derive the principal from a validated session, implement deny-by-default authorization, check ownership/permission before every resource action, and add cross-user negative tests | Yes; this is the Phase 08 security gate and must precede any protected-resource exposure | Phase 08 |
| H-02 | `SecretsRedactionFilter` is defined and manually tested, but no application logger/handler attaches it; the auth service currently has no logging calls | Secret/logging boundary | Future auth events, structured exceptions, or UI logs could expose passwords, hashes, or raw tokens; current exposure is latent | Low now, medium/high after logging or UI integration | Wire redaction into runtime handlers, prohibit credential fields in records, and add end-to-end secret-leak tests | No for starting the design; yes before any secret-bearing auth logging or browser response | Phase 08 prerequisite, completed with observability work in Phase 14 |

**MEDIUM**

| ID | Evidence | Affected component | Security impact | Likelihood | Required control | Blocks Phase 08? | Proposed future phase |
|---|---|---|---|---|---|---|---|
| M-01 | Locked users receive `LoginLockedError` before password verification and without the failure delay; unknown and wrong-password paths have different timing | Login error/timing path | Attackers can distinguish locked accounts and may discover valid usernames; timing can also reveal account existence | Medium | Use a uniform outward failure contract, add a deliberate delay/dummy verification policy where appropriate, and test status/message/timing | No, but should be resolved before exposing login publicly | Phase 07 follow-up |
| M-02 | Duplicate registration raises `UsernameAlreadyExists` with the submitted username; no registration rate limit exists | Registration boundary | Username enumeration and automated account-name probing | Medium if registration is exposed; low for a strictly local operator-only tool | Decide whether registration is public, return a uniform result where appropriate, and rate-limit/limit registration attempts | No, but required before a public registration surface | Phase 07 follow-up / Phase 20 |
| M-03 | `login()` reads the counter in one transaction and writes a calculated value in another; the counter is persisted even though `SECURITY.md` says it resets on restart | Lockout state/concurrency | Concurrent failures can lose increments and weaken the threshold; documentation misstates persistence | Medium under concurrent attempts; documentation mismatch is immediate | Make the threshold update atomic/idempotent, test concurrent and restart behavior, and correct the security documentation | No, but must be resolved before relying on lockout as a security control | Phase 07 follow-up |
| M-04 | `SessionRepo.get_valid()` filters revocation but not `expires_at`; `AuthService.validate_session()` adds the expiry check separately; cleanup is lazy | Session repository/service contract | A future caller can accidentally accept an expired session or retain stale rows | Medium as new callers are added | Make expiry part of the session validation contract, define cleanup ownership, and test direct repository and boundary behavior | Yes; authorization must rely on a single fail-closed session invariant | Phase 07 follow-up |
| M-05 | `change_password()` accepts a caller-provided `user_id` and receives no session token or authenticated principal | Password-change service | A future endpoint could operate on a target selected by the caller without a separate authorization decision | Low now because no endpoint exists; medium when exposed | Bind password change to the validated session principal, authorize the target, and test unauthenticated/cross-user attempts | Yes for any exposed password-management surface | Phase 08 |
| M-06 | Raw token is returned once, but there is no rotation, idle timeout, transport, cookie issuance, or replay detection | Session lifecycle | A stolen token remains usable until absolute expiry unless separately revoked | Medium in a future browser/local-network deployment | Define rotation/revocation policy, use the secure cookie helper at the UI boundary, choose transport posture, and add replay/session tests | Yes for browser or network exposure; no current API exists | Phase 08 / Phase 20 |
| M-07 | `UserRepo.get_by_username()` and `get_by_id()` return `SELECT *` rows; only `get_public()` is restricted | User repository | An accidental future response or log could include password hashes and lockout state | Low with disciplined callers; medium as callers multiply | Separate credential lookup from public projection and test that no internal row is serialized/logged | No, but required before new API/UI surfaces | Phase 07 follow-up / Phase 14 |

**LOW**

| ID | Evidence | Affected component | Security impact | Likelihood | Required control | Blocks Phase 08? | Proposed future phase |
|---|---|---|---|---|---|---|---|
| L-01 | Password validation checks only a minimum of eight characters; no maximum, normalization, or malformed-type boundary exists | Registration/password change | Excessively large inputs can consume resources; alternate Unicode representations can create account ambiguity | Low for the current local service | Add bounded input validation and an explicit username/password normalization policy with tests | No | Phase 07 follow-up / Phase 20 |
| L-02 | No tests cover cookie attributes, direct session expiry, cleanup scheduling, concurrent login/session operations, restart persistence, or malformed input | Test suite | Regressions in session and lockout behavior may go undetected | Low now, increasing as surfaces are added | Add focused negative and concurrency tests before relying on these controls | No, but required before production exposure | Phase 19 with Phase 07 follow-up |
| L-03 | Only registration writes an auth-related provenance event; login, logout, lockout, and password-change events are not recorded | Audit/provenance | Incident reconstruction and abuse investigation are incomplete | Low for a single-user local research tool | Define an auth-event audit policy with redaction and bounded fields; do not log credentials | No | Phase 14 |

**INFORMATIONAL**

| ID | Evidence | Affected component | Security impact | Likelihood | Required control | Blocks Phase 08? | Proposed future phase |
|---|---|---|---|---|---|---|---|
| I-01 | Argon2id is a current, maintained password-hashing choice; numeric cost parameters are not explicit in ATLAS-X and dependency versions are ranged | Password hashing | Cost and performance can vary with the installed library version; this is not evidence that the algorithm is wrong | Low | Record the effective parameters/version in the security documentation and add compatibility tests; do not replace Argon2id without a concrete concern | No | Phase 07 follow-up / Phase 19 |
| I-02 | There is no browser, API, cookie, or transport layer in the inspected code | Deployment boundary | CSRF, cookie theft, and network interception are not current controls or current guarantees | Low now; changes when a web surface is added | Keep the boundary explicit and apply the cookie/transport policy before exposing protected resources | Yes for any web exposure, not for the current local service | Phase 20 |
| I-03 | No MFA, recovery, distributed rate limiting, or internet-scale identity provider is implemented | Scope boundary | ATLAS-X is intentionally a local research authentication service, not an internet identity system | Expected for the stated scope | Keep the limitation documented; do not market the service as multi-user or internet-scale | No | Documentation/UI phase |

## 11. Required Changes Before Authorization

These are conditions and design prerequisites, not changes made by this review:

1. Define an authenticated principal/session context produced only by successful
   session validation. Authorization must consume that server-derived identity,
   never trust a caller-supplied `user_id` as proof of permission.
2. Implement Phase 08 as a separate deny-by-default layer. Every task, plan,
   execution, artifact, verification, failure, recovery, provenance, and
   evaluation read/write/delete must check the action and resource owner before
   returning or changing data.
3. Make session validity fail closed at one boundary, including expiry,
   revocation, malformed token/type handling, and cleanup behavior. Do not let
   future callers use a repository method that can return an expired session.
4. Bind password change and any future account-management operation to the
   authenticated session and authorize the target user explicitly.
5. Resolve the locked-account and registration enumeration behavior before a
   public login/registration surface, or document a strictly operator-local
   deployment assumption. Add status, message, and timing tests.
6. Make lockout updates atomic and test concurrent attempts, expiry, successful
   reset, and restart behavior. Correct the inaccurate reset-on-restart claim in
   security documentation through an approved documentation-only change.
7. Decide the session rotation, idle/absolute timeout, revocation, and
   multi-session policy. Implement the secure cookie helper and transport
   posture before a browser or network boundary is introduced; do not imply
   that the helper alone is an active cookie control.
8. Wire `SecretsRedactionFilter` into runtime logging before any auth event,
   exception, or UI path can log credential-bearing data. Add end-to-end tests;
   the filter's unit test is not sufficient.
9. Preserve Argon2id unless a concrete compatibility or security concern is
   demonstrated. Document the effective library cost parameters and dependency
   version rather than silently relying on an unpinned default.
10. Add negative tests for missing, malformed, expired, revoked, and
    cross-user sessions before Phase 08 relies on the identity result. No
    authorization, tool, sandbox, planner, verifier, or recovery behavior is
    implemented by this review.

## 12. Verification Status

**What was inspected:** The authentication implementation and tests listed in
the opening paragraph, the relevant storage/database files, the redaction
filter and configuration tests, and the security/specification/threat-model/
configuration/storage review documents. `docs/AUTHENTICATION_REVIEW.md` did not
exist before this review and is the only file this phase is intended to create.

**Tests available in the repository:** `tests/test_auth.py` (18 test
functions), `tests/test_storage.py` (8 storage tests), `tests/test_config.py`
(9 configuration tests), and the shared fixtures in `tests/conftest.py`. The
project declares pytest, Ruff, and mypy as development dependencies.

**PATH invocation:** The active system interpreter could not run
`python -m pytest` because it reported `No module named pytest`; `ruff` and
`mypy` were not recognized on PATH. The alternate Python 3.11 and 3.13
interpreters also did not have pytest available.

**Existing project-local environment:** A pre-existing `.venv` was found in the
workspace. It already contained `pytest.exe`, `ruff.exe`, and `mypy.exe`; no
package installation or environment modification was performed. The commands
below were run through those existing executables, without activating or
changing the environment.

**Exact final results:** The project-local verification results are recorded
here after execution; no result is inferred from the earlier PATH failures:

- `.\.venv\Scripts\pytest.exe` — **36 passed in 9.71s**
- `.\.venv\Scripts\ruff.exe check .` — **All checks passed!**
- `.\.venv\Scripts\mypy.exe atlas` — **Success: no issues found in 23 source files**

These results come from the executions performed in this session using the
pre-existing project-local executables. They match the earlier historical
record (36 tests passed, Ruff clean, and mypy clean) and now serve as the
verified final results for this review.

Files modified by this phase: `docs/AUTHENTICATION_REVIEW.md` (created only).
No application code, schema, provider, package, or environment file was
modified. Phase 08 is not started.

---

## 13. Addendum — Phase 08 cross-reference (2026-10-01)

No finding, severity, status, or required control above was changed by Phase 08.
`atlas/auth/` was not modified by that phase. This section only records which
prerequisites in §11 are now satisfied, so the two reviews cannot drift.

| §11 prerequisite | Status after Phase 08 |
|---|---|
| 1 — server-derived identity, never a caller-supplied `user_id` | **Satisfied.** `IdentityResolver.from_session_token` produces the actor from `AuthService.validate_session`, and no public `AuthorizationService` method accepts a `user_id` |
| 2 — separate deny-by-default authorization layer | **Satisfied for storage-facing operations.** `AuthorizationService` covers task, plan, plan step, execution, artifact, verification, failure, recovery, and provenance. `evaluation_runs` is **denied by name** because it has no owner (AZ-01) |
| 3 — one fail-closed session boundary | **Partially satisfied at the boundary.** The authorization path fails closed on expiry, revocation, and malformed tokens, but `SessionRepo.get_valid()` still does not itself check `expires_at` (M-04 / AZ-04). The repository-level contract remains misleading |
| 4 — bind password change to the session principal | **Not satisfied, deliberately.** `AuthService.change_password` is unchanged (M-05 / AZ-03). No surface exposes password management, so nothing is exposed to bind yet |
| 5, 6, 7, 8, 9 — enumeration, lockout, session/transport, redaction wiring, Argon2id parameters | **Not addressed by Phase 08** and unchanged (M-01, M-02, M-03, M-06, L-01, L-03, I-01, I-02, H-02 / AZ-05) |
| 10 — negative tests for missing, malformed, expired, revoked, and cross-user sessions | **Satisfied.** `tests/test_authorization.py` covers missing, malformed, and expired tokens; revocation tests remain with Phase 07 |

Consequences for any future caller: a session-validation result is now the only
accepted entry to user-owned data, and every protected surface must be
re-registered against `AuthorizationService` rather than a repository. See
`docs/AUTHORIZATION_REVIEW.md` §10 for the standing obligations.


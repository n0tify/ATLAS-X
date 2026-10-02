# ATLAS-X UI Architecture and Interaction Specification

Status: **Phase 07.5 specification gate (documentation only).** This document
defines UI architecture, contracts, and interaction rules **before** any UI code
exists. No frontend code, package, dependency, configuration, schema, or
application behavior was created, installed, or changed by this phase.

**Nothing described here is implemented.** At the time of writing the repository
contains no UI of any kind: no Streamlit entry point, no HTTP API, no React or
TypeScript or Vite project, no `atlas/ui` package, and no JavaScript toolchain
configuration. Every screen, node, edge, animation, and data contract below is a
**specification for future phases**, written so that those phases cannot quietly
redefine security or data meaning.

## 0. How to read this document

### 0.1 Status labels

Every substantive statement in this document carries one of these labels. A
reader must never have to guess whether something exists.

| Label | Meaning |
|---|---|
| **IMPLEMENTED** | Present in the repository now, with a test or a directly inspectable file. Verified in this phase by reading the code. |
| **SCHEMA ONLY** | The table/column exists in `atlas/storage/migrations.py` (`SCHEMA_VERSION = 1`), but no code reads or writes it yet, and no value validation is attached to it. |
| **PLANNED** | Named as future work by `docs/SYSTEM_SPECIFICATION.md`, `docs/DECISIONS.md`, `docs/THREAT_MODEL.md`, or this document. No code. |
| **NOT IMPLEMENTED** | Explicitly out of scope, or recorded as a gap in an earlier review. Not to be assumed, stubbed, or simulated. |

### 0.2 Current verified state (source of truth for this document)

Inventory taken by reading the repository in this phase.

| Component | Label | Evidence |
|---|---|---|
| `atlas/config/settings.py` — Pydantic `Settings`, `ATLAS_` env prefix, `extra="forbid"`, fail-closed in production, `safe_dump()` excluding `application_secret_key` | IMPLEMENTED | file read |
| `atlas/storage/db.py` — `Database`, WAL, `PRAGMA foreign_keys=ON`, 5,000 ms busy timeout, transactional scope | IMPLEMENTED | file read; `docs/STORAGE_REVIEW.md` §1 |
| `atlas/storage/migrations.py` — `SCHEMA_VERSION = 1`, 13 tables, idempotent `init_db()` | IMPLEMENTED | file read |
| `atlas/storage/repositories.py` — `UserRepo`, `SessionRepo`, `TaskRepo`, `ProvenanceRepo` (4 of the planned repositories) | IMPLEMENTED | file read |
| `atlas/auth/password.py` — Argon2id via `argon2.PasswordHasher`, `validate_username` (3–32 chars) | IMPLEMENTED | file read |
| `atlas/auth/sessions.py` — `secrets.token_urlsafe(32)`, SHA-256 digest, `SESSION_COOKIE_ATTRIBUTES`, `cookie_attributes()` helper | IMPLEMENTED | file read |
| `atlas/auth/service.py` — `AuthService.register/login/validate_session/logout/change_password` | IMPLEMENTED | file read; `docs/AUTHENTICATION_REVIEW.md` §1 |
| `atlas/security/logging.py` — `SecretsRedactionFilter` | IMPLEMENTED, **not wired into any logger** | file read; `docs/CONFIGURATION_REVIEW.md` HIGH-1 |
| `atlas/util.py` — `utcnow_iso`, `add_minutes_iso`, `is_later_than` | IMPLEMENTED | file read |
| `atlas/cli.py` — `atlas-x` smoke command (settings, DB init, `AuthService.bootstrap()`) | IMPLEMENTED | file read |
| `atlas/planner/`, `executor/`, `verifier/`, `recovery/`, `tools/`, `sandbox/`, `provenance/`, `evaluation/` | **NOT IMPLEMENTED** — one-line docstrings only | files read |
| `plans`, `plan_steps`, `executions`, `artifacts`, `verifications`, `failures`, `recovery_attempts`, `provenance_events`, `evaluation_runs` tables | SCHEMA ONLY | `atlas/storage/migrations.py`; `docs/STORAGE_REVIEW.md` §2 |
| Authorization / roles / tool permissions | **NOT IMPLEMENTED** | `docs/ARCHITECTURE_RECONCILIATION.md` §2, §4 |
| Sandboxed execution, model integration, evaluation harness | **NOT IMPLEMENTED** | same |
| Any UI (Streamlit, HTTP, React) | **NOT IMPLEMENTED** | no such file or dependency exists |

Toolchain facts relevant to this phase, from
`docs/environment-reconnaissance.md` plus a read-only check performed in this
phase: Node `v20.11.1` is present and `npm`/`npx` report `10.2.4`. **No package
was installed and no network access was used.** Docker and Docker Desktop are
absent; WSL is present with no distributions. Python is 3.11.0 on `PATH`, with a
pre-existing project-local `.venv`.

Established project verification results, carried forward unchanged from
`docs/AUTHENTICATION_REVIEW.md` §12 and not re-run for this documentation-only
phase:

- `pytest` → **36 passed in 9.71s**
- `ruff check .` → **All checks passed**
- `mypy atlas` → **Success: no issues found in 23 source files**

### 0.3 Authoritative sources and precedence

When two documents disagree, this document does not resolve the conflict
silently. Precedence used here:

1. **Code and schema as they exist** for statements about current behavior
   (`atlas/**`, `tests/**`, `pyproject.toml`).
2. **`docs/THREAT_MODEL.md`** for threat and residual-risk statements, and for
   the "Security Properties ATLAS-X Does NOT Guarantee" list.
3. **`docs/SYSTEM_SPECIFICATION.md` §4–§5** for the lifecycle and entity model.
4. **`docs/DECISIONS.md` and `docs/TECHNOLOGY_STACK.md`** for standing technology
   decisions.
5. **`docs/CONFIGURATION_REVIEW.md`, `docs/STORAGE_REVIEW.md`,
   `docs/AUTHENTICATION_REVIEW.md`, `docs/ARCHITECTURE_RECONCILIATION.md`** for
   recorded findings and prerequisites.
6. **This document** only for UI-layer design that does not contradict 1–5.

Recorded conflicts are listed in §25.5.

### 0.4 Definition of a UI in ATLAS-X

A "UI" here means a **rendering and interaction layer over records that the core
already decided**. It consists of: navigation, data presentation, filtering,
user input collection, and requests to act. It contains no policy, no verdict,
and no state machine of its own.

---

# PART 1 — UI architectural principles

These are binding constraints on both surfaces. They are not aspirations; a
future phase that violates one has produced an unsafe UI.

### 1.1 The twelve principles

| # | Principle | Concrete obligation on the UI layer |
|---|---|---|
| 1 | **Backend/core services are authoritative.** | Every value shown is read from a core record or a core-returned projection. The UI stores no authoritative copy of task, plan, execution, verification, or provenance state. |
| 2 | **The UI is not a security boundary.** | Removing the UI must not remove a control. No control may exist *only* in the UI. `docs/THREAT_MODEL.md` already treats the browser/UI as boundary **T1**, i.e. an assumed-hostile edge, not a defense. |
| 3 | **The UI is never trusted for authorization.** | Hiding a button is cosmetic. The UI may not be the reason an operation is permitted. `docs/AUTHENTICATION_REVIEW.md` H-01 is the governing finding. |
| 4 | **The UI never decides whether an operation is permitted.** | The UI may not hold, infer, cache, or transmit a permission decision. It renders whatever the core returns, including a denial. |
| 5 | **The UI never decides whether an artifact is verified.** | The only source of a verification verdict is a `verifications` row produced by the verifier component (**SCHEMA ONLY** today). No client-side re-check, heuristic, or "looks right" affordance may be presented as verification. |
| 6 | **The UI never mutates historical provenance because a user changed something visually.** | Re-layout, re-color, re-group, re-filter, or re-render is presentation only. The UI must expose no control that edits, reorders, or deletes provenance events. `provenance_events` is append-only by application policy (`docs/THREAT_MODEL.md` D4). |
| 7 | **Model output is untrusted.** | Plan text, tool arguments, artifact content, and diagnosis text originate from a model or a generated program. They are rendered as **data**, never as instructions, never as trusted markup, and never as authority (`docs/THREAT_MODEL.md` B1). |
| 8 | **Displayed execution state must originate from real system state.** | Statuses come from stored columns (`tasks.status`, `plan_steps.status`, `executions.status`, `verifications.result`, `recovery_attempts.outcome`). The UI must not compute, infer, or optimistically advance a status. |
| 9 | **Animations represent real events; they never fabricate activity.** | See Part 8. There is no simulated progress, no idle "thinking" motion, and no synthetic telemetry. |
| 10 | **The visual layer must never imply an operation happened when the backend did not record it.** | A transition is drawn only from a recorded transition. Optimistic UI is forbidden for any state that has security or research meaning (verification, execution, authorization). |
| 11 | **The practical research interface must remain fully usable without the cinematic visualization.** | The Living System Map is optional and additive. Every research question the Map answers must also be answerable in the workspace (§18.2, and the degradation ladder in §17.3). |
| 12 | **The Living System Map is an observability and exploration surface, not the execution engine.** | The Map has no write path to lifecycle state other than the same core request path the workspace uses. It cannot start, pause, resume, or steer anything by itself. |

### 1.2 The one-sentence boundary

> The core decides what happened; the UI decides only how to show it.

### 1.3 Anti-patterns this specification forbids

These are rejected designs, listed so later phases cannot reintroduce them as
"enhancements":

- A client-side role/permission check that gates a control.
- A "Verify" button in the UI that runs a check in the browser.
- A progress bar, spinner, or percentage that is not derived from a stored
  status or a stored timestamp pair.
- A retry loop in the client that re-issues a lifecycle action.
- A UI-side "auto-fix" that mutates a plan, artifact, or provenance event.
- A demo/simulation mode that generates plausible-looking lifecycle data
  (see Part 23 for the bounded, labeled alternative).
- Treating a `SECURITY_BLOCKED` or `CANCELLED` badge as a real state before the
  core records one (§4.5).

---

# PART 2 — The two UI surfaces

Two surfaces, one contract set, no duplicated security or business logic.

## 2.1 Relationship between the surfaces

```
                    ┌──────────────────────────────────────────┐
                    │  ATLAS-X CORE  (authoritative)           │
                    │  atlas/auth  IMPLEMENTED                 │
                    │  atlas/storage + repositories IMPLEMENTED│
                    │  atlas/planner, executor, tools, sandbox, │
                    │  verifier, recovery  NOT IMPLEMENTED     │
                    └──────────────────────────────────────────┘
                          ▲                        ▲
              in-process Python             read-only HTTP
              (same interpreter)            (separate origin)
                          │                        │
        ┌─────────────────┴──────────┐   ┌─────────┴──────────────────┐
        │ A. RESEARCH WORKSPACE      │   │ B. LIVING SYSTEM MAP       │
        │ Streamlit (PLANNED)        │   │ React + TS + Vite (PLANNED)│
        │ practical, tabular, dense  │   │ SVG/Canvas graph, optional  │
        │ REQUIRED for research use  │   │ enhancement, never required │
        └────────────────────────────┘   └────────────────────────────┘
```

Rules:

- Both surfaces consume the **same** projections. Neither invents a field, a
  status vocabulary, or a derived verdict that the other lacks.
- Neither surface contains a second copy of an authorization, verification, or
  provenance rule. If two surfaces appear to need the same decision, that
  decision belongs in the core and this specification is wrong.
- Surface A is the system of record for *doing research*. Surface B is a lens.
  If Surface B is unavailable, blocked, or broken, research continues on
  Surface A (principle 11).

## 2.2 Surface A — ATLAS-X Research Workspace

- **Intended technology:** Streamlit (Apache-2.0), per the standing decision in
  `docs/DECISIONS.md` ("Streamlit-first UI") and the UI row of
  `docs/TECHNOLOGY_STACK.md`.
- **Status:** NOT IMPLEMENTED. Streamlit is **not** in `pyproject.toml`
  dependencies and no app file exists. Recorded as a known documentation-to-code
  gap in `docs/ARCHITECTURE_RECONCILIATION.md` §5.4.
- **Process model:** runs in the same Python interpreter as the `atlas` package
  and imports it directly. It is **not** an HTTP client of ATLAS-X. It does not
  need, and must not invent, a network API for its own sake.
- **Priorities, in order:** clarity, research usefulness, accessibility, low
  resource usage. Deliberately last: spectacle.
- **Audience:** the researcher operating this laptop. Secondary audience: a
  reader of exported `reports/`.

### 2.2.1 What the workspace is for

Authenticate; create and inspect tasks; inspect plans, execution, tool
permissions, sandbox state, verification, failures, recovery, artifacts, and
provenance; run and inspect benchmarks and experiments; and inspect
security/audit and configuration information — **to the extent those records
exist**. Today only authentication, tasks, and provenance recording exist. Every
other panel is a specified-but-unbuildable contract until its core phase lands.

### 2.2.2 Session handling requirement (derived from existing code, not invented)

The browser session must be handled as follows, and these are requirements
derived from recorded findings rather than new security design:

1. On login, `AuthService.login()` returns the raw token **once**. Surface A
   keeps it in server-side Streamlit session state, never in the browser, never
   in a query string, and never in a client-side store.
2. Every privileged interaction re-validates through
   `AuthService.validate_session(token)`. The validated identity is not cached
   across interactions as an authorization decision, because
   `docs/AUTHENTICATION_REVIEW.md` M-04 records that session validity is split
   between the repository and the service and is not one fail-closed invariant
   yet.
3. Surface A must not display a password hash, a raw token, a token digest, or
   `application_secret_key` under any circumstance. `UserRepo.get_by_username()`
   and `get_by_id()` return `SELECT *` rows and are **not** safe to render
   (`docs/STORAGE_REVIEW.md` M-8, `docs/AUTHENTICATION_REVIEW.md` M-07).
4. `atlas/auth/sessions.py::cookie_attributes()` exists but **is never called**
   by any code. Whether Surface A uses cookies, and with what CSRF posture, is
   an open decision (§25.3), not a settled one. Until it is decided, no
   document may claim cookie-based session protection is active.
5. The `LoginLockedError` branch is observably distinct from
   `AuthenticationFailed` (`docs/AUTHENTICATION_REVIEW.md` M-01). Surface A must
   render the core's error, must not normalize it into a success-looking state,
   and must not add a client-side delay pretending to be the core's
   `auth_failure_delay_seconds`.

## 2.3 Surface B — ATLAS-X Living System Map

- **Intended technology:** React + TypeScript + Vite, SVG and/or Canvas, with
  open-source graph/animation libraries **only where justified by measurement**.
- **Status:** NOT IMPLEMENTED, and **not installed**. No `apps/`, no `web/`, no
  `package.json`, no `node_modules`. `docs/ARCHITECTURE_RECONCILIATION.md` §5.2
  records that an early `apps/web` sketch was deliberately retired.
- **Purpose:** to make the *real* lifecycle of a real ATLAS-X task visually
  legible, and to let a researcher trace a result back through verification,
  artifact, execution, tool, plan step, plan, and task.
- **Hard dependency (blocking):** a browser application in a separate origin
  cannot import the Python package. It therefore requires a **read-only HTTP
  projection API**, and `docs/TECHNOLOGY_STACK.md` explicitly defers FastAPI
  "only if an HTTP API is genuinely needed." This phase does not decide that
  question; it records it as the gating decision (§25.3, D-07).
- **Explicitly recorded conflict:** the React stack is listed under
  "Dependencies We Explicitly Avoid" in `docs/TECHNOLOGY_STACK.md`
  ("React/Next.js frontend — Streamlit-first; a frontend toolchain adds risk
  without research value"). This phase is instructed to specify the Map with
  that stack. Rather than override either document, this specification keeps the
  Map **additive and optional**: it never displaces Surface A, it carries no
  security decision, and its existence requires an explicit human gate. The
  conflict is recorded in §25.5 as **C-01**.

### 2.3.1 What the Map is

An observability and exploration surface over recorded state (principle 12). It
renders nodes and edges for real records. It is not a control room: it has no
authority over lifecycle state, and its visual richness is bounded by the data
that actually exists.

### 2.3.2 What the Map is not

- Not an execution engine, scheduler, or queue.
- Not a source of truth for any status.
- Not required for any research task to be completed.
- Not a place where synthetic or illustrative data is rendered without an
  explicit, persistent fixture label (Part 23).

---

# PART 3 — Information architecture (Research Workspace)

## 3.1 Screen consolidation decision

Twenty candidate screens were evaluated. Sixteen of them are task-scoped and
share one data spine (a task → plan → steps → executions → artifacts →
verifications → failures → recoveries → provenance chain). Splitting them into
sixteen top-level destinations would multiply navigation cost, multiply
authorization questions, and invent cross-screen state for no research gain.

**Decision:** Surface A has **eight** top-level destinations, with task-scoped
inspection delivered as tabs inside **Task Detail**. Mapping of all twenty
candidates:

| Candidate | Decision | Placement |
|---|---|---|
| 1. Authentication | Adopt | Destination 1 |
| 2. Dashboard | Adopt | Destination 2 |
| 3. Task creation | Adopt | Destination 3 |
| 4. Task list | Adopt | Destination 4 |
| 5. Task detail | Adopt | Destination 5 (tabs 5.1–5.9) |
| 6. Plan inspection | Merge | Tab 5.2 |
| 7. Execution timeline | Merge | Tab 5.3 |
| 8. Tool registry | Adopt (deferred) | Destination 6 |
| 9. Tool permission information | Merge | Tab 6.2 (never a grant surface) |
| 10. Sandbox status | Merge | Tab 5.4 |
| 11. Verification | Merge | Tab 5.5 |
| 12. Failure details | Merge | Tab 5.6 |
| 13. Recovery history | Merge | Tab 5.7 |
| 14. Artifact browser | Merge | Tab 5.8 |
| 15. Provenance explorer | Merge | Tab 5.9 (+ destination 7 for cross-task audit) |
| 16. Benchmark runner | Adopt (deferred) | Destination 8 |
| 17. Experiment results | Merge | Destination 8, second tab |
| 18. Security/audit information | Adopt (partial) | Destination 7 |
| 19. System configuration | Adopt (read-only) | Destination 7, tab |
| 20. Documentation/help | Adopt | Footer panel, not a destination |

No screen beyond these twenty candidates is proposed. In particular, there is no
"admin" screen, no "raw SQL" screen, and no "edit provenance" screen, because no
core capability would justify any of them.

## 3.2 Navigation model

Flat, eight destinations, always visible, keyboard reachable in order. No nested
sidebar tree, no modal-driven flow, no wizard. Rationale: a flat list is fully
discoverable by screen reader and keyboard, and it keeps the "where am I and what
is real" question answerable at all times.

```
1  Authentication        (unauthenticated only)
2  Dashboard
3  New Task
4  Tasks
5  Task Detail
6  Tools                 [PLANNED — core does not exist]
7  Security & Provenance [partial: provenance + configuration today]
8  Benchmarks & Experiments [PLANNED — no evaluation harness]
```

## 3.3 Screen specifications

Fields per screen: purpose; primary user; required data; actions available;
actions unavailable; authorization dependency; loading state; empty state; error
state; permission-denied state; successful state; security considerations.

Statuses referenced below are `CURRENTLY IMPLEMENTED`, `SCHEMA ONLY`, or
`NOT IMPLEMENTED`, per §0.1.

---

### Destination 1 — Authentication

- **Purpose:** establish an authenticated session; register a local account;
  change a password; end a session.
- **Primary user:** the local researcher-operator.
- **Required data:** `users.id`, `users.username`, `users.created_at` (the public
  projection `UserRepo.get_public()` returns — IMPLEMENTED). `sessions.expires_at`
  for the session banner (IMPLEMENTED).
- **Actions available:** register, login, logout, change own password.
- **Actions unavailable:** impersonation; acting on another user's account;
  unlocking a locked account; viewing lockout counters for another account;
  any role or permission action.
- **Authorization dependency:** none exists yet. Access to any other
  destination depends only on a valid session, which is *authentication*, not
  authorization (NOT IMPLEMENTED). This is the exact boundary stated in
  `docs/AUTHENTICATION_REVIEW.md` §7 and finding H-01.
- **Loading state:** form disabled while `AuthService.login()` runs, because the
  failure path includes a real `time.sleep(auth_failure_delay_seconds)`. The UI
  must not fake completion during that sleep.
- **Empty state:** not applicable; a form is always actionable.
- **Error state:** render the core exception's message. Two distinct failures
  exist and must stay distinct because the core makes them distinct: invalid
  credentials (`AuthenticationFailed`) and locked account
  (`LoginLockedError`). Registration raises `UsernameAlreadyExists` including
  the submitted username, and `ValueError` for length rules (username 3–32 of
  letters/digits/`_`/`-`; password ≥ 8). The UI must not merge these into one
  message, and must not add a client-side enumeration aid (M-01, M-02).
- **Permission-denied state:** not applicable at this screen.
- **Successful state:** session established; the public user identity is shown;
  the token itself is never displayed, copied, or logged by the UI.
- **Security considerations:** never render `password_hash`; never echo a
  submitted password back into the DOM; never place a token in a URL; the
  enumeration trade-offs above are already known (`A6` residual Lo–Med) and the
  UI must not make them worse, for example by prefilling or suggesting usernames.

---

### Destination 2 — Dashboard

- **Purpose:** orient the researcher in real system state at a glance.
- **Primary user:** the researcher-operator.
- **Required data:** counts and recents derived from `tasks`,
  `executions`, `verifications`, `failures`, `recovery_attempts`, `artifacts`,
  `provenance_events`, `evaluation_runs`. Today, only `tasks` and
  `provenance_events` are writable/readable by any repository, so a truthful
  dashboard today shows tasks and provenance plus explicit "not implemented"
  markers for the rest.
- **Actions available:** navigate to a task; refresh.
- **Actions unavailable:** start/stop/cancel work; retry anything; mutate counts;
  filter across users.
- **Authorization dependency:** every query must be scoped to the authenticated
  user. `TaskRepo.list_for_user()` does this (IMPLEMENTED);
  `ProvenanceRepo` has **no** owner predicate and no owner column
  (`docs/STORAGE_REVIEW.md` M-4), so cross-task provenance aggregation is a
  **known blocker** for this screen, not a UI choice.
- **Loading state:** skeleton with the query in flight; no placeholder numbers.
- **Empty state:** "No tasks yet" with a link to Destination 3. Never a zero
  rendered as a chart axis implying a measurement.
- **Error state:** "Could not load dashboard data" with the technical detail
  collapsed and available only in a diagnostics panel that is redacted.
- **Permission-denied state:** a denied query renders as a denial, not as zero
  and not as an error.
- **Successful state:** numbers with their definitions and their as-of time.
- **Security considerations:** every metric must be traceable to a query over
  stored rows (Part 14). No decorative telemetry. No cross-user aggregation.

---

### Destination 3 — New Task

- **Purpose:** create a task owned by the authenticated user.
- **Primary user:** the researcher-operator.
- **Required data:** `title`, `goal`, `user_id` (server-derived from the
  validated session, never from a form field). `TaskRepo.create()` is
  IMPLEMENTED and hard-codes `status = 'pending'`.
- **Actions available:** submit a title and goal within bounds.
- **Actions unavailable:** choose an owner; choose an initial status; choose a
  plan; choose tools; trigger execution directly; upload arbitrary files.
- **Authorization dependency:** the authenticated principal supplies ownership.
  Nothing else is authorized, because authorization does not exist
  (NOT IMPLEMENTED). Task creation is therefore available to any authenticated
  user for themselves only.
- **Loading state:** submit disabled while the insert transaction runs.
- **Empty state:** the form itself.
- **Error state:** `max_task_chars` (default 4,000; range 1–100,000) is a
  **configured, validated, but not yet enforced** limit
  (`docs/CONFIGURATION_REVIEW.md` §3). The UI must therefore *not* claim the
  core enforces a length cap. It may show the configured value as
  "configured, enforcement lands with the task-validation phase," and must
  validate in the browser only as a convenience, clearly labelled as a
  convenience.
- **Permission-denied state:** not applicable; there is no cross-user creation.
- **Successful state:** task created with a real id, `status = 'pending'`, and
  real timestamps; navigation to Destination 5.
- **Security considerations:** `goal` is untrusted text and a prompt-injection
  surface (`docs/THREAT_MODEL.md` B1). It must be rendered as plain data, never
  as markup, and must never be displayed inside a context that implies it is an
  instruction the system will obey. No SQL is built from it (standing rule 4 in
  `SECURITY.md`).

---

### Destination 4 — Tasks

- **Purpose:** list the authenticated user's tasks and filter them.
- **Primary user:** the researcher-operator.
- **Required data:** `tasks.id`, `title`, `goal` (truncated by the UI for
  display only), `status`, `created_at`, `updated_at`.
- **Actions available:** filter by status and date, sort, open a task, delete
  own task.
- **Actions unavailable:** view, edit, or delete another user's task; bulk
  actions across users; bulk re-run.
- **Authorization dependency:** `TaskRepo.list_for_user()` and
  `TaskRepo.get()` carry `WHERE user_id = ?` (IMPLEMENTED for these three
  methods only). This is repository-level ownership filtering, **not** an
  authorization layer (`docs/STORAGE_REVIEW.md` §13).
- **Loading state:** table skeleton.
- **Empty state:** "No tasks match" with a filter-reset control.
- **Error state:** generic failure with redacted detail.
- **Permission-denied state:** a task id belonging to another user must render
  as "not found or not permitted" from the core's perspective. Because the core
  currently returns `None` for a foreign id, the UI must not be able to
  distinguish "absent" from "forbidden" either, and must not attempt to.
- **Successful state:** the list; deletion shows the real cascade consequence
  (deleting a task cascades plans, steps, executions, artifacts, verifications,
  failures, and recovery attempts, and nulls provenance references —
  `docs/STORAGE_REVIEW.md` §9). The confirmation must state that, because it is
  destructive and irreversible.
- **Security considerations:** deletion is a provenance-affecting action. The UI
  must warn using the actual cascade behavior, must not offer "undo"
  (no soft delete, no retention policy, no secure erasure — M-6), and must not
  present a deleted task's data as recoverable from the UI.

---

### Destination 5 — Task Detail

Container for the real research work. Nine tabs. Each tab's data is currently
SCHEMA ONLY except 5.9, which is the one partially real.

Common contract for all tabs:

- **Loading state:** per-tab, not full-page.
- **Empty state:** names the specific record that does not exist yet (e.g. "No
  plan recorded for this task") — never a generic blank panel.
- **Error state:** redacted, with the tab still usable.
- **Permission-denied state:** the tab is not rendered as available; if reached
  directly it shows a denial.
- **Successful state:** records with ids and timestamps.
- **Cross-cutting rule:** no tab may display a status value the core did not
  store, and no tab may display a `pending`/`failed` state as though a
  corresponding record existed.

#### 5.1 Overview
Task record; current `status`; ownership; creation/update timestamps; a compact
lifecycle strip that reflects only recorded transitions; links to the sibling
tabs. No "continue" or "retry" affordance, because no orchestrator exists.

#### 5.2 Plan
Source: `plans.plan_json`, `plans.validated` (0/1), and `plan_steps` rows
(`position`, `action`, `tool_name`, `input_json`, `status`) — SCHEMA ONLY.
Display: the plan as structured data (read-only tree/table), the `validated`
flag exactly as stored, and the step count against the configured
`max_plan_steps` (default 10) labelled as configured-not-enforced.
`plan_json` and `input_json` are model-produced text and are untrusted
(principle 7). The `validated` flag has no database `CHECK` and no validator
(`docs/STORAGE_REVIEW.md` M-3), so a non-0/1 value must render as
"unrecognized validation flag," never as "validated." No inline plan editing.

#### 5.3 Execution timeline
Source: `executions` rows (`attempt`, `status`, `started_at`, `finished_at`,
`result_json`, `error`) — SCHEMA ONLY. Display: one row per attempt, ordered by
`attempt`, with real timestamps. `attempt` has no uniqueness or range
constraint, so duplicate or out-of-range attempts must render as recorded, with
an "unrecognized" marker. `max_execution_seconds` and
`max_concurrent_executions` are configured and unenforced today, so the UI must
not render a live countdown or a queue position.

#### 5.4 Sandbox state
See Part 13. Source: none exists. There is no sandbox component and no
execution path (`docs/ARCHITECTURE_RECONCILIATION.md` §3.3). This tab exists as
a specified contract and must render an explicit "sandbox not implemented"
state until Phase 10 lands, and must never describe the planned Windows
subprocess approach as container isolation.

#### 5.5 Verification
See Part 10. Source: `verifications` rows (`verifier`, `result`, `detail_json`,
`created_at`) — SCHEMA ONLY. `result` is `TEXT` with **no** `CHECK` constraint,
so the UI renders the stored string and treats unrecognized values as
unclassified rather than coercing them (§4.5, Part 10).

#### 5.6 Failures
Source: `failures` rows (`category`, `diagnosis`, `detail_json`, `created_at`) —
SCHEMA ONLY. `category` has no defined vocabulary in the schema or in
`SYSTEM_SPECIFICATION.md` §5, so the UI must render the stored string and must
not present a fixed category taxonomy as if the core defined it.

#### 5.7 Recovery history
See Part 11. Source: `recovery_attempts` rows (`attempt_no`, `diagnosis`,
`new_plan_json`, `outcome`) — SCHEMA ONLY, attached to an `execution_id`.
`attempt_no` has no range or uniqueness constraint; `max_recovery_attempts`
(default 2, range 1–10) is configured and unenforced. The UI must render
`attempt_no` as stored and must not compute or display an authoritative
"max attempts" as though the core enforced it — it may show the configured value
labelled as configured.

#### 5.8 Artifacts
Source: `artifacts` rows (`name`, `kind`, `relative_path`, `content`,
`size_bytes`, `checksum`, `created_at`) — SCHEMA ONLY. `size_bytes` has no
non-negative constraint; `relative_path` has **no** validation and is not
confined to any sandbox root (`docs/STORAGE_REVIEW.md` §6, M-1). Rendering rules
in Part 21.5. Default view is metadata only; `content` is opt-in, size-capped
for display, and never treated as trusted content.

#### 5.9 Provenance
See Part 9. This is the only task-scoped tab with real code behind it:
`ProvenanceRepo.record()` is IMPLEMENTED and one producer exists
(`AuthService._record_registration` writes `event_type='user.registered'`,
`actor='auth'`). All other event types are PLANNED (Phase 14).
Hard constraints: the UI is read-only here; `task_id`/`execution_id` are
nullable and set to `NULL` on task deletion, so orphaned events exist and must be
labeled as such; and `detail_json` is `json.dumps()` of an arbitrary caller
dictionary with **no** redaction, allowlist, or size cap

Ownership note, which is why this tab is specifiable while Destination 7's
cross-task audit view is not: a task-scoped provenance read inherits ownership
from the task lookup that already carries `WHERE user_id = ?`
(`TaskRepo.get()`). The provenance query itself still has no owner predicate, so
this inheritance is a **presentation-layer argument, not an enforced
authorization control** — it disappears the moment a task id is accepted from a
client, a graph edge, or a URL. A cross-task aggregate has no such anchor and is
blocked until Phase 08/14 establish ownership (D-08, and Destination 7).
(`docs/STORAGE_REVIEW.md` §8, M-5). Provenance detail therefore requires a
data-minimization decision (§25.3, D-08) before it can be rendered.

---

### Destination 6 — Tools

- **Purpose:** show the tool registry and the caller's permission position.
- **Primary user:** the researcher-operator.
- **Required data:** `tools` and `tool_permissions` — **NOT IMPLEMENTED**. There
  are no such tables (`docs/STORAGE_REVIEW.md` §2) and no registry code
  (Phase 09). `SYSTEM_SPECIFICATION.md` §5 lists the planned fields.
- **Actions available:** browse registry metadata; view declared policy; view
  own permission state.
- **Actions unavailable:** **grant, revoke, or request a permission by clicking.**
  Permission changes are core operations with audit requirements
  (`docs/STORAGE_REVIEW.md` §12) and are not a UI action in this specification.
  Also unavailable: create or edit a tool, enable a tool, or edit a policy.
- **Authorization dependency:** viewing is subject to the core's decision;
  mutating permissions is a core-only action with a provenance requirement.
- **Loading/empty/error/denied states:** the panel must render an explicit
  "tool registry not implemented" state. It must not show a sample registry, an
  empty-but-plausible tool list, or disabled buttons that imply a future grant
  path.
- **Permission-denied state:** for a tool the caller may not use, the UI shows
  the core's denial and does not reveal whether the tool exists for others.
- **Security considerations:** Part 12 governs the metadata; deny-by-default
  means absence of a grant is a legitimate display state.

---

### Destination 7 — Security & Provenance (cross-task audit + configuration)

- **Purpose:** audit view over provenance across the user's tasks, plus a
  read-only view of effective configuration.
- **Primary user:** the researcher-operator, reviewing their own history.
- **Required data:** `provenance_events` (partially real), and
  `Settings.safe_dump()` (IMPLEMENTED — the only secret-safe projection).
- **Actions available:** filter events by type/actor/time; export the visible
  event set for a report; view effective non-secret configuration.
- **Actions unavailable:** edit or delete an event; re-run or repair an event;
  change any setting from the UI; view `application_secret_key`; view another
  user's events; view raw `detail_json` before a redaction decision exists.
- **Authorization dependency:** provenance has no owner column and
  `ProvenanceRepo` has no user predicate, so a user-scoped cross-task audit view
  is **blocked** until Phase 14/08 establishes ownership and redaction. Until
  then this destination is limited to configuration display and to a
  clearly-labeled statement of the blocker.
- **Loading/empty/error/denied states:** explicit; an empty audit view must say
  "no events recorded" rather than implying a healthy system.
- **Security considerations:** `safe_dump()` is the only sanctioned
  configuration projection and it excludes `application_secret_key`; the UI must
  use it and must not re-implement field filtering. The application secret is
  **unused by any current code** (`docs/CONFIGURATION_REVIEW.md` MEDIUM-3) and
  must not be described as a signing or encryption key. `SecretsRedactionFilter`
  exists but is not attached to any logger (HIGH-1), so the UI cannot rely on
  runtime log redaction and must apply its own presentation-level
  data-minimization instead — without becoming the security boundary (principle
  2).

---

### Destination 8 — Benchmarks & Experiments

- **Purpose:** run and inspect reproducible evaluations.
- **Primary user:** the researcher-operator.
- **Required data:** `evaluation_runs` (`run_name`, `config_json`, `status`,
  `results_json`, timestamps) — SCHEMA ONLY, with **no** user or ownership
  relationship (`docs/STORAGE_REVIEW.md` §2, §12 item 3). No `BenchmarkTask`
  table exists. No `Metric` or `Experiment` entity exists anywhere.
- **Actions available (future):** define a run, execute it, read results.
- **Actions unavailable (future, by design):** edit stored results; mark a run
  as passing; delete a run to hide a failure; hand-author `results_json`.
  "No fabricated results" and "no cherry-picking" are standing decisions
  (`docs/DECISIONS.md`, `SYSTEM_SPECIFICATION.md` §7).
- **Authorization dependency:** ownership semantics of evaluation runs must be
  decided before this screen is exposed to more than one account
  (§25.3, D-09).
- **Loading/empty/error/denied states:** "evaluation harness not implemented"
  until Phase 21+.
- **Security considerations:** benchmark inputs are versioned research assets
  (B4, poisoned-input defense). The UI must not offer dataset editing that would
  silently change inputs between ablations.

---

# PART 4 — Task lifecycle visualization

## 4.1 The authoritative lifecycle

`docs/SYSTEM_SPECIFICATION.md` §4 is the authoritative lifecycle and it enumerates
**18 stages**, not the shorter diagram used to brief this phase. It also names
the owning component and the record each stage produces:

| # | Stage | Owning component | Record produced |
|---|---|---|---|
| 1 | User authentication | `auth/` (done) | sessions, users |
| 2 | Authorization | `security/` (Phase 08) | — |
| 3 | Task creation | `storage/` (done) | tasks |
| 4 | Task validation | input validation layer | — |
| 5 | Plan generation | `planner/` (Phase 11) | plans |
| 6 | Plan validation | deterministic validator | plans (`validated`) |
| 7 | Tool authorization | `tools/` + `security/` | tool_permissions |
| 8 | Sandboxed execution | `sandbox/` (Phase 10) | executions |
| 9 | Artifact generation | `sandbox/` (Phase 10) | artifacts |
| 10 | Deterministic verification | `verifier/` (Phase 13) | verifications |
| 11 | Failure classification | `recovery/` (Phase 15) | failures |
| 12 | Diagnosis | deterministic inspection | failures (`diagnosis`) |
| 13 | Bounded recovery/replanning | `recovery/` (Phase 16) | recovery_attempts |
| 14 | Re-execution | orchestrator | a new `executions` row |
| 15 | Re-verification | verifier | a new `verifications` row |
| 16 | Provenance recording | `provenance/` + `storage/` | provenance_events |
| 17 | Final result | orchestrator | result (only with a recorded PASS) |
| 18 | Evaluation logging | `evaluation/` | evaluation_runs |

**No component in stages 2 and 4–18 exists.** `atlas/planner/`,
`atlas/executor/`, `atlas/verifier/`, `atlas/recovery/`, `atlas/tools/`,
`atlas/sandbox/`, `atlas/provenance/`, and `atlas/evaluation/` are one-line
docstrings. The only real transition today is task creation
(`tasks.status` is hard-coded to `'pending'` by `TaskRepo.create()`) plus the one
`user.registered` provenance event written during registration.

## 4.2 The visual lifecycle is a derived view, and it is marked as such

The diagram briefed for this phase (TASK → PLANNING → PLAN VALIDATION →
AUTHORIZATION → READY → EXECUTING → VERIFYING → PASS/FAIL → RECOVERY → REPLAN →
EXECUTING → VERIFYING, plus COMPLETED / FAILED / CANCELLED / SECURITY_BLOCKED)
is **more convenient for drawing than authoritative for storage**. The
authoritative source is `SYSTEM_SPECIFICATION.md` §4. The visual view is adopted
as a *naming convention for display*, subject to all of the following, which are
not optional:

1. A stage may be drawn **only** when the record it produces exists. Stages with
   no record do not appear as nodes, boxes, or placeholders in a live view.
2. The visual state name is a **label**, not a stored value. The UI must always
   show the raw stored value alongside any friendly label, because none of the
   status columns has a database `CHECK` constraint and no status enum is defined
   in code or schema (`docs/STORAGE_REVIEW.md` M-3).
3. `READY` is **not** an authoritative concept in `SYSTEM_SPECIFICATION.md` §4.
   It is treated here as a derived label for "plan validated and tool
   authorized," and the UI must only show it once both records exist.
4. `AUTHORIZATION` as a user-visible stage must not imply a role model. Stage 2
   is resource-level ownership plus permission, not a role
   (`docs/THREAT_MODEL.md` A4: roles are Phase 08 and residual risk is **Hi**
   until then). The UI must not render an actor's "authority level" as a
   property of a person.

## 4.3 Loop placement, resolved against the schema

`SYSTEM_SPECIFICATION.md` §14 states that re-execution is "a new `Execution`
attempt under the same task", and `recovery_attempts.execution_id` points at the
**failing** execution. Therefore the retry loop is **not** execution → execution.
It is:

```
EXECUTION(attempt=n) --FAIL--> FAILURE --> RECOVERY(attempt_no=k)
        --> new recovery_attempts row attached to EXECUTION(n)
        --> revalidated plan payload
        --> EXECUTION(attempt=n+1)   [new sibling row under the same task]
        --> new verifications rows
```

Visualization rule: executions are **siblings under the task**, numbered by the
stored `attempt` value, and a recovery node points forward to the next execution
node rather than nesting inside the failed one. The UI must not renumber,
merge, or compact attempts, and must not imply that a later attempt erased an
earlier one.

## 4.4 Terminal states

| Terminal state | Authoritative? | Storage evidence | UI rule |
|---|---|---|---|
| Completed | Implied by stage 17 ("only a verified result ... is finalized") | No status enum exists | Render only when a recorded verification PASS and a finalized result exist. Not a badge the UI may award. |
| Failed (bounded) | Implied by stage 17 ("or a bounded, recorded failure") | `failures` + `recovery_attempts` (SCHEMA ONLY) | Render only with the failure record and the recovery bound actually recorded. |
| Cancelled | **NOT in the authoritative model** | No cancellation mechanism, column, or service exists anywhere | Never render. The UI must not offer a cancel control for tasks or executions, because nothing can honor it. Recorded as gap **C-04**. |
| Security blocked | **NOT in the authoritative model** | No `security_blocked` value, column, or service exists | Never render. When Phase 08 denies an action, the UI shows a **denial on that action**, which is not the same as a task terminal state. Recorded as gap **C-04**. |

## 4.5 Unknown-value policy (applies to every status field)

Because `tasks.status`, `plan_steps.status`, `executions.status`,
`verifications.result`, `recovery_attempts.outcome`, and
`evaluation_runs.status` are unconstrained `TEXT` columns with no enum, and
because the brief for this phase asks for a three-valued verification model that
the schema does not define, the following single rule governs all of them:

> Render the stored value verbatim. Classify it only if it matches a documented
> vocabulary. Otherwise show it as **unrecognized**, with the raw value visible.
> Never coerce, never default to `PASS`, `pending`, or `failed`, and never hide
> it.

This is how the UI stays honest while the core's vocabularies are still being
decided in Phases 08–16. It also means the UI requires **no** change when the
core later adds `INCONCLUSIVE` or `CANCELLED`: the value simply starts being
recognized.

## 4.6 Recorded lifecycle discrepancies

| ID | Discrepancy | Authoritative source | Effect on this specification |
|---|---|---|---|
| C-02 | The briefed diagram has ~13 visual stages; `SYSTEM_SPECIFICATION.md` §4 has 18. The brief's `READY` and `SECURITY_BLOCKED` have no authoritative counterpart. | `SYSTEM_SPECIFICATION.md` §4 | §4.2 labels the visual view as derived; §4.4 forbids rendering non-authoritative terminal states. |
| C-03 | The brief requires `INCONCLUSIVE` as a first-class verification outcome. `SYSTEM_SPECIFICATION.md` §5 defines `result` as PASS/FAIL, and `verifications.result` is unconstrained `TEXT` with no `CHECK`. | `SYSTEM_SPECIFICATION.md` §5 + `atlas/storage/migrations.py` | Part 10 defines rendering for a three-valued model **conditional on the core defining it**; §4.5 forbids collapsing or inventing it meanwhile. |
| C-04 | `CANCELLED` and `SECURITY_BLOCKED` are briefed as terminal states; no cancellation or security-block record exists in schema, code, or specification. | `atlas/storage/migrations.py`, `atlas/**` | §4.4: never rendered. Escalated as a required decision (§25.3, D-05). |

---

# PART 5 — Living System Map nodes

## 5.1 Precondition: nothing to draw yet

`tasks` and `provenance_events` have real data. `plans`, `plan_steps`,
`executions`, `artifacts`, `verifications`, `failures`, and
`recovery_attempts` are SCHEMA ONLY, and no code writes them. `tools` and
`tool_permissions` do not exist as tables. Therefore **the Map cannot render a
single lifecycle node today**, and a Map implementation that shows example
nodes without an explicit fixture label would violate Part 8 and Part 23.

Every node below is specified so that a future implementation creates it from a
record and from nothing else.

## 5.2 Node specifications

Fields per node: what it represents; what backend state creates it; metadata
that may be displayed; metadata that must remain hidden; possible statuses;
possible transitions; hover behavior; click behavior; expandability; provenance
traceability.

Node **positions are never authoritative**. Layout is presentation only
(principle 6). No node may be dragged into a position that implies a different
hierarchy, and no manual arrangement may be stored as system state.

---

### TASK

- **Represents:** one unit of research work owned by one user.
- **Created by:** a `tasks` row (IMPLEMENTED writer: `TaskRepo.create()`).
- **Display metadata (user-visible):** `id`, `title`, `status` (verbatim),
  `created_at`, `updated_at`; a truncated `goal` preview labelled as untrusted
  model-directed text.
- **Must remain hidden:** `user_id` unless it is the viewer's own id and the
  display is labelled as such; any other user's identifier; internal row fields
  returned by `SELECT *` that are not user-meaningful.
- **Possible statuses:** the stored `status` string. The only value any code
  writes today is `'pending'`.
- **Transitions:** none observable yet. Outgoing edges are drawn only when the
  corresponding records exist.
- **Hover:** title, id, status, created timestamp, and counts of *existing*
  child records (plan, executions, artifacts, verifications, provenance events)
  — each count from a real query, and 0 shown as "0", never as an omitted field.
- **Click:** select; offer navigation to the workspace Task Detail for the same
  id.
- **Expands:** yes, to its existing children.
- **Provenance-traceable:** yes — it is the root of the chain.

### PLAN

- **Represents:** the structured decomposition of a goal.
- **Created by:** a `plans` row (SCHEMA ONLY).
- **Display metadata:** `id`, `validated` (verbatim 0/1 or other), timestamps;
  step count; `plan_json` rendered as structured, read-only data.
- **Must remain hidden:** nothing extra is hidden beyond the global rules, but
  `plan_json` must be labeled untrusted model output.
- **Possible statuses:** `validated` is a flag, not a state machine.
- **Transitions:** to PLAN STEP (children). A *replan* does **not** create a
  second `plans` row — see the structural constraint below.
- **Hover:** id, `validated` raw value, step count, and whether a recovery
  attempt supplied this payload (only if a `recovery_attempts.new_plan_json`
  record says so).
- **Click:** select; expand to steps; open the read-only plan view.
- **Expands:** yes, to steps.
- **Provenance-traceable:** yes.

> **Structural constraint (important, not resolvable by this document).**
> `plans.task_id` is declared `UNIQUE` (`atlas/storage/migrations.py:72`). The schema therefore
> permits **exactly one plan row per task**. A replan cannot be a new `plans`
> row, and the only place a renewed plan payload is stored today is
> `recovery_attempts.new_plan_json`. Consequences: (a) if a replan overwrites
> `plans.plan_json`, history is destroyed, which collides with principle 6 and
> with the append-only intent of `docs/THREAT_MODEL.md` D4; (b) therefore a
> revision model (plan revisions, or a new table, or an immutable
> `recovery_attempts` chain as the authority) must be decided by the owning core
> phases (11/12/16) before the Map can draw a "REPLAN → new PLAN" edge. Until
> then the Map must render a recovered plan as a **distinct, explicitly labeled
> recovered-plan node sourced from `recovery_attempts`**, never as an ordinary
> second PLAN. Recorded as **C-05** and decision **D-06**.

### PLAN STEP

- **Represents:** one atomic planned action inside a plan.
- **Created by:** a `plan_steps` row (SCHEMA ONLY).
- **Display metadata:** `id`, `position` (verbatim), `action`, `tool_name`
  (verbatim, may be `NULL`), `status` (verbatim), timestamps; `input_json` only
  as redacted, size-capped, read-only data.
- **Must remain hidden:** nothing beyond global rules; `input_json` is
  untrusted model-directed text and must be rendered as data, never as markup
  and never as an instruction the system will follow.
- **Possible statuses:** the stored `status` string; no enum is defined. Duplicate
  or unordered `position` values must render as recorded.
- **Transitions:** to TOOL (when a `tool_name` matches a registry entry, which
  cannot happen yet), to EXECUTION (when an execution exists that consumed it —
  **no such linkage column exists in the schema**, see §6.3.1 and C-07).
- **Hover:** id, position, tool name, status, and any bound that applied.
- **Click:** select; open the step detail.
- **Expands:** yes, to its arguments and any linked records.
- **Provenance-traceable:** intended yes; blocked today (§6.3.1, C-07).

### AUTHORIZATION

- **Represents:** a recorded authorization decision for an action on a resource.
- **Created by:** **NOT IMPLEMENTED.** No authorization layer, no roles, no
  permission table, no decision record exists
  (`docs/ARCHITECTURE_RECONCILIATION.md` §2 and §4; `docs/THREAT_MODEL.md` A4,
  residual **Hi** until Phase 08 with tests).
- **Display metadata (when it exists):** the decision outcome as recorded, the
  resource type, the action, and the policy identifier — **no internal policy
  text**, no rule internals, nothing that would help an attacker map the policy.
- **Must remain hidden:** the caller's supplied identity claims; the internal
  decision function's logic; any other user's identity involved in the decision.
- **Possible statuses:** whatever the core records (allow/deny at minimum). No
  vocabulary exists yet.
- **Transitions:** none until the core produces records.
- **Hover:** outcome, action, resource type, timestamp.
- **Click:** open the audit record for that decision, if one exists.
- **Expands:** no.
- **Provenance-traceable:** intended yes; it is an audit event, not lifecycle
  state.
- **Hard rule:** this node must never be used to display *who may use what* as a
  property of a person, and must never be interactive in a way that suggests the
  viewer can change an authorization outcome.

### TOOL

- **Represents:** a named, schema-declared capability the registry exposes.
- **Created by:** **NOT IMPLEMENTED.** No `tools` table, no registry
  (`docs/STORAGE_REVIEW.md` §2; Phase 09).
- **Display metadata (when it exists):** see Part 12.
- **Must remain hidden:** implementation internals, credentials, environment
  values, anything that would assist abuse.
- **Possible statuses:** the stored `enabled`/policy value as recorded.
- **Transitions:** to EXECUTION when an execution dispatches it.
- **Hover / click / expand:** metadata panel; select; expand to declared input
  schema (read-only).
- **Provenance-traceable:** intended yes.

### EXECUTION

- **Represents:** one concrete attempt to run the task.
- **Created by:** an `executions` row (SCHEMA ONLY).
- **Display metadata:** `id`, `task_id`, `attempt` (verbatim), `status` (verbatim),
  `started_at`, `finished_at`; presence/absence of `error` and of `result_json`
  as booleans, not as raw dumps.
- **Must remain hidden:** raw `result_json` and `error` bodies by default (they
  may contain untrusted or sensitive content; Part 21).
- **Possible statuses:** the stored string. `attempt` has no uniqueness or range
  constraint, so duplicates render as recorded.
- **Transitions:** to ARTIFACT, to VERIFICATION, to FAILURE, and — for a later
  attempt — a sibling EXECUTION node under the same task (§4.3).
- **Hover:** id, attempt, status, real duration computed from
  `started_at`/`finished_at` **only when both exist and are parseable**; never a
  live or estimated duration.
- **Click:** select; open the execution timeline tab.
- **Expands:** yes, to children.
- **Provenance-traceable:** yes, when provenance records exist.

### SANDBOX

- **Represents:** the execution boundary that constrained one execution.
- **Created by:** **NOT IMPLEMENTED.** No sandbox component, no execution path.
- **Display metadata (when it exists):** see Part 13, including the explicit
  distinction between resource limits, process restrictions, filesystem
  restrictions, network restrictions, and container isolation.
- **Must remain hidden:** absolute host paths; the user's home directory layout;
  anything outside the project root.
- **Possible statuses:** whatever the core records per execution.
- **Hover / click / expand:** limits panel; select; expand to per-execution
  enforcement facts.
- **Provenance-traceable:** intended yes.
- **Hard rule (from `docs/THREAT_MODEL.md` non-guarantee 1):** on this Windows
  host a subprocess sandbox is **resource and file-scope control, not container
  or VM isolation**, and residual risk for B3/C4/C5 is **Hi**. The Map must not
  use isolation-grade visual language (a "sealed" container, a shield implying
  kernel isolation) for a mechanism that does not provide it.

### ARTIFACT

- **Represents:** a file or text output produced by one execution.
- **Created by:** an `artifacts` row (SCHEMA ONLY).
- **Display metadata:** `id`, `name`, `kind`, `size_bytes` (verbatim; may be
  negative because there is no constraint), `checksum`, `created_at`, and
  `relative_path` **only after the core has validated it** — today no writer or
  validator exists, so the stored value must be shown as an unvalidated,
  unverified data value, never as a safe path.
- **Must remain hidden:** `content` by default; absolute host paths; any content
  classified as internal-only or security-sensitive.
- **Possible statuses:** none stored. Artifacts have no status column; the UI must
  not invent one (e.g. no "valid" badge).
- **Transitions:** to VERIFICATION.
- **Hover:** metadata and checksum, with an explicit note that checksum
  verification is not implemented (`docs/ARCHITECTURE_RECONCILIATION.md` §4,
  D4/provenance integrity absent).
- **Click:** select; open metadata; content is a separate, explicit action.
- **Expands:** yes, to metadata and to opt-in content.
- **Provenance-traceable:** yes, when the linkage exists.

### VERIFIER (and the verification result it produces)

- **Represents:** a deterministic acceptance check over an execution's output.
- **Created by:** a `verifications` row (SCHEMA ONLY). No verifier code exists.
- **Display metadata:** `id`, `verifier` (the verifier's identity as recorded),
  `result` (verbatim), `created_at`; `detail_json` only under the Part 9/21
  classification rules.
- **Must remain hidden:** verifier source; internal predicate implementations that
  would let a caller reverse-engineer how to satisfy a check without satisfying
  it honestly.
- **Possible statuses:** the stored `result` string, with no `CHECK` constraint.
  The documented vocabulary is PASS/FAIL. Any other stored value renders as
  **unrecognized** (§4.5). `INCONCLUSIVE` is **not** currently a defined value;
  see Part 10 and C-03.
- **Transitions:** to RESULT on a recorded pass, to FAILURE on a recorded fail.
- **Hover:** verifier identity, result, timestamp, and the affected artifact or
  result reference.
- **Click:** select; open the evidence panel defined in Part 10.
- **Expands:** yes, to evidence, subject to classification.
- **Provenance-traceable:** yes.
- **Hard rule:** no client-side control may set, clear, or re-run a verdict
  (principle 5). "Re-verify" is a **core request**, not a UI action, and is not
  specified here because the core does not offer it.

### FAILURE

- **Represents:** one classified failure of an execution.
- **Created by:** a `failures` row (SCHEMA ONLY).
- **Display metadata:** `id`, `category` (verbatim; no vocabulary is defined
  anywhere, so the UI must not present a fixed taxonomy as authoritative),
  `created_at`, and `diagnosis` as untrusted text.
- **Must remain hidden:** `detail_json` until a redaction/allowlist decision
  exists; internal diagnostic content not needed to understand the failure.
- **Possible statuses:** none stored.
- **Transitions:** to RECOVERY.
- **Hover / click / expand:** summary; select; expand to diagnosis and detail.
- **Provenance-traceable:** yes.
- **Security consideration:** the threat model treats a diagnosis derived from
  untrusted artifact content as potentially attacker-influenced
  (`docs/THREAT_MODEL.md` B1/B3). It is rendered as data.

### RECOVERY

- **Represents:** one bounded replan cycle.
- **Created by:** a `recovery_attempts` row (SCHEMA ONLY).
- **Display metadata:** `id`, `attempt_no` (verbatim), `outcome` (verbatim),
  `created_at`; the configured bound labelled explicitly as
  configured-not-enforced.
- **Must remain hidden:** `new_plan_json` raw payload by default; internal
  diagnosis internals.
- **Possible statuses:** the stored `outcome` string; the only value any future
  default would write is `'pending'`.
- **Transitions:** to a recovered-plan node, then to the next EXECUTION sibling.
- **Hover / click / expand:** attempt number, outcome, and the bound; select;
  expand to the new plan payload.
- **Provenance-traceable:** yes.
- **Hard rule:** the UI must not present a recovery node as autonomous agency.
  Bounded recovery is a recorded counter against `max_recovery_attempts`; the
  visual language must make the bound and the termination reason legible (Part
  11).

### REPLAN

- **Represents:** the decision to produce a renewed plan payload after a
  classified failure.
- **Created by:** **no dedicated record.** It is inferable only from a
  `recovery_attempts` row carrying `new_plan_json` (SCHEMA ONLY). The Map must
  treat REPLAN as a **derived annotation on a recovery node**, not as a node with
  independent state, until the core defines a plan-revision record (C-05).
- **Display metadata:** which recovery attempt produced it.
- **Must remain hidden:** raw plan payload by default.
- **Possible statuses:** none of its own.
- **Transitions:** to the recovered-plan node.
- **Hover / click / expand:** as a label, non-interactive beyond selection.
- **Provenance-traceable:** yes, through its recovery attempt.

### RESULT

- **Represents:** a finalized outcome. Per `SYSTEM_SPECIFICATION.md` stage 17, a
  final result exists only after a recorded verification PASS, or as a bounded,
  recorded failure.
- **Created by:** **NOT IMPLEMENTED.** No result table, no result service, and no
  finalize path exists. The orchestrator that would enforce the invariant is a
  placeholder (`docs/THREAT_MODEL.md` B5).
- **Display metadata (when it exists):** id, task reference, the verification
  event that authorized finalization, timestamps, and the failure record if the
  result is a bounded failure.
- **Must remain hidden:** raw execution output by default; internal diagnostics.
- **Possible statuses:** the recorded outcome.
- **Transitions:** to PROVENANCE (always); to nothing else.
- **Hover:** result identity, its authorizing verification, and its timestamp.
- **Click:** select; trigger the provenance trace defined in Part 9.
- **Expands:** yes, into its chain.
- **Provenance-traceable:** yes — this is the primary trace entry point.
- **Hard rule:** a RESULT node must never appear without a referencing recorded
  verification event. Rendering a result because a task "looks done" is a
  fabricated result and violates `docs/DECISIONS.md` ("No fabricated results").

### PROVENANCE

- **Represents:** the append-only audit trail for a task or execution.
- **Created by:** `provenance_events` rows. One producer exists today
  (`AuthService._record_registration`, `event_type='user.registered'`,
  `actor='auth'`). All lifecycle event types are PLANNED (Phase 14).
- **Display metadata:** `id`, `event_type`, `actor` (verbatim), `created_at`,
  and `detail_json` **only** under an approved redaction/allowlist policy
  (D-08). Currently `detail_json` is an unredacted `json.dumps()` of an arbitrary
  dictionary, so the default rendering is **metadata only, detail withheld**.
- **Must remain hidden:** full prompts, tool inputs, generated code, and any
  secret-bearing detail; the other user's identity in a cross-task view.
- **Possible statuses:** none. Events are immutable; there is no status and the
  UI must not offer edit, acknowledge, or dismiss.
- **Transitions:** the event stream itself. `task_id`/`execution_id` are nullable
  and set to `NULL` on task deletion, so **orphan events are normal** and must be
  rendered as orphans, not as errors and not as belonging to some other task.
- **Hover:** event type, actor, timestamp.
- **Click:** select; show the event and its links.
- **Expands:** yes, to detail, when permitted by classification.
- **Provenance-traceable:** it is the provenance.
- **Actor vocabulary caution:** `SYSTEM_SPECIFICATION.md` §5 states actors are the
  fixed roles user/planner/executor/verifier/recovery, but the only existing
  producer writes `actor='auth'`. The Map must render the stored string and label
  unknown actors as unclassified rather than forcing them into the documented
  five. Recorded as **C-06**.

## 5.3 Node summary

| Node | Backend record | Record status | Traceable | Interactive expansion |
|---|---|---|---|---|
| TASK | `tasks` | IMPLEMENTED (writer) | root | yes |
| PLAN | `plans` | SCHEMA ONLY | yes | yes |
| PLAN STEP | `plan_steps` | SCHEMA ONLY | intended | yes |
| AUTHORIZATION | none | NOT IMPLEMENTED | intended | no |
| TOOL | none | NOT IMPLEMENTED | intended | yes |
| EXECUTION | `executions` | SCHEMA ONLY | yes | yes |
| SANDBOX | none | NOT IMPLEMENTED | intended | yes |
| ARTIFACT | `artifacts` | SCHEMA ONLY | yes | yes |
| VERIFIER | `verifications` | SCHEMA ONLY | yes | yes |
| FAILURE | `failures` | SCHEMA ONLY | yes | yes |
| RECOVERY | `recovery_attempts` | SCHEMA ONLY | yes | yes |
| REPLAN | derived from `recovery_attempts` | SCHEMA ONLY | via recovery | no |
| RESULT | none | NOT IMPLEMENTED | yes | yes |
| PROVENANCE | `provenance_events` | PARTIALLY IMPLEMENTED — `ProvenanceRepo.record()` plus one producer in `AuthService`; the `atlas/provenance/` package itself is a placeholder | self | yes |

## 5.4 Nodes that must never be created by the UI layer

A node may not be created, removed, merged, split, reordered, or renamed by any
user action. Specifically forbidden: "add step" (planner's job), "retry
execution" (orchestrator's job), "mark verified" (verifier's job), "mark failed"
(classifier's job), "dismiss failure", "delete artifact", "edit event", "collapse
a failed attempt into a successful one", and "create task node" from a form
field that is not a real `tasks` insert.

---

# PART 6 — Edges and transitions

## 6.1 Precondition

An edge is drawn only when **both** endpoint records exist. The briefing's edge
list assumes records that do not exist. This section therefore specifies each
edge's trigger and, where the current schema cannot support the briefed
relationship, records the constraint rather than inventing a link.

## 6.2 Edge specifications

Fields per edge: meaning; source; destination; triggering backend event; visual
behavior; interaction behavior.

| # | Edge | Meaning | Source record | Destination record | Triggering backend event | Visual behavior | Interaction behavior |
|---|---|---|---|---|---|---|---|
| E1 | TASK → PLAN | the task's structured decomposition exists | `tasks.id` | `plans.task_id` | a `plans` row committed | solid edge from task to plan; plan appears once | click plan → open plan tab |
| E2 | PLAN → PLAN STEP | ordered steps of that plan | `plans.id` | `plan_steps.plan_id` | `plan_steps` rows committed | ordered chain in stored `position` order; unsorted positions shown as unordered | click step → step detail |
| E3 | PLAN STEP → TOOL | the step selects a registered capability | `plan_steps.tool_name` | tool registry entry | a registry lookup that resolves the name | dashed "selects" edge; unresolved names render as an unresolved stub, not a hidden edge | hover → declared policy summary |
| E4 | TOOL → EXECUTION | that capability was dispatched | tool id | `executions.id` | a tool dispatch recorded by the orchestrator | solid edge labeled with the dispatch timestamp | hover → dispatch metadata |
| E5 | EXECUTION → ARTIFACT | outputs produced by the attempt | `executions.id` | `artifacts.execution_id` | an `artifacts` row committed | edge per artifact; size shown as a count of bytes only if the stored value is non-negative | click → artifact metadata; content is a separate action |
| E6 | ARTIFACT → VERIFICATION | the artifact was an input to a check | `artifacts.id` | `verifications.execution_id` | a `verifications` row referencing the same execution | edge labeled with verifier identity | click → evidence panel |
| E7 | VERIFICATION → RESULT | a recorded PASS authorized finalization | `verifications.id` | result record | a finalized result referencing that PASS | emphasized edge; the only edge that may carry a "result-bearing" marker | click → result |
| E8 | VERIFICATION → FAILURE | a recorded FAIL produced a failure record | `verifications.id` | `failures.execution_id` | a `failures` row committed for the same execution | emphasized edge in the failure direction, visually distinct from E7 | click → failure detail |
| E9 | FAILURE → RECOVERY | the failure entered bounded recovery | `failures.id` | `recovery_attempts.execution_id` | a `recovery_attempts` row committed | edge labeled with `attempt_no` | click → recovery attempt |
| E10 | RECOVERY → REPLAN | a renewed plan payload was produced | `recovery_attempts.id` | derived annotation on the same recovery node | `new_plan_json` present | annotation, not a node, until a plan-revision record exists (C-05) | select the annotation |
| E11 | REPLAN → PLAN | the renewed plan re-enters validation | derived replan annotation | `plans.id` (or a future revision record) | plan re-validation | rendered as an edge to an explicitly labeled **recovered-plan** node sourced from `recovery_attempts`, never as an ordinary second PLAN (C-05) | click → compare payload with the original plan, read-only |
| E12 | RESULT → PROVENANCE | the result's audit chain | result record | `provenance_events` | events recorded for the task/execution | the chain edge set used by Part 9 | click → provenance explorer |
| E13 | EXECUTION → EXECUTION (next attempt) | a later attempt under the same task | `executions.attempt = n` | `executions.attempt = n+1` | a new `executions` row committed | sibling-to-sibling edge, clearly separated from E9/E10/E11 so the loop is legible | click → compare the two attempts |
| E14 | TASK → PROVENANCE | the task's audit stream | `tasks.id` | `provenance_events.task_id` | any event recorded for the task | spine edge; null task references render as orphans, not as attached to another task | click → event stream |

## 6.3 Edge integrity rules

1. **No inferred edges.** If the schema does not record the relationship, the Map
   does not draw it. Specifically, there is currently **no column** linking a
   `plan_steps` row to the `executions` row that consumed it, and none linking an
   `artifacts` row to a specific `verifications` row. E4 and E6 therefore require
   Phase 09/12/13 to add those linkages, or to accept a weaker
   execution-scoped reading. Until then the Map must not draw a
   step→execution or artifact→verification edge as if it were recorded fact.
   Recorded as **C-07** and decision **D-10**.
2. **No visual ordering claims beyond stored values.** Edge direction must match
   the recorded relationship, not a plausible story. An edge from FAILURE to
   RESULT must never be drawn because the timestamps happen to sort that way.
3. **No synthetic edges.** No "inferred" or "likely" edges, no confidence-weighted
   edges, no edges created by layout heuristics. If a relationship is not
   recorded, it is not drawn.
4. **Edge deletion is forbidden.** Hiding an edge for readability is allowed;
   deleting, merging, or rewriting one is not (principle 6).
5. **Orphan handling.** Events with `NULL` task/execution references are drawn in
   a separate "unlinked events" region, clearly labeled, never auto-attached to a
   task by temporal proximity.
6. **Edge animation** obeys Part 8: an edge may animate only when the transition it
   represents has been recorded.

---

# PART 7 — Cursor-reactive interaction

Interaction exists to make recorded relationships legible. It never invents
state, and it never becomes the only route to information (Part 18).

## 7.1 Hover

On node hover:

1. A concise **information panel** appears with: node type, database id, the raw
   status/result value, and the 2–5 most relevant timestamps. No wall of text.
2. **Edges incident to the hovered node** are highlighted. Edges two hops away
   may be dimmed to a "related" level. All other nodes may be de-emphasized to
   roughly 40–60% opacity.
3. **Non-negotiable:** de-emphasis must never make a node's status unreadable,
   and must never hide a warning, denial, or failure indicator. Faded ≠
   declassified.
4. Hover content is identical in substance to what a click reveals, minus the
   detail panel. Hover is not a place where more sensitive information appears
   than on click.
5. Hover over an **empty region** shows nothing. An empty region is not a node,
   and the Map must not report a "system idle" or "agent thinking" state there.

## 7.2 Focus (keyboard parity)

- Every node is a focusable element in DOM order, reachable by keyboard.
- Focusing a node is **equivalent** to hovering it: the same panel, the same edge
  highlighting, the same de-emphasis.
- Visible focus indicators must meet the contrast requirement in Part 18 and
  must not rely on color alone.
- A roving-tabindex pattern is acceptable for large graphs; the requirement is
  that all nodes remain reachable without a pointer, and that the current focus
  is always announced.
- Focus must not be trapped. A user can always leave the graph.

## 7.3 Click / activate

Click (or Enter/Space on a focused node) may:

- **select** the node — a persistent highlight with the detail panel open;
- **open detail** for that record in the detail region (not a modal that hides
  context; modals are permitted only for destructive confirmations);
- **highlight provenance** — for RESULT, EXECUTION, ARTIFACT, and VERIFICATION,
  selection highlights the recorded chain (Part 9);
- **show related execution information** — sibling executions for the same task,
  with real `attempt` values.

Selection is **view state only**. It is not stored as system state, is not shared
between users, and never becomes an input to any core operation.

## 7.4 Provenance highlighting

Selecting a RESULT highlights the chain backward, using recorded links only:

```
RESULT ← VERIFICATION ← ARTIFACT ← EXECUTION ← TOOL ← PLAN STEP ← PLAN ← TASK
```

Current implementability, stated honestly:

| Link | Recordable today? |
|---|---|
| RESULT → VERIFICATION | No result record exists (NOT IMPLEMENTED) |
| VERIFICATION → ARTIFACT | No linking column exists (C-07) |
| ARTIFACT → EXECUTION | Yes, via `artifacts.execution_id` (SCHEMA ONLY) |
| EXECUTION → TOOL | No dispatch record exists (NOT IMPLEMENTED) |
| TOOL → PLAN STEP | Only the `plan_steps.tool_name` string; no verified registry resolution (NOT IMPLEMENTED) |
| PLAN STEP → PLAN | Yes, via `plan_steps.plan_id` (SCHEMA ONLY) |
| PLAN → TASK | Yes, via `plans.task_id`, unique (SCHEMA ONLY) |
| TASK → provenance events | Yes, via `provenance_events.task_id` (PARTIALLY IMPLEMENTED) |

So the full chain is a **target architecture**, not a current capability. The Map
must render only the links that exist and must show the rest as explicitly
unavailable rather than drawing a plausible continuous line. A partially traced
result must **look** partially traced.

## 7.5 Edge interaction

Hovering or selecting an edge explains the relationship without guesswork. The
edge panel states: edge identity (E1–E14), plain-language meaning, source record
and id, destination record and id, the recorded trigger, and the recorded
timestamp of the underlying event. Where the relationship is *derived* (E10,
E11) the panel says so explicitly.

Clicking an edge selects both endpoints and highlights the pair. It must not
offer a "delete edge", "reassign", or "reorder" control.

## 7.6 Expansion

Complex nodes expose additional metadata on demand, in place, in this order:
core identifiers and timestamps → status/result → relationships → bounded detail
payloads (redacted, size-capped) → opt-in artifact content. Each expansion level
is explicitly requested, so a user can be sure that what they have not expanded
has not been silently withheld for security reasons. A panel that is truncated
for length must say **truncated** and state the real size.

## 7.7 Tooltips

Tooltips carry technical facts: identifiers, statuses, timestamps, counts,
relationships. They do not carry encouragement, flavor, tutorial text, or
animated filler. A tooltip must never be the only place a piece of information
exists (Part 18); it is a convenience layer over the detail panel and the
accessible name.

## 7.8 Interaction prohibitions

- No drag-to-reparent, no drag-to-reorder, no drag-to-delete. Dragging may pan or
  zoom only.
- No in-canvas editing of any kind. The Map is read-only except for the
  navigation it links to.
- No double-click to "open" something that requires a core action.
- No context menu offering privileged operations.
- No interaction that reports success for a state the core did not record.

---

# PART 8 — Animation model

## 8.1 The single rule

> An animation is a rendering of a transition that the core has already
> recorded. If no record exists, there is no animation.

Animations are therefore a **read-side effect of recorded state**, not a
simulation. Every animation is triggered by data the Map received, and stopping
the animation never changes data.

## 8.2 Event-to-animation mapping

Each mapping requires the named record. All of these records are SCHEMA ONLY or
NOT IMPLEMENTED except task creation, so today **only the first row can animate**.

| Recorded event | Required record | Animation | Forbidden embellishment |
|---|---|---|---|
| `TASK CREATED` | `tasks` row | task node appears with its real `created_at` | no "spawning" effect implying more than one task |
| `PLAN CREATED` | `plans` row | plan node materializes from the task | no "generating" shimmer implying live model inference |
| `PLAN VALIDATED` | `plans.validated` change **with a record of the validator run** | validation marker appears | no progress bar for validation; it is a single recorded outcome |
| `TOOL STARTED` | a recorded dispatch with `started_at` | edge activation from tool to execution | no pulsing "tool is working" loop |
| `TOOL COMPLETED` | dispatch completion with `finished_at` | dispatch edge resolves | no fake streaming output |
| `ARTIFACT CREATED` | `artifacts` row | artifact node appears with real size/checksum | no progress-from-zero for a file that already exists |
| `VERIFICATION STARTED` | a verifier-run record with a start time (does not exist; the schema has only `created_at` on the result row) | verifier marker activates | no spinner implying ongoing verification unless a real run record exists |
| `VERIFICATION PASSED` | `verifications.result` = recorded pass | success transition | no confetti, no glow implying more certainty than a predicate provides |
| `VERIFICATION FAILED` | `verifications.result` = recorded fail | failure branch activates | no alarm theater implying severity beyond the record |
| `FAILURE CLASSIFIED` | `failures` row | failure node appears with `category` verbatim | no invented category labels |
| `RECOVERY STARTED` | `recovery_attempts` row with `attempt_no` | recovery path activates, attempt counter increments to the stored value | no "the system is trying hard" framing |
| `REPLAN` | `recovery_attempts.new_plan_json` present | recovered-plan annotation appears, labeled as derived | no rewriting of the original plan node |
| `FINAL RESULT` | a finalized result with a referencing PASS | result node activates | no "mission accomplished" messaging |
| Terminal stop | recorded terminal condition | motion stops | no idle animation afterwards |

## 8.3 Explicitly forbidden animation

- "AI thinking" loops, pulsing brain nodes, or any motion that implies cognition.
- Fake token streams or typewriter effects over model output.
- Fake computation: spinners, progress rings, or percentage counters with no
  recorded basis.
- Fake telemetry: drifting graphs, random metrics, simulated CPU/network graphs.
- Fake execution: a spinner while nothing is executing.
- Fake progress: linear interpolation toward an outcome the core has not
  recorded.
- Idle "breathing" or ambient motion on a static graph. If nothing changed, the
  picture is still.
- Any easing curve whose duration is proportional to an unmeasured quantity.

## 8.4 Update cadence and honesty about time

Real-time streaming is **not** assumed. `docs/TECHNOLOGY_STACK.md` has no
streaming, websocket, or message-bus component, and the system is local with
`max_concurrent_executions=1` by default. Therefore:

- The Map's baseline update mechanism is **explicit refresh or bounded polling**
  of stored state (§17.4), and the current mode must be visible in the UI
  ("showing data as of \<timestamp\"").
- If a future phase adds streaming, it streams **stored events**, and the
  animation still requires a record.
- Any "live" indicator must state its last-update time. A stale view must be
  visibly stale, never silently presented as current.

## 8.5 Reduced motion

`prefers-reduced-motion` (Part 18) replaces every transition with an immediate
state change plus a brief non-motion highlight. No information may be conveyed
only by motion, in either mode.

---

# PART 9 — Provenance experience

## 9.1 The trace

```
RESULT
  └─ VERIFICATION EVENT   (the recorded PASS that authorized finalization)
      └─ ARTIFACT         (what was checked)
          └─ EXECUTION    (the attempt that produced it)
              └─ TOOL INVOCATION
                  └─ PLAN STEP
                      └─ PLAN
                          └─ TASK
                              └─ PROVENANCE EVENT STREAM (all events, in order)
```

Each hop exposes: record id, recorded timestamps, status/result verbatim, and the
relationship that justifies the hop. Where a hop is not recorded, the trace stops
there and says which record is missing (see the honesty table in §7.4).

## 9.2 Information classification (mandatory before provenance detail is shown)

Provenance detail is currently an unredacted `json.dumps()` of an arbitrary
caller-supplied dictionary with no allowlist, no size cap, and no redaction
(`docs/STORAGE_REVIEW.md` §8, M-5). Three tiers are therefore required, and the
Map must default to tier 1:

| Tier | Contents | Default visibility |
|---|---|---|
| **User-safe** | event id, `event_type`, `actor`, `created_at`, related record ids and types, statuses, checksums, byte sizes, durations derived from real timestamps, and a fixed allowlist of structural detail keys | visible |
| **Internal diagnostics** | verbose detail fields, retry internals, timing breakdowns, raw tool stdout/stderr, unclassified `detail_json` keys | hidden by default; requires an explicit disclosure control **and** an approved policy (D-08) |
| **Security-sensitive** | raw session tokens or digests, password hashes, `application_secret_key`, absolute host paths outside the project, other users' identifiers, full model prompts, generated code | **never** rendered in any tier; the Map has no control that reveals it |

Non-negotiable: the presence of data in the database is not a reason to display
it. `docs/THREAT_MODEL.md` D2 states artifact content is stored but not echoed in
logs or UI summaries; that posture is adopted here for provenance detail.

## 9.3 Provenance exploration UX

- **Ordered stream.** Events render in `created_at` order with monotonic
  sequence, since `created_at` is second-resolution text
  (`atlas/util.py::utcnow_iso` uses `timespec="seconds"`) and events within the
  same second are not strictly ordered by time. The stable `id` is the tiebreaker,
  and the UI should say so rather than implying precise sub-second ordering.
- **Filtering** by `event_type`, `actor`, and time range — client-side over the
  authorized set.
- **Search** is scoped to the authorized set only. SQLite FTS is the stack's
  lightweight search mechanism, but no FTS table exists today; the Map must not
  promise full-text search over provenance.
- **Orphans** (`task_id` and `execution_id` both `NULL`, e.g. the current
  `user.registered` event) render in a labeled "unlinked events" region.
- **Read-only.** No acknowledge, annotate, edit, or delete control exists.
- **Export** for reports is allowed and desirable (it serves research), but the
  export must contain the same tiers the viewer was permitted to see, plus a
  header recording the export time, the record count, and the schema version
  (`SCHEMA_VERSION = 1`) so a reader can tell what they are looking at.

## 9.4 Chain integrity honesty

`docs/THREAT_MODEL.md` D4 records that provenance integrity is **append-only by
policy only**, with no checksum chain, and residual risk because an operator with
database access can still edit the file. The provenance experience must therefore
never claim tamper-evidence. It may state that events are append-only by
application policy and that the database file is host-owned. It must not display
"verified chain", "tamper-proof", or an integrity badge, because no such control
exists.

---

# PART 10 — Verification visualization

## 10.1 The three-valued requirement, handled honestly

The briefing requires PASS / FAIL / INCONCLUSIVE to be visually distinct and
explicitly warns against collapsing INCONCLUSIVE into PASS. The authoritative
position:

- `SYSTEM_SPECIFICATION.md` §5 defines `verifications.result` as PASS/FAIL.
- `atlas/storage/migrations.py` defines `result TEXT NOT NULL` with **no** `CHECK` constraint,
  so the database can already hold any string.
- No verifier exists, so no value has ever been written.

Therefore: the UI **must** support three distinct visual treatments and **must
not** collapse any value into another. But it must not *assert* that
`INCONCLUSIVE` is a supported outcome either. The rule from §4.5 applies:

| Stored value | Treatment |
|---|---|
| `PASS` | pass treatment |
| `FAIL` | fail treatment |
| `INCONCLUSIVE` (or any other non-PASS/FAIL value) | a **third, visually distinct** "other / unrecognized outcome" treatment — explicitly neither pass nor fail |
| `NULL` or missing row | "no verification recorded" |

When the core later defines `INCONCLUSIVE` as a first-class outcome, the third
treatment simply gains a name. Until then, the UI must not label an unknown value
"inconclusive", because that would invent a semantic the core has not defined.
Recorded as C-03 / D-05.

## 10.2 On verification failure, show

For each recorded `verifications` row with a non-pass result:

- **Verification identity** — `verifier` exactly as recorded, plus the record id.
- **Affected artifact/result** — the linked artifact or result where a link
  exists; otherwise "no artifact linkage recorded" (no fabrication; see C-07).
- **Failed predicate** — from `detail_json`, **only** if a key is on the approved
  allowlist (Part 9.2). Otherwise "predicate detail withheld by policy."
- **Observed value** — where safe, size-capped, and redacted.
- **Expected condition** — where safe.
- **Failure category** — from the linked `failures.category`, **verbatim**. No
  taxonomy is defined in the schema or the specification, so the UI must not map
  categories into a fixed severity scheme.
- **Recovery status** — whether a `recovery_attempts` row exists for the
  execution, with `attempt_no` and `outcome` verbatim (Part 11).

## 10.3 Prohibitions

- **No client-side verdict.** The frontend must not compute, re-run, infer, or
  override a verification. There is no "mark as verified" affordance, ever.
- **No re-verify button** until the core exposes a re-verification operation. A
  UI that offers one implies a capability that does not exist.
- **No weakening language.** A PASS must be described as "the recorded verifier
  returned PASS for this record", with the verifier's identity visible, because
  `docs/THREAT_MODEL.md` B6 and non-guarantee 7 state verification is only as
  strong as its predicates and verifier strength is itself an experimental
  variable. A green badge with no verifier identity overstates the evidence.
- **No collapsing.** A fail must never be rendered as a neutral state, a warning
  as a pass, or a missing record as a pass.

---

# PART 11 — Recovery visualization

## 11.1 Bounded recovery must be visibly bounded

```
VERIFY → FAIL → DIAGNOSE → RECOVERY ATTEMPT 1 → RE-EXECUTE → VERIFY → PASS
VERIFY → FAIL → DIAGNOSE → RECOVERY ATTEMPT 1 → RE-EXECUTE → VERIFY → FAIL
                                    ↓
                        RECOVERY ATTEMPT 2 … up to the recorded bound
                                    ↓
                        BOUND REACHED → FAILED (bounded, recorded)
```

The UI must display, for every recovery sequence:

| Element | Source | Rule |
|---|---|---|
| **Attempt number** | `recovery_attempts.attempt_no` | verbatim; duplicates or out-of-range values render as recorded and are flagged as unrecognized, never renumbered |
| **Maximum attempts** | `max_recovery_attempts` (default 2, range 1–10) | labeled **"configured bound — not enforced by current code"**, because the configuration review records it as declared-but-unenforced (`docs/CONFIGURATION_REVIEW.md` §3) |
| **Failure reason** | `failures.category` + `diagnosis` | verbatim category; diagnosis is untrusted text |
| **Recovery status** | `recovery_attempts.outcome` | verbatim; the default value in schema is `'pending'` |
| **Final termination reason** | the recorded terminal condition | must be shown; the UI must not declare a task "done" or "abandoned" without a record |

## 11.2 Boundedness must be structural, not decorative

- The attempt counter is always visible while a recovery sequence is displayed.
- The bound is stated in words ("at most N recovery attempts, as configured"),
  not only as a number in a corner.
- When the recorded attempts reach the configured bound, the UI states that the
  sequence is bounded and shows the recorded termination reason.
- If the stored `attempt_no` exceeds the configured bound, the UI must show the
  discrepancy as a **data-integrity observation**, not silently clamp it, and
  must not claim the bound held.

## 11.3 No infinite-autonomy framing

- No looping, spinning, or "still trying" visual for a recovery sequence that has
  no further recorded attempt.
- No anthropomorphic language ("the agent is thinking", "it is trying to fix it").
  Recovery is a bounded counter over recorded rows.
- No auto-retry control in the UI. Retry is an orchestrator operation
  (NOT IMPLEMENTED).
- A stalled sequence (no new `recovery_attempts` row, no status change) must be
  shown as **stalled or unknown**, with the last recorded timestamp — not as
  ongoing progress. `docs/THREAT_MODEL.md` lists no queue or background scheduler,
  and none exists.

---

# PART 12 — Tool permission visualization

## 12.1 Current state

Tools do not exist. There is no `tools` table, no `tool_permissions` table, no
registry, and no policy layer (Phase 09; `docs/STORAGE_REVIEW.md` §2;
`docs/ARCHITECTURE_RECONCILIATION.md` §2). Every field below is taken from the
planned entity definitions in `SYSTEM_SPECIFICATION.md` §5 and is **PLANNED**.

## 12.2 Metadata display matrix (future)

| Field | Planned source | Visibility rule |
|---|---|---|
| Tool id | `tools.id` | user-visible |
| Name | `tools.name` | user-visible |
| Description | `tools.description` | user-visible; treat as untrusted text if model-generated |
| Permission requirement | `tool_permissions` presence for the caller | show as **granted / not granted**; absence equals denial (deny-by-default) |
| Filesystem policy | tool policy | user-visible as a **declared policy**, never as an enforced fact, until the sandbox enforces it |
| Network policy | tool policy | same rule; must state "declared" vs "enforced" |
| Timeout | tool policy and/or `max_subprocess_seconds` | show the value and whether it is enforced |
| Output limit | tool policy and/or `max_artifact_bytes` | show the value and whether it is enforced |
| Sandbox requirement | tool policy | show as a requirement, not as a satisfied condition |
| Input schema | `tools.input_schema` | user-visible, read-only |
| Enabled state | `tools.enabled` | user-visible |
| Implementation source, environment values, credentials, host paths | — | **never displayed** |

## 12.3 Hard rules

- **The UI never grants a permission.** No "grant", "allow", "enable", or
  "trust this tool" control exists in this specification, at any point, in either
  surface. Permission grants are auditable core operations
  (`SYSTEM_SPECIFICATION.md` §5: "absence = denial; grants are auditable and
  revocable"), and `docs/STORAGE_REVIEW.md` §12 requires role/permission/grant/
  revocation/audit requirements to be defined before they are added. A UI that
  can grant a permission is a UI that has become a security boundary, violating
  principles 2 and 3.
- **A click is never consent.** Hovering, focusing, or expanding a tool node
  changes nothing.
- **Declared is not enforced.** Every policy value must be labeled with whether
  the core enforces it. Today the answer is "not enforced" for every execution
  bound.
- **Deny-by-default display.** A missing grant is a normal, expected state to be
  shown — not an error, and not hidden.
- **No capability inflation.** The registry view must not imply that a tool is
  safe, trusted, or verified because it is listed. Listing is not approval
  (`docs/THREAT_MODEL.md` B2: policy quality, not magic, is the limit).

---

# PART 13 — Sandbox visualization

## 13.1 Current state, stated without softening

There is no sandbox component, no execution path, and no subprocess call site in
the codebase (`docs/ARCHITECTURE_RECONCILIATION.md` §3.3, §6). The current
system is safe against generated-code attack **only because it executes nothing**,
and the reconciliation document is explicit that this is not a control.

The planned posture on this host is a subprocess with resource, time, and
project-scoped filesystem limits. `docs/environment-reconnaissance.md` records
that Docker is not installed and WSL has no distributions.

## 13.2 Mandatory distinction, and it must be visible in the UI

The Map and the workspace must distinguish these five concepts and must never
merge them into one "sandboxed" badge:

| Concept | Meaning | Status on this host |
|---|---|---|
| **Resource limits** | CPU, memory, wall-clock, and output-size bounds | **Configured, not enforced** (`Settings` declares `cpu_limit_cores`, `memory_limit_mb`, `max_execution_seconds`, `max_subprocess_seconds`, `max_artifact_bytes`; no call site consumes them) |
| **Process restrictions** | What the child process may do as a process (no shell string execution, argument-list invocation only) | **PLANNED** (Phase 09/10 design rule for C2) |
| **Filesystem restrictions** | Confinement of reads/writes to a project-scoped root; rejection of absolute paths and `..` traversal | **NOT IMPLEMENTED**. No path confinement exists; `artifacts.relative_path` is an unvalidated column |
| **Network restrictions** | Denial or allowlisting of network access from executed code | **NOT IMPLEMENTED**. Nothing executes |
| **Container isolation** | Kernel/namespace-level isolation from the host | **NOT AVAILABLE**. Docker is not installed; WSL has no distributions |

## 13.3 Prohibited claims

The UI must not describe the current or planned Windows subprocess approach as
container isolation, VM isolation, a security boundary, a jail, or "sealed". It
must not use visual language implying kernel-level separation (a hermetic
container glyph, a hard boundary ring, a shield). `docs/THREAT_MODEL.md`
non-guarantee 1 and residual ratings for B3, C4, and C5 are **Hi** on this host;
the UI is required to be consistent with that, and the workspace should surface
the residual risk in plain text on the sandbox panel rather than only in
`SECURITY.md`.

## 13.4 Future sandbox panel content

Only from recorded values: execution status; workspace identifier as the core
records it (never an absolute host path); the applicable timeout; the resource
limits in force; the declared network policy; the artifact boundary; and cleanup
status. Each item labeled **enforced** or **declared**. Any value the core does
not record is shown as "not recorded" — never filled in with the configured
default as though it were observed.

---

# PART 14 — Practical dashboard

## 14.1 The rule for every number

> Every displayed value must be the result of a query over stored records, and
> the dashboard must be able to state which query produced it.

No derived-looking metric without a query, no ratio without numerator and
denominator, no "trend" without at least two real data points, and no number
whose underlying records were never created.

## 14.2 Dashboard contents and their current availability

| Tile | Definition (query over) | Available today? |
|---|---|---|
| Active tasks | `tasks` where `status` not in a recorded terminal set | Partially: only `'pending'` is ever written, so "active" is currently every task; the tile must say so rather than implying an active execution pipeline |
| Completed tasks | `tasks` by recorded terminal status | No — no terminal status is ever written |
| Failed tasks | `tasks` by recorded failure status | No |
| Tasks by recorded status | `GROUP BY tasks.status` over raw values | Yes, and the most honest tile available today |
| Verification failures | `COUNT` of `verifications` rows with a non-pass `result` | No — no rows are ever written |
| Recovery attempts | `COUNT` / `MAX(attempt_no)` over `recovery_attempts` | No |
| Recent executions | latest `executions` rows | No |
| Recent artifacts | latest `artifacts` rows with size and checksum | No |
| Provenance events (recent) | latest `provenance_events` for the user | Partially — only `user.registered` events exist today |
| Benchmark status | `evaluation_runs` | No — table empty, no harness |
| Experiment status | no entity exists | No — must not be invented |
| Security events | authentication-related events | Almost none: only `user.registered` is recorded. Login, logout, lockout, and password change are **not** recorded (`docs/AUTHENTICATION_REVIEW.md` L-03) |
| Locked account (own) | `users.locked_until` for the viewer | Yes for the viewer's own account only |
| Effective configuration | `Settings.safe_dump()` | Yes, and the only tile that shows real runtime configuration |

Every unavailable tile must render an explicit "not implemented — owned by phase
N" state, per the standing practice established in the earlier review
documents. A dashboard of gray placeholders is a truthful dashboard; a dashboard
of plausible zeros is not.

## 14.3 Prohibited dashboard content

Simulated throughput, fake latency percentiles, invented confidence scores,
sample activity sparklines, comparisons to imaginary baselines, anomaly scores
with no detection logic, and any tile whose number cannot be traced to a query.
`docs/DECISIONS.md` ("No fabricated results") and `docs/THREAT_MODEL.md` D3 apply
directly: the dashboard is an observability surface, not a marketing surface.

## 14.4 Freshness

Every tile or panel shows an as-of timestamp from the query time, and the
dashboard distinguishes "no records" from "query failed" from "not authorized",
because those three states have completely different meanings for a researcher
interpreting a result.

---

# PART 15 — Conceptual data contracts for future UI integration

## 15.1 Status and caveats

- These are **conceptual read contracts** for a future projection layer. No API,
  no endpoint, no serializer, and no read-model module exists or is created by
  this phase. Nothing here is implemented.
- Field names follow the existing schema where a table exists, so that a future
  implementation is a projection rather than a redesign.
- Legends: **R** = required for the UI to render the record honestly;
  **O** = optional, rendered when present; **S** = sensitive, must never be
  rendered; **I** = internal-only, not part of any UI contract; **V** =
  user-visible.

## 15.2 Contracts

### User — `users` (IMPLEMENTED table)

| Field | | Notes |
|---|---|---|
| `id` | R, V | |
| `username` | R, V | |
| `created_at` | O, V | |
| `failed_login_attempts`, `locked_until` | O, V | own account only; supports the enumeration-reduction posture in the auth screen |
| `password_hash` | **S, I** | never rendered; `UserRepo.get_by_username()` / `get_by_id()` return it and are unsafe to expose (M-7, M-8) |
| `updated_at` | O, I | no current UI need |

### Session — `sessions` (IMPLEMENTED table)

| Field | | Notes |
|---|---|---|
| `expires_at` | R, V | for the session-expiry banner |
| `created_at` | O, V | |
| `revoked_at` | O, V | own sessions only |
| `user_id` | R, V | the viewer's own id |
| `token_hash` | **S, I** | never rendered |
| raw token | **S, I** | exists only in the login return value; never displayed, never sent to a browser-side store |

### Task — `tasks` (IMPLEMENTED table)

| Field | | Notes |
|---|---|---|
| `id`, `title`, `status` | R, V | `status` verbatim |
| `goal` | R, V | untrusted text (B1); render as data, truncate for display with an explicit marker |
| `created_at`, `updated_at` | R, V | |
| `user_id` | R, I | server-derived; never a client-supplied filter |

### Plan — `plans` (SCHEMA ONLY)

`id` R,V · `task_id` R,V · `validated` R,V (verbatim; no enum) · `created_at`,
`updated_at` O,V · `plan_json` O,V (untrusted, structured, read-only). No
revision field exists (C-05).

### PlanStep — `plan_steps` (SCHEMA ONLY)

`id` R,V · `plan_id` R,V · `position` R,V (verbatim; no uniqueness or range) ·
`action` R,V (untrusted) · `tool_name` O,V (verbatim, nullable) · `status` R,V
(verbatim) · `input_json` O,V (untrusted, redacted, size-capped) ·
`created_at` / `updated_at` O,V. No column links a step to the execution that
consumed it (C-07).

### Tool — NOT IMPLEMENTED (no table)

Planned from `SYSTEM_SPECIFICATION.md` §5: `id`, `name`, `description`,
`input_schema`, `policy`, `enabled`. Visibility per Part 12.2. Implementation
detail and environment values are **I**.

### ToolPermission — NOT IMPLEMENTED (no table)

Planned: `id`, `user_id`, `tool_id`, `granted_by`, timestamps, `scope`. The UI
needs exactly one derived value per (caller, tool): **granted: yes/no**. Absence
is denial. Grant management is a core-only, audited operation (Part 12.3).

### Execution — `executions` (SCHEMA ONLY)

`id` R,V · `task_id` R,V · `attempt` R,V (verbatim) · `status` R,V (verbatim) ·
`started_at`, `finished_at` O,V (duration derived only when both parse) ·
`error` O,V (untrusted, truncated) · `result_json` O, **tier-2 by default** (may
contain sensitive content; hidden by default).

### Artifact — `artifacts` (SCHEMA ONLY)

`id` R,V · `execution_id` R,V · `name` R,V · `kind` O,V · `size_bytes` O,V
(verbatim; may be negative) · `checksum` O,V (displayed, never presented as
verified) · `created_at` R,V · `relative_path` O,V **only after core
validation**; until then labeled unvalidated · `content` O, tier-2/tier-3 by
default, opt-in, size-capped, never rendered as markup.

### VerificationEvent — `verifications` (SCHEMA ONLY)

`id` R,V · `execution_id` R,V · `verifier` R,V (identity must always be visible
next to the outcome; B6) · `result` R,V (verbatim, unknown-value rule §4.5) ·
`created_at` R,V · `detail_json` O, **tier-2**, allowlist-gated. No start-time
column exists, so no "verification running" state is derivable (Part 8.2).

### Failure — `failures` (SCHEMA ONLY)

`id` R,V · `execution_id` R,V · `category` R,V (verbatim; no vocabulary defined)
· `created_at` R,V · `diagnosis` O,V (untrusted) · `detail_json` O, tier-2.

### RecoveryAttempt — `recovery_attempts` (SCHEMA ONLY)

`id` R,V · `execution_id` R,V · `attempt_no` R,V (verbatim) · `outcome` R,V
(verbatim; default `'pending'`) · `created_at` R,V · `diagnosis` O,V ·
`new_plan_json` O, tier-2, labeled as a recovered plan (C-05).

### ProvenanceEvent — `provenance_events` (PARTIALLY IMPLEMENTED)

`id` R,V · `event_type` R,V · `actor` R,V (verbatim; `'auth'` is the only value
ever written, and it is not in the documented role vocabulary — C-06) ·
`created_at` R,V · `task_id` O,V (nullable; `NULL` after task deletion) ·
`execution_id` O,V (nullable) · `detail_json` O, **tier-2, currently withheld
by default** pending D-08.

### BenchmarkRun — `evaluation_runs` (SCHEMA ONLY)

`id` R,V · `run_name` R,V (unique) · `status` R,V (verbatim) · `created_at`,
`started_at`, `finished_at` O,V · `config_json` O,V (reproducibility anchor;
serialized **with** the run by design) · `results_json` O,V (tier-1 once real;
never editable). **No owner column exists** — the record is global. Ownership
must be decided before a multi-account UI exposes it (D-09).

### Experiment — no entity exists

Not in the schema, not in `SYSTEM_SPECIFICATION.md` §5, and no code. The
`experiments/` directory is a documentation placeholder only. The workspace must
not present an "Experiment" record type; it must present evaluation runs and, if
needed later, a directory of result files whose provenance is a documented
decision (D-11).

### Metric — no entity exists

`SYSTEM_SPECIFICATION.md` §7 requires "pre-registered metric names and
definitions per run", and §5 defines `metrics_json` only inside the *planned*
`BenchmarkTask`. There is no metric table, no metric registry, and no
pre-registration mechanism. A UI may display a metric **only** as a named value
carried inside a stored run, with its definition shown, and must never define,
compute, or normalize a metric itself — that is the evaluation harness's job and
it does not exist.

## 15.3 Contract rules

1. **Projection, not exposure.** A future read-model layer should emit only
   fields marked R/O/V, applying the Part 9.2 tiering at the boundary, so that a
   UI bug cannot widen exposure. Proposed module name: `atlas/readmodel`
   (proposed only; not created by this phase).
2. **Verbatim enums.** Status and result fields pass through unchanged. The
   projection layer must not normalize, uppercase, translate, or default them.
3. **One vocabulary.** Both surfaces consume these same projections; neither
   defines a parallel shape.
4. **No contract implies existence.** A listed contract is a requirement on a
   future phase, not a description of a current capability.

---

# PART 16 — UI / core separation

## 16.1 The UI must never be authoritative for

| Concern | Owning core component | Phase | Current state |
|---|---|---|---|
| Authentication | `atlas/auth` | 07 | IMPLEMENTED |
| Authorization (resource/action permission) | `security/` | 08 | NOT IMPLEMENTED |
| Tool permission | `tools/` + `security/` | 09 | NOT IMPLEMENTED |
| Sandbox policy | `sandbox/` | 10 | NOT IMPLEMENTED |
| Filesystem access | `sandbox/` + path validation | 10 | NOT IMPLEMENTED (unrestricted `database_path`; unvalidated `relative_path`) |
| Network access | `sandbox/` + tool policy | 09/10 | NOT IMPLEMENTED |
| Verification verdict | `verifier/` | 13 | NOT IMPLEMENTED |
| Provenance integrity | `provenance/` + storage policy | 14 | append-only policy only; no integrity chain |
| Experiment validity | `evaluation/` | 21+ | NOT IMPLEMENTED |
| Final-result invariant ("no result without a recorded PASS") | orchestrator | 12 | NOT IMPLEMENTED (`docs/THREAT_MODEL.md` B5) |
| Resource-limit enforcement | owning runtime call sites | 09–16 | CONFIGURED, NOT ENFORCED |

## 16.2 The UI may

- request actions (submit a form, ask the core to do something);
- display state returned by the core;
- filter and sort data **it is already authorized to see**;
- visualize data;
- collect user input and validate it for usability (clearly labeled as a
  convenience, never as enforcement);
- navigate, zoom, filter, and change presentation.

## 16.3 The UI must never

- compute a permission, a verdict, a status transition, a bound, or a severity;
- cache an authorization or verification decision as if it were durable;
- retry, resume, cancel, or re-order a lifecycle operation;
- present a control whose effect it cannot state in terms of a core operation;
- be required for any control to exist. If a capability can only be performed
  through the UI, it is a capability the core does not have.

## 16.4 Enforcement consequence

Because the UI is not a boundary, the same action attempted by hand against the
database must be equally rejected. That property is testable only at the core,
and it is why `docs/STORAGE_REVIEW.md` §12 and `docs/AUTHENTICATION_REVIEW.md`
§11 list core-side prerequisites as blocking for any UI exposure. The UI phase
cannot substitute for them. Conversely, the UI must not ship in a way that
*assumes* those prerequisites are met: any destination whose data cannot yet be
authorized or redacted must be visibly unavailable rather than partially
shipped.

---

# PART 17 — Performance

Target: the documented host — 10c/12t i5-1335U, 15.7 GB RAM, ~197 GB free disk,
CPU-only local model — running the app, a local model, and the UI together
(`docs/DECISIONS.md`: laptop-safe execution).

## 17.1 Scale expectations

Datasets are small by design (`docs/TECHNOLOGY_STACK.md`: in-memory graphs only,
dataset sizes are small by design). The realistic stress cases are therefore
**long task histories and long event streams**, not huge single graphs:
thousands of provenance events, tens of executions per task, and a benchmark run
with many recorded results.

## 17.2 Budgets (requirements, not measurements)

| Concern | Requirement |
|---|---|
| Node count | Cap the default rendered graph at a few hundred nodes with an explicit "N of M shown" indicator; never truncate silently |
| Edge count | Cap similarly, prioritizing edges on the selected chain |
| Layout | Must be bounded-time; an unbounded force simulation is unacceptable. Prefer a deterministic layered layout for lifecycle graphs |
| Long-running tasks | Never poll in a tight loop; bounded interval with jitter, and a visible last-update time |
| Frequent updates | Incremental, not full re-render (§17.3) |
| Memory | Do not retain full artifact contents or large `detail_json` payloads in client state; fetch on demand and cap |
| Animation | Must not block input; heavy graphs degrade to instant state changes |

These are budgets for a future implementation to measure against. No measurement
exists yet and none is claimed.

## 17.3 Incremental updates and graceful degradation

- Load a **summary** first (counts, statuses, ids), then detail on demand.
- Apply incremental updates: new records patch the existing view; a changed
  status updates in place; nothing is rebuilt from scratch on each poll.
- Degradation ladder when the graph is too large or the host is busy:
  1. full interactive graph;
  2. filtered graph (selected task or selected chain only);
  3. chain view (the Part 9 trace as a linear, ordered list);
  4. table view (every record, every field, sortable);
  5. explicit "graph unavailable at this size", with the table view offered.
- Every rung carries the same information. Degradation reduces **rendering**
  complexity, never **truth**.
- The table view is the accessibility guarantee (Part 18), which is why it cannot
  be a degraded afterthought.

## 17.4 Streaming is not assumed

`docs/TECHNOLOGY_STACK.md` selects no broker, websocket, or streaming component,
and `docs/DECISIONS.md` explicitly avoids Kafka for exactly this reason. The UI
is therefore specified against **refresh and bounded polling** of stored state. A
future streaming path is permitted only if it streams records the core has already
persisted, and the Map must remain correct when the stream is absent.

## 17.5 What must never be done for performance

Dropping records silently; sampling without labeling; rendering stale data as
current; skipping the "as of" timestamp; truncating a status list without saying
so; or moving enforcement work into the client to save a round trip. The cheapest
correct answer is a smaller, honest view.

---

# PART 18 — Accessibility

The Map is a rich visualization; it must never be the only way to understand
anything important.

## 18.1 Requirements

| Area | Requirement |
|---|---|
| Keyboard navigation | All destinations, tabs, table rows, graph nodes, and controls reachable and operable by keyboard, in logical DOM order. No keyboard trap. |
| Visible focus | A clearly visible focus indicator on every interactive element, including SVG/canvas nodes, meeting the contrast requirement below. Never removed without a replacement. |
| Semantic labels | Every control and node has a programmatic name. Graph nodes are exposed as a labeled list or tree, e.g. "Artifact, id 41, execution 12, file, 2.1 KB". Status is conveyed as text, not color alone. |
| Contrast | Text and meaningful graphics meet WCAG AA (4.5:1 text, 3:1 large text and essential graphics). Status colors remain distinguishable under common color-vision deficiencies and are paired with a text label or shape. |
| Reduced motion | `prefers-reduced-motion: reduce` disables all non-essential animation; transitions become instant state changes plus a brief static highlight (Part 8.5). No information is motion-only. |
| Alternative representation | Every graph view has a complete non-graph equivalent: an ordered table of nodes (type, id, status, timestamps) and an ordered list of edges (source, destination, meaning). This is the primary fallback, not an extra. |
| Accessible status indicators | Status always available as text. A color, glow, or icon is redundant encoding, never the sole carrier. |
| Zoom and scaling | Usable at 200% zoom / enlarged text without loss of content or function. |
| Screen-reader behavior | Dynamic updates announced politely and user-triggerable rather than auto-playing; a rapidly updating graph must not flood assistive technology. |
| Language and units | Timestamps shown with explicit timezone; byte sizes and durations in unambiguous units; the raw stored value available for verification purposes. |
| Forms | Labels associated with inputs; errors associated with fields; never placeholder-as-label. |

## 18.2 The non-negotiable accessibility principle

> If a research question can only be answered by looking at the graph, the
> research question is not answerable. Every fact the Map conveys must be
> obtainable in the workspace as text.

This is what makes principle 11 testable: with the Map entirely absent, Surface A
must still answer every question the Map can answer — which is why the workspace's
Task Detail tabs (§3.3) carry the same records, and why provenance is a
first-class tab rather than a Map feature.

---

# PART 19 — Visual design direction

## 19.1 What the visual identity must communicate

**Observability · Control · Verification · Provenance · Reliability.** Every
visual decision should be defensible against one of those five words. If a design
element communicates none of them, it is removed.

The project is a serious AI-systems research instrument. It should look like an
instrument: legible, calm, precise, and dense with real information. "Cinematic"
is permitted only where it aids comprehension of a real transition (Part 8) and
never as decoration.

## 19.2 Characteristics

| Characteristic | Requirement |
|---|---|
| Modern | contemporary type and layout conventions; no skeuomorphism, no dated widgets |
| Precise | aligned grids, consistent spacing scale, unambiguous units, monospace for identifiers and machine output |
| Minimal | every element earns its place; no ornament |
| Technical | real terminology from the domain (attempt, verifier, artifact, provenance) rather than invented language |
| Research-oriented | dense, tabular, exportable, citation- and figure-friendly; the interface should look like something whose screenshots belong in a paper appendix |
| Information-dense but readable | high information density with strict typographic hierarchy, whitespace discipline, and contrast |
| Sophisticated | restraint; confidence from precision rather than effect |
| Cinematic where appropriate | reserved for genuine state transitions in the Map, disabled under reduced motion |

## 19.3 Explicitly rejected visual language

Neon cyberpunk; glowing AI-brain graphics; random particles; meaningless 3D; fake
terminal output; decorative telemetry; excessive gradients; visual noise;
glassmorphism for its own sake; animated backgrounds; "AI magic" sparkles;
skeleton loaders that imply work is happening when nothing is running.

Two specific traps for this project:

1. **Glow as certainty.** A glowing node implies something is active, alive, or
   trusted. Reserve glow exclusively for a recorded active state, and never for a
   verification pass — a PASS is a predicate result, not an aura.
2. **Motion as intelligence.** Ambient or looping motion implies ongoing
   cognition. There is no such state to depict (Part 8.3).

## 19.4 Status visual language

Status is always a **triple**: a text label, a shape/pattern, and a color. Color
alone is never sufficient (Part 18). Because the UI renders stored values
verbatim (§4.5), the visual vocabulary must be extensible: an unrecognized status
gets a neutral "unrecognized" treatment, never a guessed one.

Proposed neutral, restrained palette direction: a single low-chroma accent for
interactive affordances; a small, fixed set of semantic status colors (pass, fail,
other/unrecognized, pending, denied) that all pass AA contrast; and
monochrome-plus-accent for everything structural. Exact values, and their
contrast verification, are a future implementation task — no palette is claimed
here.

---

# PART 20 — Responsive behavior

Target form factors: desktop (primary), laptop (the documented host), and a
smaller viewport (a phone or a narrow window). The research instrument is
desktop-first because that is how research is done here, but nothing critical may
become unreachable on a small screen.

| Form factor | Behavior |
|---|---|
| **Desktop (≥1280px)** | Full layout: persistent navigation, multi-column task detail, full Map with side-by-side detail panel. |
| **Laptop (1024–1279px)** | Same structure with tighter spacing; the Map detail panel becomes an overlay rather than a side column. |
| **Smaller viewport (<1024px)** | Navigation collapses to a single top-level selector; task-detail tabs become a scrollable tab strip; the Map switches to the chain/table views by default. |
| **Narrow (<768px)** | The graph is **not** rendered as a squeezed canvas. Default to the ordered chain list and the full table. The graph remains reachable only via an explicit "open graph" action, with a notice that it is not optimized for this width. |

The rule for smaller screens is **simplify, do not shrink**. Shrinking a
force-directed graph to phone width produces an unreadable hairball; the correct
degradation is a linear, ordered, complete representation.

The core research information must remain accessible at every size: task list,
task record, plan, steps, executions, verifications, failures, recoveries,
artifacts, provenance, and configuration must all be reachable and readable
without the graph at any viewport.

---

# PART 21 — Security and privacy

## 21.1 Threat surface specific to the UI

| # | Threat | Required UI-side control | Governing core control |
|---|---|---|---|
| U1 | **Frontend authorization bypass** — hiding or enabling a control to gain access | none in the UI can prevent this; the core must deny. The UI must therefore never be *evidence* of a permission. It may reduce accidents, never attacks | Phase 08 deny-by-default authorization (A4, residual Hi until then) |
| U2 | **Information leakage through over-broad reads** | render only R/O/V fields from §15; apply Part 9.2 tiering; never use `SELECT *` rows as view models | M-7/M-8 data-minimization findings |
| U3 | **User enumeration** | do not add enumeration aids: no username suggestions, no distinct styling for "locked" beyond the core's own error, no client-side timing theater | generic `AuthenticationFailed` (A6); M-01 residual |
| U4 | **Cross-user task visibility** | scope every query to the viewer's own id; never accept a user id from the client; never render a foreign record "as empty" if a denial is available | `WHERE user_id = ?` (implemented for `TaskRepo` only); A3/D1 |
| U5 | **Sensitive artifact exposure** | artifacts default to metadata; `content` is opt-in, capped, redacted, and never rendered as markup | D2 (content stored, not echoed) |
| U6 | **Secret exposure** | never render `password_hash`, raw session token, `token_hash`, or `application_secret_key`; use `Settings.safe_dump()`; never echo a submitted password into the DOM | Argon2id + redaction filter (A5, D3) |
| U7 | **Provenance leakage** | tier-2 default withholding; per-event ownership scoping once it exists; no bulk export of other users' events | M-4 (no owner column), D1 |
| U8 | **Debug information exposure** | no tracebacks, SQL text, file paths, or environment dumps in the default view; diagnostics behind an explicit control and redacted | D3; redaction filter not yet wired (HIGH-1) |
| U9 | **Unsafe rendering (XSS)** | render all stored text as text, never as HTML. This applies to **every** stored string: goals, plan text, step actions, tool names, artifact names, artifact content, failure categories, diagnoses, provenance detail | B1 (model output is untrusted data) |
| U10 | **Malicious artifact content** | artifact content is untrusted by definition (it may be model-generated code or attacker-influenced). Never executed, never rendered as markup, always labeled with its origin | B3, C3, C4 |
| U11 | **Model-generated content rendered as trusted HTML/JS** | strictly prohibited. No `unsafe_html`, no `dangerouslySetInnerHTML` equivalent, no script evaluation, no markdown-to-HTML without sanitization. If rich text is ever rendered, it must be sanitized by a reviewed, local library | B1 |
| U12 | **CSRF** | undecided (D-04). Until decided, no state-changing control may rely on ambient credentials alone, and the cookie posture must be explicit | A2; `SECURITY.md` lists CSRF as a must-address item at the UI phase |
| U13 | **Transport exposure** | localhost plaintext is the documented posture; the UI must not encourage binding to a LAN interface, and must not display a token over an insecure channel | THREAT_MODEL non-guarantee 2 |
| U14 | **Path disclosure** | never display absolute host paths; note the reconnaissance finding that the project sits on a Desktop containing personal documents, and that the project must never walk outside its root | `docs/environment-reconnaissance.md` security concern |

## 21.2 Rendering rules (normative)

1. **All stored text is text.** Escaped, never interpreted. No exceptions for
   "trusted" columns — provenance and artifact content are the *least* trusted.
2. **No client-side secret storage.** No `localStorage`, `sessionStorage`, cookies
   readable by script, or URL parameters for tokens. Streamlit session state is
   server-side; the React surface must not persist credentials in browser storage.
3. **Bounded rendering.** Every text field has a display cap with an explicit
   "truncated, full length N" marker, and a cap on total rendered payload per view.
4. **No silent omission.** If something is withheld, the UI says it is withheld
   and why (policy), so a researcher is never misled into thinking data is absent
   rather than hidden.
5. **No ambient authority.** The presence of a control never implies the backend
   permits the action; a successful action is confirmed only by a real response.
6. **Redaction is a boundary concern, not a UI convenience.** The UI applies
   presentation-tier filtering for correctness and data minimization; it does not
   claim to be the security control, and `SecretsRedactionFilter` must be wired at
   the core before any secret-bearing logging exists (HIGH-1).

## 21.3 Privacy posture

Task goals, artifact content, verification details, and provenance details are
plaintext in SQLite, with the OS account as the only at-rest boundary
(`docs/STORAGE_REVIEW.md` M-5, M-6; THREAT_MODEL non-guarantee 6). The UI must not
imply encryption, retention, or secure deletion that does not exist, and must
warn before destructive actions (task deletion cascades and nulls provenance).

---

# PART 22 — Error states

## 22.1 Principles

Every error must have: (a) a safe user-facing explanation, (b) an appropriate
recovery action, (c) no secret leakage. Additionally: (d) errors are states to
render, not animations to perform; (e) an error never fabricates state; and (f) an
error in a read must not clear or reset correct data already on screen.

## 22.2 Error catalogue

| Condition | User-facing explanation | Recovery action | Must not do | Secret-leakage rule |
|---|---|---|---|---|
| **Authentication failure** | the core's generic invalid-credentials message | retry; do not pre-fill the username | do not distinguish "no such user" from "wrong password" in new UI text; do not add a client-side delay pretending to be the core's | never echo the submitted password |
| **Account locked** | the core's locked message, with the fact that it is temporary | wait, or change nothing and retry later; no unlock control | do not offer "unlock", which does not exist; do not show another user's lock state | n/a |
| **Session expired** | the session is no longer valid | re-authenticate; unsaved input is discarded with a warning | do not silently refresh; do not keep displaying protected data after expiry | do not display the expired token |
| **Authorization denial** | the action is not permitted for this account | return to an allowed view; request access through the core's process, if one exists | do not reveal whether the resource exists; do not offer a UI workaround | do not reveal policy internals |
| **Task failure** | the task's recorded failure category and diagnosis, verbatim | open the failure tab; navigate to recovery history if a record exists | do not auto-retry; do not relabel the failure | diagnosis may be untrusted text |
| **Tool failure** | the recorded tool/execution error, truncated | open the execution timeline | do not imply the tool registry is at fault; do not offer "run again" | do not dump raw stdout/stderr by default |
| **Sandbox failure** | the recorded sandbox/constraint violation, plus the standing residual-risk note | open the sandbox tab; report the violation for the security-testing phase | never describe the boundary as container isolation; never suggest weakening limits from the UI | do not show absolute host paths |
| **Verification failure** | the recorded verification identity, result, and allowed evidence | open the verification evidence panel; follow the recorded recovery | no re-verify control; no client-side re-judgment | do not expose verifier source or policy internals |
| **Recovery exhausted** | the recorded bound, attempts used, and termination reason | review the failure and the provenance chain; record the outcome in a report | do not offer a further attempt from the UI; do not imply the system will keep trying | n/a |
| **Backend unavailable** (database missing, locked, unwritable) | the core could not be reached or read; state which operation failed | retry; verify the configured database path is accessible; consult the CLI health check (`atlas-x`) | do not display connection strings, SQL, or tracebacks; do not offer to create or relocate a database from the UI | never display the database path outside the project, or file contents |
| **Invalid task input** | which bound or rule was violated, and that the bound is *configured* vs *enforced* | correct the input | do not claim the core rejected it if the UI rejected it client-side | n/a |
| **Invalid plan** | the plan failed validation, once a validator exists | return to the plan tab read-only | no UI plan editing; never render an unvalidated plan as executable | plan text is untrusted |
| **Missing artifact** | the referenced artifact record is absent or was deleted with its execution | show the deletion chain; note that cascades are not reversible | do not offer "restore"; there is no soft delete or secure erasure (M-6) | do not show stale cached content as if it were recovered |
| **Corrupted provenance** | the audit chain is incomplete or internally inconsistent, and that integrity is append-only-by-policy only | escalate to the operator; treat conclusions drawn from it as unverified | never repair, reorder, or drop events to make the chain look clean; never claim tamper-evidence | do not dump `detail_json` in an error path |
| **Unsupported visualization data** | the graph cannot represent this data shape or size | fall back automatically to the chain or table view; state why | never drop records silently; never substitute invented structure | n/a |
| **Schema/version mismatch** | the database `schema_migrations` version does not match what the code expects | stop; do not initialize or upgrade from the UI | never auto-migrate. Version validation is not implemented (H-2), so this must fail loudly and refuse | do not display the file path or file contents |
| **Configuration invalid** | the specific `Settings` field and rule that failed validation, with the field name only | correct the environment variable and restart | never display `application_secret_key` or any secret field value; never offer an in-UI config editor | `safe_dump()` only; never `secret_values()` |

## 22.3 Error-state prohibitions

No error may suggest an action the core cannot perform; no error may be
"resolved" by a client-side retry of a non-idempotent operation (the threat model
lists replay of privileged operations as A7, residual Med, with replay guards
still planned for Phase 12); no error may be silently swallowed; and no error may
leave the UI in a state that looks like success.

---

# PART 23 — Research mode vs demo mode

## 23.1 Evaluation

The question is whether ATLAS-X should have two modes.

**Decision: no mode switch. One mode — real research — plus an explicitly
labeled fixture data source.**

Reasons:

1. A mode flag that changes what the system displays is a
   fixture/production switch, and `docs/CONFIGURATION_REVIEW.md` §4 and its
   required change 5 establish a standing rule that **no configuration flag may
   disable auth, authorization, verification targets, or logging redaction**. A
   "demo mode" is exactly the shape of knob that rule exists to prevent: it is
   almost impossible to add one later without it becoming a security off-switch.
2. A mode flag is a fabrication risk. `docs/DECISIONS.md` requires that all
   claims trace to real measured executions. A screen whose data source can be
   swapped invites a screenshot of synthetic data entering a report.
3. There is no present need. Nothing in the current system is demo-worthy,
   because nothing executes yet.

## 23.2 What replaces it

- **RESEARCH MODE is the only mode** and is not a toggle. It is the default and
  the only state.
- **Fixture data is a separate, explicitly labeled data source**, permitted only
  for UI development before real records exist, and subject to all of:
  - a **persistent, non-dismissible banner** on every screen showing fixture data,
    naming it as fixture and stating that it is not a real ATLAS-X run;
  - a **watermark in every export** produced while fixtures are active;
  - **no mixing**: fixture and real records are never displayed in the same list,
     the same graph, or the same aggregate;
  - **no fixture path to any claim**: a fixture-sourced number may never be
    copied into a report, a benchmark result, or an experiment record — enforced
    by the export watermark and, ultimately, by the fact that fixtures are never
    written to the database;
  - **fixtures are never persisted** into `tasks`, `executions`, `verifications`,
    or `provenance_events`. If a fixture must be shown, it is shown from a
    read-only in-memory source, so a fixture can never become provenance.
- **What fixtures may depict:** node/edge layout, empty states, error states,
  typography, and layout. They may also depict a synthetic lifecycle **only** with
  the banner and watermark rules above and only while the corresponding core
  phases are unimplemented.

## 23.3 The hard boundary

> A demo may show the *shape* of ATLAS-X. It may never show *results* that did
> not come from a real recorded execution, and it may never write anything that
> could later be mistaken for a real run.

---

# PART 24 — Future frontend implementation plan

Order of work, dependencies first. **None of this is implemented or started.**
Each item is gated on the core phase named beside it.

| # | Step | Depends on | Notes |
|---|---|---|---|
| 1 | Shared data contracts (read-model projections, tiering, verbatim enums) | Part 15 + core entities | the contract layer must exist before any screen; it is where Part 9.2 tiering is enforced |
| 2 | Basic research workspace shell (navigation, session handling, re-validation per §2.2.2) | 08 for any protected data | session handling depends on M-04 being resolved |
| 3 | Authentication screens | auth (done) + D-04 cookie/CSRF decision | must not be built before the session principal is defined |
| 4 | Task dashboard | repository coverage for the tiles actually shown | only real tiles; explicit "not implemented" elsewhere |
| 5 | Task list and task creation | task validation (Phase 11) for real bound enforcement | label client-side checks as convenience |
| 6 | Task detail with the record tabs | core entities per tab | tabs appear as their records become writable |
| 7 | Execution timeline | Phase 12 orchestrator | needs real `executions` rows |
| 8 | Verification UI | Phase 13 verifier | three-valued rendering per Part 10; never a client verdict |
| 9 | Provenance UI | Phase 14 + D-08 redaction/ownership decision | detail stays withheld until D-08 lands |
| 10 | Benchmark and experiment UI | Phase 21+ + D-09 ownership decision | cannot precede a real harness |
| 11 | Living System Map foundation (project scaffolding, build, deploy posture) | D-07 approval of an HTTP read surface | nothing before approval |
| 12 | Graph rendering (nodes and edges from records) | 11 + real records for the entities drawn | deterministic layered layout first |
| 13 | Real event integration (refresh/polling, incremental updates, as-of timestamps) | 12 + provenance producers | no streaming assumed |
| 14 | Cursor interactions (hover, focus, click, edge panels, expansion) | 12 | keyboard parity in the same step, not later |
| 15 | Provenance highlighting and chain trace | 9 + 12 | must show partial traces honestly (§7.4) |
| 16 | Animations | 13, and only for recorded events | reduced-motion support ships with this step |
| 17 | Accessibility pass (labels, contrast verification, table/chain equivalents) | 11–16 | the table view is a release blocker for the Map, not a follow-up |
| 18 | Performance optimization and graceful degradation | measured behavior on the real host | budgets from Part 17 verified by measurement |
| 19 | Final visual polish | 17, 18 | polish never changes semantics |

Ordering rationale: contracts before screens, core before display, real records
before visualization, accessibility and honesty before polish.

---

# PART 25 — Architectural decision log

## 25.1 Decisions made by this phase (documentation only, no code)

| ID | Decision | Rationale |
|---|---|---|
| DD-01 | Two surfaces: a Streamlit Research Workspace and an optional React Living System Map | the workspace serves research; the map serves observability. Principle 11 requires the workspace to stand alone |
| DD-02 | The Map is additive, optional, and never displaces Surface A | `docs/TECHNOLOGY_STACK.md` deliberately dropped React for the core (see C-01). Additivity is the only position that does not override a standing decision while still meeting this phase's mandate |
| DD-03 | The workspace is in-process (imports `atlas`) and needs no HTTP API for itself | it runs in the same interpreter; adding FastAPI for it would add attack surface with no benefit (`docs/TECHNOLOGY_STACK.md` rationale) |
| DD-04 | Eight top-level destinations; sixteen task-scoped candidates become tabs in Task Detail | avoids invented screens and multiplied cross-screen state (§3.1) |
| DD-05 | The visual lifecycle is a derived display convention, never an authoritative state machine | `SYSTEM_SPECIFICATION.md` §4 is authoritative; no status enum exists in code or schema |
| DD-06 | Unknown status and result values render verbatim and are labeled unrecognized, never coerced | status columns are unconstrained `TEXT`; coercing would fabricate meaning (§4.5) |
| DD-07 | Executions are siblings under a task, numbered by stored `attempt`; the retry loop crosses siblings | matches stage 14 and the `recovery_attempts.execution_id` foreign key (§4.3) |
| DD-08 | `CANCELLED` and `SECURITY_BLOCKED` are never rendered | no such record, status, or mechanism exists (C-04) |
| DD-09 | Nodes and edges exist only where both endpoint records exist; no inferred, confidence-weighted, or layout-derived edges | principle 8 and Part 6.3 |
| DD-10 | A partial provenance chain must visibly look partial | principle 10; pretending completeness is the failure mode this project exists to study |
| DD-11 | No client-side verdict, no re-verify control, no grant control | principles 3–5; Part 12.3 |
| DD-12 | Three information tiers for provenance and artifact detail, tier 1 by default | `detail_json` is unredacted and unbounded (`docs/STORAGE_REVIEW.md` M-5) |
| DD-13 | Animations only for recorded events; no ambient motion; visible as-of timestamps | Part 8 |
| DD-14 | No mode switch; fixtures are a labeled, non-persistent, non-mixable read-only source | Part 23; standing "no security off-switch" rule |
| DD-15 | Graph is never the only representation; a complete table/chain equivalent ships with the Map | Part 18; principle 11 |
| DD-16 | Refresh/bounded polling is the baseline; streaming is not assumed | no streaming component is selected anywhere in the stack |
| DD-17 | Sandbox panel must state "not container isolation" and label every limit enforced vs declared | THREAT_MODEL non-guarantee 1; residual Hi for B3/C4/C5 |
| DD-18 | Single read-model projection layer feeds both surfaces; proposed name `atlas/readmodel` | prevents contract drift and duplicate logic; name is proposed, not created |

## 25.2 Decisions deferred

| ID | Deferred decision | Why deferred |
|---|---|---|
| DD-19 | Exact Streamlit layout, component library, and theming | the workspace does not exist; premature detail |
| DD-20 | SVG vs Canvas, and any graph/animation library selection | selection must be justified by measurement (Part 17), and no measurement exists |
| DD-21 | Whether the Map is a separate process, a separate origin, or a served static bundle | follows from D-07 and the deployment posture |
| DD-22 | Benchmark and experiment screen detail | no harness, no ownership decision (D-09 below) |
| DD-23 | Search implementation (SQLite FTS vs in-memory filter) for the provenance explorer | no FTS table exists; needs a volume estimate |
| DD-24 | Retention, export formats, and report layout for `reports/` | `docs/CONTRIBUTING.md` requires results committed with their configs; format decision is a later phase |
| DD-25 | Whether a role/permission concept is ever surfaced in the UI | roles are Phase 08 and residual risk is Hi; the UI must not invent a role display |

## 25.3 Decisions requiring human approval (blocking)

| ID | Decision needed | Blocks | Why it cannot be decided here |
|---|---|---|---|
| D-01 | Approve Surface A (Streamlit) as the first UI to build, and confirm Surface A is the primary research surface | step 2 of Part 24 | this phase may specify but not commit scope |
| D-02 | Approve the `atlas/readmodel` projection layer as a new core component (name, location, ownership) | step 1 of Part 24 | adds a component to the core; core scope belongs to the owning phases |
| D-03 | Approve a read-only HTTP projection API (and therefore the FastAPI deferral being lifted) | Surface B entirely | `docs/TECHNOLOGY_STACK.md` defers FastAPI pending a real API need; a browser app in another origin is a real need, but the decision is a stack-level change |
| D-04 | Choose the session/cookie/CSRF/transport posture for a browser surface (Streamlit's own model vs explicit cookies via `atlas/auth/sessions.py`; CSRF posture; localhost-only binding) | any protected screen | `SECURITY.md` explicitly defers CSRF to the UI phase; A2 residual is Med; `application_secret_key` is currently unused (MEDIUM-3) and cannot be assumed to sign anything |
| D-05 | Define the core status vocabularies, including whether `INCONCLUSIVE` is a verification outcome, and whether `CANCELLED` / `SECURITY_BLOCKED` terminal states exist | Parts 4, 10, 11 | these are core semantics owned by Phases 08/12/15/16; the UI follows them (§4.5, C-03, C-04) |
| D-06 | Decide the plan-revision model (revisions table, immutable recovery chain as authority, or documented overwrite) | the REPLAN → PLAN edge and any replan visualization | `plans.task_id` is UNIQUE, so a second plan row is impossible today (C-05) |
| D-07 | Approve or reject the React/TypeScript/Vite surface given C-01, and where it lives | Surface B | conflicts with a standing stack decision; requires the human gatekeeper |
| D-08 | Approve a provenance/artifact detail redaction policy with an allowlist, size caps, and tier definitions | provenance and artifact detail rendering (step 9) | a data-classification decision affecting stored research data |
| D-09 | Decide whether `evaluation_runs` are global research data or user-owned | Destination 8 | `docs/STORAGE_REVIEW.md` §12 requires this decision before multi-user exposure |
| D-10 | Decide whether to add explicit `plan_steps → executions` and `artifacts → verifications` linkages | edges E4 and E6 | schema change belongs to the owning core phases (C-07) |
| D-11 | Decide what an "Experiment" is, or confirm that evaluation runs are the only experiment-level entity | Destination 8 | no entity exists anywhere; inventing one here would be fabrication |
| D-12 | Approve whether the `SECURITY.md` lockout-persistence wording is corrected (already recorded as a discrepancy by `docs/AUTHENTICATION_REVIEW.md` M-03) | accuracy of the security panel on Destination 7 | documentation change outside this phase's scope |

## 25.4 Assumptions

1. The core remains the owner of every decision listed in Part 16.1; a later phase
   that contradicts one of them invalidates this document rather than the reverse.
2. Single-host, local, single-user research use continues to be the deployment
   posture. A multi-tenant or network-exposed deployment would invalidate
   substantial parts of Parts 2, 12, 13, and 21.
3. Status vocabularies will be added by the core with tests, and until then the
   verbatim/unknown-value rule is the correct renderer behavior.
4. `plans`, `executions`, `artifacts`, `verifications`, `failures`, and
   `recovery_attempts` will be written by their owning phases with the columns
   already in schema; a schema change to any of them requires revisiting Parts 4–6
   and 15.
5. Node and npm availability (verified read-only in this phase: Node v20.11.1,
   npm 10.2.4) makes a future frontend build technically possible offline for
   already-cached packages, but no package availability is assumed and no
   install is authorized by this phase.
6. The researcher's data volume stays small, so a bounded graph and a complete
   table view are sufficient; a very large deployment would require pagination
   and server-side filtering decisions that are out of scope here.

## 25.5 Unresolved contradictions (recorded, not silently resolved)

| ID | Contradiction | Authoritative source | Status |
|---|---|---|---|
| C-01 | This phase is instructed to specify a React/TypeScript/Vite surface; `docs/TECHNOLOGY_STACK.md` lists "React/Next.js frontend" under **Dependencies We Explicitly Avoid** and states React "was deliberately dropped for the core (the folder shape no longer includes an `apps/web` frontend)"; `docs/ARCHITECTURE_RECONCILIATION.md` §5.2 records that `apps/web` was retired; `docs/DECISIONS.md` records "Streamlit-first UI" | `docs/TECHNOLOGY_STACK.md` + `docs/DECISIONS.md` for the core | **Unresolved — human gate (D-07).** Mitigated, not resolved, by DD-02: the Map is additive, optional, and carries no security or business logic. Neither document has been edited by this phase |
| C-02 | The briefed lifecycle has ~13 visual stages; `docs/SYSTEM_SPECIFICATION.md` §4 defines 18, and the brief's `READY` and `SECURITY_BLOCKED` have no authoritative counterpart | `SYSTEM_SPECIFICATION.md` §4 | Resolved for display purposes by DD-05/DD-08; the underlying core model still needs D-05 |
| C-03 | The brief requires PASS/FAIL/INCONCLUSIVE; `SYSTEM_SPECIFICATION.md` §5 defines PASS/FAIL, and `verifications.result` is unconstrained `TEXT` with no `CHECK` | `SYSTEM_SPECIFICATION.md` §5 + `atlas/storage/migrations.py` | **Unresolved — human gate (D-05).** The UI supports a distinct third treatment without asserting the value's meaning (Part 10.1) |
| C-04 | The brief lists `CANCELLED` and `SECURITY_BLOCKED` as terminal states; no cancellation mechanism, status value, or record type exists | `atlas/storage/migrations.py`, `atlas/**`, `SYSTEM_SPECIFICATION.md` | **Unresolved — human gate (D-05).** Never rendered (DD-08) |
| C-05 | The briefed edge `REPLAN → PLAN` implies multiple plans per task, but `plans.task_id` is `UNIQUE` (`atlas/storage/migrations.py:72`); a renewed plan can only live in `recovery_attempts.new_plan_json` | `atlas/storage/migrations.py` | **Unresolved — human gate (D-06).** A replan is rendered as a labeled recovered-plan node from `recovery_attempts`, never as an ordinary second PLAN |
| C-06 | `SYSTEM_SPECIFICATION.md` §5 states provenance actors are the fixed roles user/planner/executor/verifier/recovery; the only producer writes `actor='auth'` (`atlas/auth/service.py:140`) | code for behavior, spec for intent | Recorded. The UI renders `actor` verbatim and labels unknown actors unclassified (Part 5.2 Provenance) |
| C-07 | Edges E4 (tool→execution) and E6 (artifact→verification) are required by the brief, but no column links `plan_steps` to the execution that consumed it, and no column links an `artifacts` row to a specific `verifications` row | `atlas/storage/migrations.py` | **Unresolved — human gate (D-10).** Those edges are not drawn until the linkage exists (§6.3.1) |
| C-08 | This phase is numbered 07.5, while `SYSTEM_SPECIFICATION.md` §9, `THREAT_MODEL.md` (D2 → "20 UI", A2 → "UI cookies"), and `ARCHITECTURE_RECONCILIATION.md` §7 all place UI at Phase 20 | those documents | Recorded, not renumbered. This document is a **specification precursor** to Phase 20 and does not claim to be Phase 20. No phase numbering was changed |
| C-09 | `docs/DECISIONS.md` and `docs/TECHNOLOGY_STACK.md` mark Streamlit as the UI decision, but Streamlit is not a dependency in `pyproject.toml` and no UI entry point exists | already recorded in `docs/ARCHITECTURE_RECONCILIATION.md` §5.4 | Carried forward unchanged. No dependency was added by this phase |

## 25.6 Future implementation dependencies

- Core phases 08 (authorization), 09 (tools/permissions), 10 (sandbox — hard
  gate), 11 (planner), 12 (orchestrator, replay guards, verification invariant),
  13 (verifier), 14 (provenance producers and integrity), 15/16 (failure
  classification and bounded recovery), 19 (security testing), 21+ (evaluation).
- Resolution of the recorded authentication prerequisites that block any browser
  exposure: M-04 (single fail-closed session invariant), M-05 (bind password
  change to the session principal), M-06 (session rotation/transport), and H-02
  (wire `SecretsRedactionFilter` into runtime logging).
- Resolution of the storage prerequisites in `docs/STORAGE_REVIEW.md` §12:
  owner-scoped repository contracts for every entity, a real migration/validation
  protocol, database path confinement, and a provenance data-classification
  policy.
- Approvals D-01 through D-12, of which D-03 and D-07 gate the entire Living
  System Map.

---

# Verification performed by this phase

Documentation only. No application code, schema, configuration, dependency,
environment, or model/provider setting was created, installed, or modified.

1. **Existence.** `docs/UI_ARCHITECTURE.md` was created and re-read after writing.
2. **Grounding.** Every "currently implemented" claim in this document was checked
   against the source files read in this phase: `atlas/config/settings.py`,
   `atlas/storage/db.py`, `atlas/storage/migrations.py`,
   `atlas/storage/repositories.py`, `atlas/auth/password.py`,
   `atlas/auth/sessions.py`, `atlas/auth/service.py`,
   `atlas/security/logging.py`, `atlas/util.py`, `atlas/cli.py`, the eight
   placeholder package `__init__.py` files, `pyproject.toml`, `.env.example`, and
   the `benchmarks/`, `datasets/`, `docker/`, `experiments/`, `reports/`, and
   `scripts/` placeholder READMEs.
3. **Contradiction inspection.** Nine contradictions are recorded in §25.5 rather
   than resolved silently, and the authoritative source is named for each.
4. **No unimplemented functionality claimed.** The document labels every entity
   IMPLEMENTED, SCHEMA ONLY, PLANNED, or NOT IMPLEMENTED; states in §0.2 that no
   UI of any kind exists; marks every unavailable dashboard tile and screen panel
   as owned by a named future phase; and creates no frontend, no dependency, and
   no module (the `atlas/readmodel` name is explicitly marked as proposed and not
   created).
5. **Implemented vs planned separation.** §0.2 gives the inventory; §2 states that
   both surfaces are unimplemented; §4.1 shows which lifecycle stages exist;
   §5.3 tabulates each Map node against its record; §15 marks every field's
   contract status.
6. **Security responsibility assignment.** Part 16 assigns every sensitive
   decision to a named core component and phase; Part 12.3 forbids UI permission
   grants; Part 10.3 forbids client-side verdicts; §2.2.2 constrains session
    handling; standing prerequisites from the earlier reviews are carried forward
    in §25.6; and no document outside this one was edited.
7. **Map defined as visualization of real state.** Principle 12, Part 6.3
   (no inferred or synthetic edges), Part 8 (animation only for recorded events,
   with an explicit forbidden list), §7.4 (partial traces must look partial), and
   Part 23 (fixtures labeled, non-persistent, never mixed, never written to the
   database) together define the Map as an instrumentation layer over recorded
   state.
8. **Environment.** Read-only checks confirmed Node v20.11.1 and npm 10.2.4 and
   confirmed that `docs/UI_ARCHITECTURE.md` and `atlas/ui` did not previously
   exist. No package was installed; no network call was made.
9. **Test suite.** Not re-run. This phase changed no code, so the established
   results (pytest 36 passed, Ruff clean, mypy clean in 23 files) are carried
   forward unchanged from `docs/AUTHENTICATION_REVIEW.md` §12, as instructed.

Files created by this phase: `docs/UI_ARCHITECTURE.md` only.
Files modified by this phase: none.
Phase 08 is not started.


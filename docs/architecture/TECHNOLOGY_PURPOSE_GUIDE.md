# Technology Purpose Guide

This guide explains, in plain English, what each technology does in ATLAS-X and why
it is here. It is aimed at a developer new to the project.

## React

General purpose: a JavaScript library for building component-based user interfaces.
In ATLAS-X: the single-page app in `frontend/src` (pages, components, contexts,
hooks). Routes are defined in `frontend/src/App.tsx`. State and API calls live in
`frontend/src/contexts/AuthContext.tsx` and `frontend/src/services/api.ts`.
Trade-off: adds a frontend toolchain (Node, Vite) but gives a typed, component-based UI. The backend remains usable through its REST API and CLI if the frontend is unavailable.

## TypeScript

General purpose: statically typed superset of JavaScript.
In ATLAS-X: all `frontend/src` code is TypeScript; `tsc -b` runs before Vite
build (`frontend/package.json` scripts). Catches type errors at build time.
Trade-off: extra build step; benefit is safer refactoring.

## Vite

General purpose: fast dev server and bundler for modern frontend projects.
In ATLAS-X: `frontend/vite.config.ts` sets dev port 5173, proxies `/api` to
`http://127.0.0.1:8000`, and `npm run build` produces `frontend/dist`, which
FastAPI serves as static files (`api/__init__.py`). If unavailable, no frontend
build; backend still runs.

## Python

General purpose: general-purpose language with strong ecosystem for AI/ML and
research tooling.
In ATLAS-X: the entire backend (`atlas/`, `api/`, `tests/`). Chosen for
research credibility, sqlite3 stdlib, and local model HTTP clients. If
unavailable, nothing runs.

## FastAPI

General purpose: modern async web framework with dependency injection and
automatic validation.
In ATLAS-X: `api/__init__.py` creates the app, adds CORS middleware, exception
handlers, `/health` and `/ready` endpoints, and mounts routers under `/api/auth`,
`/api/tasks`, `/api/system`, `/api/tools`. If unavailable, only the CLI
(`atlas-x`) could drive the backend.

## SQLite

General purpose: embedded, file-based relational database.
In ATLAS-X: `atlas/storage/db.py` opens connections with WAL, foreign keys ON,
5s busy timeout. Schema is versioned (currently version 4) in
`atlas/storage/migrations.py`. Stores users, sessions, tasks, plans, executions,
artifacts, verifications, failures, recovery attempts, provenance events, etc.
Trade-off: single-file, zero install, but limited concurrency; OS file permissions
are the outer boundary. If unavailable, no persistence.

## Local model (Ollama + llama3.1:8b)

General purpose: run LLMs locally without cloud calls.
In ATLAS-X: `Settings.model_base_url` defaults to `http://127.0.0.1:11434` and
`model_name` to `llama3.1:8b`. The planner (`atlas/planner/service.py`) calls the
model once to produce a structured plan. The URL is restricted to loopback by
validation. Trade-off: slow on CPU (measured ~94s for a plan prompt) but keeps
data local and free. If Ollama is unavailable, planning fails with
`ModelUnavailable`.

## API schemas and validation (Pydantic)

General purpose: data validation and serialization.
In ATLAS-X: `Settings` (config) and request/response models in routers (e.g.
`CreateTaskRequest`, `RegisterRequest`). Enforces bounds like `max_task_chars`,
`max_plan_steps`. `extra="forbid"` prevents unknown fields. If absent, inputs
would be unvalidated.

## Authentication vs authorization

Authentication (identity): `atlas/auth/service.py` — registration, login, session
tokens (opaque, SHA-256 digest stored), expiry, lockout, password change. Answers
"who are you?"
Authorization (permission): `atlas/security/service.py` — `AuthorizationService`
is the single enforcement boundary; deny-by-default, ownership checks, tool
permission checks. Answers "may you do this?" Authentication is a prerequisite,
never a permission. Separating them prevents conflating identity with access.

## Tool registry

General purpose: a single authoritative list of invokable capabilities.
In ATLAS-X: `atlas/tools/registry.py` (`ToolRegistry`, `default_registry()`)
registers six built-in read-only analysis tools (`csv_statistics`,
`json_shape_inspect`, `numeric_summary`, `text_statistics`,
`artifact_metadata`, `task_graph_summary`) and freezes the registry. Tools are
code, not data, so adding a capability is a reviewed source change. The registry
describes capability; authorization grants authority.
## Sandbox

General purpose: confine untrusted execution.
In ATLAS-X: `atlas/sandbox/supervisor.py` launches the tool body inside a WSL2
guest (`Ubuntu-24.04`) via `wsl.exe`. There is no in-process fallback: if the
guest is unavailable, the call fails with `SandboxUnavailable`. Resource limits
(memory, PIDs, CPU, output bytes) are enforced in the guest. Trade-off: requires
WSL2; not a container or VM-grade boundary.

## Planning vs execution vs verification vs provenance

- Planning (`atlas/planner/`): model proposes a structured plan; validated
  deterministically against the registry. A plan is a proposal, never permission.
- Execution (`atlas/executor/`): runs a validated plan one authorized step at a
  time through the dispatcher and sandbox. Moves task to `executed` only.
- Verification (`atlas/verifier/`): independently re-derives results from persisted
  records and compares; produces PASS/FAIL. Only a PASS allows finalizing a result.
- Provenance (`atlas/storage` provenance repo + dispatch): append-only
  `provenance_events` recording tool invocations, outcomes, failures, recovery.
  Provides auditability; not a digital signature.

## Hashes

General purpose: fixed-size fingerprints of data.
In ATLAS-X: session tokens stored as SHA-256 digests (`atlas/auth/sessions.py`);
tool invocation input/output digests recorded in provenance; provenance chain
digests (`chain_digest`) for integrity checks. Hashes detect certain changes but
do not prove authenticity (no signing).

## JSONL

General purpose: append-only line-delimited JSON records.
In ATLAS-X: mentioned in Phase 1 docs as the format for provenance/evaluation
logs. The current implementation stores provenance events in SQLite
(`provenance_events`), not JSONL files. JSONL usage is therefore partially
implemented/aspirational. `max_log_bytes` bounds log growth.

## Tests, linting, type checking, production builds

- Pytest: 633 collected tests in `tests/` (backend). Run via `python -m pytest`.
- Ruff: `ruff check .` (config in `pyproject.toml`).
- Mypy: `mypy atlas` (Python 3.11 strict-ish).
- ESLint: `npm run lint` in `frontend/`.
- TypeScript: `tsc -b` in `npm run build`.
- Production build: `npm run build` -> `frontend/dist`, served by FastAPI.
These guard regressions and type safety; they are part of the quality gate.

## Frontend-backend communication

The frontend uses `fetch` with Bearer token from `localStorage` (`api.ts`).
Vite proxies `/api` to the backend in dev. In production, FastAPI serves the
built frontend and the same origin is used. Endpoints are REST JSON under
`/api/*`. Errors surface as `detail` strings.

## Failure behavior

Authorization denials raise `AuthorizationError` -> HTTP 403 "Access denied".
Auth failures -> 401. Tool errors -> 400/422. Verification refusal -> 409.
Task status moves to `failed` on execution failure (best effort). Recovery is
bounded by `max_recovery_attempts`.

## Local vs network

- Local only: SQLite, WSL2 guest, model inference (loopback), all tool execution.
- Network (loopback HTTP): planner -> Ollama on 127.0.0.1:11434. No cloud calls.
- Frontend dev server talks to backend via proxy (local).

## WSL2 / Windows / model dependencies

- Sandbox requires WSL2 with `Ubuntu-24.04` distribution provisioned
  (`atlas.sandbox.provision`). Windows hosts without WSL2 cannot run tools.
- Model requires Ollama installed separately and the model pulled.
- Backend/FastAPI run on Windows Python.

## Evidence

- `frontend/src/App.tsx`, `frontend/src/services/api.ts`
- `atlas/planner/service.py`, `atlas/executor/service.py`
- `atlas/verifier/service.py`, `atlas/tools/dispatch.py`
- `atlas/sandbox/supervisor.py`, `atlas/storage/db.py`
- `atlas/auth/service.py`, `atlas/security/service.py`

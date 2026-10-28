# ATLAS-X Technology Stack (Verified)

Status: **Audit-derived inventory.** This document records technologies actually
present in the repository as of the documentation audit. It distinguishes
declared, installed, imported, and actively used dependencies. Where a version
could not be verified from installed metadata, it is written as "not verified."

## Executive overview

ATLAS-X is a local-first research platform for studying reliable, verifiable,
secure multi-step AI agents. It consists of:

- A Python backend package (`atlas/`) implementing configuration, storage,
  authentication, authorization, planning, execution, tools, sandboxing,
  verification, failure classification, recovery, artifacts, and provenance.
- A FastAPI HTTP API (`api/`) exposing those capabilities over REST.
- A React + TypeScript + Vite web frontend (`frontend/`).
- The React frontend is the supported UI. A legacy Streamlit UI is not a dependency and is not part of the current runtime.
- A local model served by Ollama (default `llama3.1:8b`) used by the planner.
- SQLite (stdlib `sqlite3`) for persistence, with WAL and foreign keys.
- A WSL2-based sandbox for tool execution on Windows hosts.

## Candidate technologies: status summary

| Technology | Declared | Installed | Imported/used | Status |
|---|---|---|---|---|
| Python 3.11 | yes (>=3.11) | 3.11.0 | yes | runtime |
| FastAPI | yes | 0.162.0 | yes (`api/`) | runtime |
| Uvicorn | yes | 0.54.0 | yes (`api/server.py`) | runtime/dev |
| Pydantic | yes | 2.13.5 | yes | runtime |
| Argon2 (argon2-cffi) | yes | 23.1.0 | yes (`atlas/auth/password.py`) | runtime |
| Streamlit | no | not declared | no (`ui/` retired) | not used (legacy Streamlit UI retired) |
| React | yes (frontend) | ^18.3.1 | yes (`frontend/src`) | runtime |
| TypeScript | yes (frontend) | ~5.6.2 | yes | dev/build |
| Vite | yes (frontend) | ^5.4.10 | yes | dev/build |
| Axios | yes (frontend) | ^1.20.0 | no (frontend uses `fetch`) | declared, not imported |
| React Router | yes (frontend) | ^7.18.4 | yes | runtime |
| SQLite (stdlib) | stdlib | 3.38.4 | yes | runtime |
| python-jose | yes | not installed | no imports found | declared, unused |
| passlib[bcrypt] | yes | not installed | no imports found | declared, unused |
| Ollama daemon | external | 0.34.4 (docs) | HTTP via stdlib urllib | external service |
| NetworkX | not declared | not installed | no imports found | not used |
| SQLite FTS5 | stdlib | available | no usage found | not used |
| Playwright | dev (frontend) | ^1.64.1 | yes (frontend/tests) | test |
| ESLint | dev (frontend) | ^9.13.0 | yes | dev |
| Ruff | dev | >=0.4 | yes (config) | dev |
| Mypy | dev | >=1.10 | yes (config) | dev |
| Pytest | dev | >=8 | yes | test |

## Backend Python dependencies (pyproject.toml)

Source: `pyproject.toml` lines 11-20.

Runtime dependencies:
- `pydantic>=2.5,<3` (installed 2.13.5)
- `argon2-cffi>=23.1,<25` (installed 23.1.0)
- `fastapi>=0.109,<0.112` (installed 0.162.0 — exceeds declared upper bound)
- `uvicorn[standard]>=0.27,<0.33` (installed 0.54.0 — exceeds declared upper bound)
- `python-multipart>=0.0.9,<0.0.13`
- `python-jose[cryptography]>=3.3,<3.4` (not installed; no imports)
- `passlib[bcrypt]>=1.7.4,<1.8` (not installed; no imports)

Dev dependencies (`[project.optional-dependencies] dev`):
- `pytest>=8`
- `ruff>=0.4`
- `mypy>=1.10`

Build system: setuptools>=68.

Console script: `atlas-x = "atlas.cli:main"` (`pyproject.toml` lines 29-30).
## Frontend dependencies (frontend/package.json)

Runtime:
- `axios ^1.20.0` — declared; not imported anywhere in `frontend/src` (frontend uses `fetch`).
- `react ^18.3.1`
- `react-dom ^18.3.1`
- `react-router-dom ^7.18.4`

Dev:
- `@eslint/js ^9.13.0`
- `@playwright/test ^1.64.1`
- `@types/react ^18.3.12`
- `@types/react-dom ^18.3.1`
- `@vitejs/plugin-react ^4.3.3`
- `eslint ^9.13.0`
- `eslint-plugin-react-hooks ^5.0.0`
- `eslint-plugin-react-refresh ^0.4.14`
- `globals ^15.11.0`
- `typescript ~5.6.2`
- `typescript-eslint ^8.11.0`
- `vite ^5.4.10`

## Technology-to-purpose matrix

| Technology | Category | Where used | Purpose in ATLAS-X |
|---|---|---|---|
| Python 3.11 | Language | entire backend | Core language; type hints, dataclasses, stdlib sqlite3/urllib/subprocess |
| FastAPI | Web framework | `api/__init__.py`, routers | HTTP API, routing, dependency injection, validation, exception handlers |
| Uvicorn | ASGI server | `api/server.py` | Serves `api:app` on 127.0.0.1:8000 with reload |
| Pydantic | Validation | `atlas/config/settings.py`, API routers | Settings validation, request/response schemas, fail-closed bounds |
| Argon2 (argon2-cffi) | Password hashing | `atlas/auth/password.py` | Argon2id password hashing |
| Streamlit | UI framework | retired `ui/` package | Not a dependency; legacy UI removed from the supported runtime |
| React 18 | UI framework | `frontend/src` | Component-based SPA |
| TypeScript ~5.6 | Language | `frontend/src` | Static typing for frontend |
| Vite 5 | Build tool | `frontend/vite.config.ts` | Dev server (port 5173), proxy `/api` to 8000, production build |
| React Router 7 | Routing | `frontend/src/App.tsx` | Client-side routes and protected routes |
| SQLite 3.38 | Database | `atlas/storage/db.py` | Single-file relational persistence, WAL, FKs |
| secrets (stdlib) | Crypto | `atlas/auth/sessions.py` | Opaque session token generation |
| hashlib (stdlib) | Hashing | dispatch/provenance | SHA-256 token digests, content digests |
| subprocess (stdlib) | Process control | `atlas/sandbox/supervisor.py` | Launches `wsl.exe` guest |
| urllib (stdlib) | HTTP client | `atlas/planner/model.py` (inferred) | Talks to Ollama HTTP API on loopback |
| Ollama | Model runtime | external daemon | Serves local LLM; default `llama3.1:8b` |
| Playwright | E2E testing | `frontend/tests`, `frontend/playwright.config.ts` | Browser tests against Vite dev server |
| Ruff | Linting | `pyproject.toml` | Python lint (`E,F,I,W`) |
| Mypy | Type checking | `pyproject.toml` | Static type checking (Python 3.11) |
| ESLint 9 | Linting | `frontend/eslint.config.js` | Frontend lint |
| TypeScript compiler | Type checking/build | `frontend/package.json` scripts | `tsc -b && vite build` |
| Pytest | Testing | `tests/`, `pyproject.toml` | Backend test runner (633 collected) |

## External/non-Python infrastructure

- WSL2 distribution `Ubuntu-24.04` (default) — guest for sandboxed tool execution.
- Ollama daemon on `http://127.0.0.1:11434` — local model inference.
- No Docker (per environment reconnaissance). Docker is documented as optional enhancement only.

## Declared but unused / not installed

- `python-jose[cryptography]` and `passlib[bcrypt]`: declared in `pyproject.toml`, not installed in the venv, and no imports found. Authentication uses Argon2 directly and custom session tokens; these appear to be legacy/placeholder dependencies from the Phase 1 plan.
- `axios`: declared in `frontend/package.json`, not imported in `frontend/src` (the frontend uses `fetch`).
- `networkx`: mentioned in the Phase 1 technology stack document as a candidate; no imports found.
- SQLite FTS5: mentioned as candidate; no usage found in code.
- `python-multipart`: declared; usage not directly verified (likely transitive FastAPI support).

## Version discrepancy note

Installed versions of FastAPI (0.162.0) and Uvicorn (0.54.0) exceed the upper bounds declared in `pyproject.toml` (`<0.112`, `<0.33`). This is a documented discrepancy between the manifest and the installed environment; the code runs against the newer versions. The audit does not change dependencies.

## Evidence

- `pyproject.toml`
- `frontend/package.json`
- `api/server.py`, `api/__init__.py`
- `atlas/config/settings.py`
- `frontend/vite.config.ts`
- `docs/TECHNOLOGY_STACK.md` (historical Phase 1 document; partially superseded by actual implementation)

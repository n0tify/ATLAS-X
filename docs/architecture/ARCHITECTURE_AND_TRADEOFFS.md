# Architecture and Trade-offs

## Local-first execution

- Decision: everything runs on the operator's machine; no cloud services.
- Evidence: `Settings` loopback-only model URL; SQLite; WSL2 sandbox.
- Benefits: privacy, zero cost, offline capability.
- Limitations: single host, no horizontal scaling, laptop resource bounds.
- Alternatives: cloud-hosted DB/model (rejected by design).
- Status: implemented.

## Local LLM inference (Ollama)

- Decision: use a single local model (`llama3.1:8b`) via Ollama HTTP on loopback.
- Evidence: `Settings.model_base_url`, `atlas/planner/model.py`.
- Benefits: free, private, reproducible model version.
- Limitations: slow on CPU (~94s/plan), model quality constraints, requires separate install.
- Alternatives: hosted APIs (rejected: cost/privacy).
- Status: implemented (planner only; no embeddings/RAG).

## Frontend/backend separation

- Decision: React SPA + FastAPI API. The React frontend is the supported UI.
- Evidence: `frontend/`, `api/`.
- Benefits: clear API boundary, testable frontend, typed client.
- Limitations: frontend toolchain required; CORS configuration needed.
- Status: implemented. A legacy Streamlit UI previously existed under `ui/`; it is not a runtime dependency in `pyproject.toml`, has no runtime imports in the backend, and is retired from the working tree. Its Git index state still contains staged additions plus working-tree deletions; see `docs/audits/PUBLIC_RELEASE_CHECKLIST.md`.

## SQLite-first persistence

- Decision: stdlib sqlite3, WAL, FKs, versioned schema (v4).
- Evidence: `atlas/storage/db.py`, `atlas/storage/migrations.py`.
- Benefits: zero install, single file, transactional.
- Limitations: limited concurrency; OS permissions are outer boundary; no encryption at rest.
- Alternatives: Postgres (heavier, server process).
- Status: implemented.

## Task and execution identity

- Decision: tasks owned by users; executions are siblings under a task with attempt
  numbers; plans can supersede.
- Evidence: schema v3 (supersedes_plan_id), `task_status.py`.
- Benefits: auditability of attempts; no overwrite of history.
- Limitations: schema migration complexity (rebuild plans table).
- Status: implemented.

## Tool registration and dispatch

- Decision: tools are code-registered, frozen registry; single dispatch boundary.
- Evidence: `atlas/tools/registry.py`, `atlas/tools/dispatch.py`.
- Benefits: reviewed capability changes; authorization separate from capability.
- Limitations: in-process registry attribute readable by trusted code (documented).
- Status: implemented.

## Authorization boundaries

- Decision: deny-by-default `AuthorizationService`; no roles; ownership only.
- Evidence: `atlas/security/service.py`, `SECURITY.md`.
- Benefits: simple, auditable, no elevation path.
- Limitations: no roles/MFA; process-level trust (SQL bypass possible).
- Status: implemented.

## Subprocess/WSL2 isolation

- Decision: every tool runs in a WSL2 guest; no in-process fallback.
- Evidence: `atlas/sandbox/supervisor.py`.
- Benefits: real process/filesystem boundary; resource limits in guest.
- Limitations: requires WSL2; guest kernel/TCB trusted; supervisor unconfined (A12.5 caveat); not container-grade.
- Alternatives: Docker (not installed; documented optional).
- Status: implemented.

## Independent verification

- Decision: a separate verifier re-derives results from persisted records; only PASS
  finalizes a result.
- Evidence: `atlas/verifier/service.py`.
- Benefits: model cannot self-grade; deterministic, reproducible.
- Limitations: rules are per-tool; verifier cannot prove semantic correctness
  beyond declared contracts.
- Status: implemented.

## Provenance and integrity checks

- Decision: append-only `provenance_events` with chain digests; verification endpoint.
- Evidence: `atlas/storage/repositories.py` (ProvenanceRepo), dispatch.
- Benefits: audit trail, tamper detection of certain changes.
- Limitations: not signed/chained cryptographically; mutable by DB holders; digests are identifiers not proof.
- Status: implemented (Phase 14 lineage).

## Caching and session management

- Decision: opaque tokens, SHA-256 digest stored, TTL, lazy expiry purge, lockout.
- Evidence: `atlas/auth/sessions.py`, `atlas/auth/service.py`.
- Benefits: no raw token at rest; revocation on password change.
- Limitations: in-process lockout resets on restart; no MFA.
- Status: implemented.

## Resource budgets and timeout handling

- Decision: explicit positive capped bounds in `Settings`; enforced at call sites.
- Evidence: `atlas/config/settings.py`, executor `_check_budget`.
- Benefits: no unlimited defaults; laptop-safe.
- Limitations: host elapsed budget checked after call returns (guest enforces real limit).
- Status: implemented.

## Testing and reproducibility

- Decision: pytest backend, Playwright frontend, ruff, mypy, tsc/eslint.
- Evidence: `pyproject.toml`, `frontend/package.json`.
- Benefits: regression detection, type safety.
- Limitations: live model tests require Ollama; sandbox tests require WSL2.
- Status: implemented.

## Windows development constraints

- Decision: develop on Windows; WSL2 only for sandbox guest; no Docker.
- Evidence: environment reconnaissance; `docs/TECHNOLOGY_STACK.md`.
- Benefits: matches target machine; no Docker install.
- Limitations: POSIX-only sandbox code type-checked on Windows with relaxations.
- Status: implemented.

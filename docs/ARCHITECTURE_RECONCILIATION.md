# Architecture Reconciliation

Status: **Phase 4 reconciliation gate.** This document compares the approved
documentation set against the actual repository state and records alignment,
gaps, security gaps, contradictions, the current execution boundary, required
next gates, and necessary corrections. Nothing herein adds functionality.

## 1. Implemented Components

Factual inventory of the repository (module → responsibility → status → tests).

| Module | Responsibility | Status | Tests |
|---|---|---|---|
| `atlas/config/settings.py` | Pydantic `Settings`; env-driven (`ATLAS_*`); bounded positive limits; fail-closed in production; `safe_dump()` excludes secrets | Implemented | `tests/test_config.py` |
| `atlas/storage` | SQLite: `Database` (WAL, FK on, busy timeout, transactional scope), deterministic `init_db`, 13-table schema | Implemented | `tests/test_storage.py` |
| `atlas/storage/repositories.py` | Parameterized repos: `UserRepo`, `SessionRepo`, `TaskRepo` (ownership in SQL), `ProvenanceRepo` | Implemented (4 repos) | `test_storage.py`, `test_auth.py` |
| `atlas/auth` | Argon2id hashing; opaque session tokens (SHA-256 digest at rest); expiry; lockout; generic errors; password change | Implemented | `tests/test_auth.py` |
| `atlas/security/logging.py` | `SecretsRedactionFilter` for log output | Implemented | `tests/test_config.py` |
| `atlas/util.py` | UTC ISO time helpers | Implemented | used by storage/auth tests |
| `atlas/cli.py` | `atlas-x` health/smoke command (schema init + auth bootstrap) | Implemented | smoke run (manual) |
| `planner/ executor/ verifier/ recovery/ tools/ sandbox/ provenance/ evaluation/` | Package placeholders with one-line docstrings only | Placeholders — **not implementation** | none |
| `tests/` | 36 tests: config (9), storage (8), auth (17+), conftest | Implemented, green | — |
| `pyproject.toml` | Build + deps: pydantic, argon2-cffi (runtime); pytest, ruff, mypy (dev); ruff/mypy/pytest config | Implemented | — |
| Root docs | README, SECURITY, CONTRIBUTING, LICENSE (placeholder), `.env.example`, `.gitignore` | Implemented | — |

Verification on this run (see section 9): **36 passed**, **Ruff clean**,
**mypy clean (23 files)**.

## 2. Documentation-to-Code Alignment

| Documented Component | Expected Responsibility | Current Implementation | Status |
|---|---|---|---|
| Configuration + resource bounds | Bounded, validated, fail-closed settings | `atlas/config/settings.py` + 9 tests | ALIGNED |
| SQLite persistence schema | Tables/FK/indexes, deterministic init | `atlas/storage/migrations.py` | ALIGNED |
| Repository layer | Parameterized, ownership-scoped queries | Repos for users/sessions/tasks/provenance | PARTIALLY ALIGNED |
| Authentication | Register/login/logout/validate/expiry/lockout/password change | `atlas/auth/` + 17 tests | ALIGNED |
| Security logging / redaction | No secrets in logs or responses | `atlas/security/logging.py` | ALIGNED |
| Health/smoke entry point | `atlas-x` command | `atlas/cli.py` | ALIGNED |
| Lifecycle stage 2: Authorization | Authorize caller/action/resource | No authorization layer | NOT IMPLEMENTED |
| Planner (spec stage 5-6) | Plan generation + deterministic validation | Placeholder only | NOT IMPLEMENTED |
| Orchestrator/executor (stage 8) | Execution state machine | Placeholder only | NOT IMPLEMENTED |
| Tool registry + permissions (stage 7) | Whitelist, schemas, Tool/ToolPermission | Placeholder; no schema | NOT IMPLEMENTED |
| Sandbox (stage 8) | Bounded, isolated execution (hard gate) | Placeholder; no code path | NOT IMPLEMENTED |
| Verifier (stage 10/15) | Deterministic PASS/FAIL | Placeholder only | NOT IMPLEMENTED |
| Recovery (stages 11-13) | Classification, diagnosis, bounded replan | Placeholder only | NOT IMPLEMENTED |
| Provenance recording | Append-only audit per lifecycle | Schema + `ProvenanceRepo`; no lifecycle producers yet | PARTIALLY ALIGNED |
| Evaluation + benchmarks | Harness, vari-ants, metrics, reproducibility | Schema (`evaluation_runs`) + empty dirs | PARTIALLY ALIGNED |
| UI (Streamlit-first) | Local interface | Not started | NOT IMPLEMENTED |
| Model runtime integration (Ollama) | Primary local model use | Runtime on host; no code path | NOT IMPLEMENTED |
| Data-science libs (NumPy/pandas/SciPy/sklearn/matplotlib) | Analysis/plots | Selected in stack doc; **not installed** | NOT IMPLEMENTED (deferred) |
| Documentation gates 0-3 | − | All five files present | ALIGNED |

## 3. Architecture Gaps

Concrete gaps between `SYSTEM_SPECIFICATION.md` / `THREAT_MODEL.md` /
`TECHNOLOGY_STACK.md` and the code (not fixed here):

1. **No authorization layer** (spec stage 2; threats A3, A4, D1). Only
   repository-level ownership scoping exists.
2. **No tool registry, policies, or Tool/ToolPermission schema** (threats B2,
   C1, C2). Deny-by-default is designed, not enforced.
3. **No sandbox** (threats B3, C3-C7). No sandboxed execution path exists at
   all; this is the hard Phase 10 gate.
4. **No orchestrator/executor stub, no plan validator, no verifier, no
   recovery state machine.** Lifecycle stages 5-15 are unimplemented.
5. **No domain/repository objects** for Plan, PlanStep, Execution, Artifact,
   Verification, Failure, RecoveryAttempt (tables exist; logic does not).
6. **No model integration**: `Settings.model_*` fields exist but no code talks
   to Ollama.
7. **No Streamlit UI**, no cookie/session wiring to a browser boundary (T1).
8. **Resource bounds are not consumed yet**: auth uses TTL/lockout/delay only;
   the execution/artifact/dataset/log limits have no enforcement call sites.
9. **No evaluation harness or metrics**; `evaluation_runs` table + empty
   `benchmarks/` dirs only.

## 4. Security Gaps

Controls documented but not yet implemented (do not treat these as existing):

| Control | Status in code | Blocking threat(s) |
|---|---|---|
| Authorization (roles/permissions) at any API/task layer | Absent | A4 (privilege escalation), D1 |
| Per-resource ownership beyond direct `TaskRepo.user_id` scoping | Absent for executions/artifacts/provenance queries | A3 (BOLA), D1 |
| Tool permission enforcement (ToolPermission) | Absent | B2, C1 |
| Sandbox isolation (process + FS + resource) | Absent — no execution path exists | B3, C3, C4, C5 |
| Filesystem confinement at runtime | Absent (only SQLite writes into project) | C4 |
| Network restriction for executed code | Absent (nothing executes yet) | C5, C6 |
| Enforcement of `Settings` resource limits at runtime | Absent (config-only today) | C6, C7 |
| Provenance integrity (checksums/chain) | Absent (append-only by policy only) | D4 |
| Verification-bypass invariant ("no final result without recording PASS") | Absent (no orchestrator) | B5, B6 |

Safety-by-absence note: the system is currently safe against generated-code
attacks **only because it executes nothing** (no subprocess/tool/model code
path exists). That is not a control; it disappears the moment any execution
landscape is added, which is why the sandbox is a hard gate.

## 5. Contradictions

1. **`SECURITY.md` stated the threat model was "scheduled, not present"** while
   `docs/THREAT_MODEL.md` exists → corrected in this phase (doc-only).
2. **Early skeleton sketch listed `apps/api` + `apps/web`;** the repository has
   no `apps/` tree. This is the intended outcome of the Streamlit-first decision
   (`TECHNOLOGY_STACK.md`) and is recorded, not silently reverted.
3. **Gate prompts named `config/` and `tests/config/`; implementation uses
   `atlas/config/` (Python package) and `tests/test_config.py`.** Consistent with
   a `src`-style package layout; not a security issue, but the naming difference
   between the old prompt and the repo should be intentional, not accidental.
4. **"Streamlit-first" recorded in `DECISIONS.md`, yet Streamlit is not a
   dependency.** Not a contradiction: the stack installs dependencies phase-wise.
   Recorded so reviewers do not mistake it for missing scope.
5. **`DECISIONS.md` is frozen ("no additional decisions yet"),** while later
   decisions (subprocess-first sandbox, model default, FastAPI-deferred) now
   live in `TECHNOLOGY_STACK.md`. Separation is intended; `DECISIONS.md` should
   be re-opened at an approved gate if new standing decisions accumulate.

## 6. Current Execution Boundary

What can and cannot execute on this host right now (Windows, no Docker, no WSL
distribution, 15.7 GB RAM):

- **Application code (canonical, trusted):** the `atlas` package runs under the
  system interpreter. It performs local SQLite IO, Argon2 hashing, and no
  network calls. Reads/writes are project-scoped.
- **Trusted local code:** the test suite and `atlas-x` CLI run under the same
  interpreter; both are project-authored and reviewed. No model is invoked.
- **Future tool execution:** tool registry and sandbox are not implemented. No
  subprocess/work API exists in the codebase.
- **Future generated-code execution:** none exists. When introduced, it must
  arrive only through the Phase 10 hard gate. A subprocess sandbox on this host
  is **resource control, not container isolation** — arbitrary generated code
  could still reach host files, which is why `THREAT_MODEL.md` rates B3/C4/C5
  residual risk as **Hi** until Phase 10 lands with scope-enforcing tests.

## 7. Required Next Gates

Precise order, per the approved sequence:

1. Configuration review (05)
2. Storage review (06)
3. Authentication review (07)
4. Authorization implementation + review (08) — security gate
5. Tool registry (09)
6. Sandbox design + implementation (10) — **HARD security gate**
7. Planner (11), orchestrator (12), verifier (13), provenance (14),
   failure classification (15), recovery (16)
8. First end-to-end agent (18), security testing (19), UI (20),
   evaluation/ablations/reproducibility/docs (21-33)

None of these are to be started by this phase.

## 8. Recommended Corrections

Only corrections necessary for reconciliation accuracy; no code changes:

1. **`SECURITY.md`** — point to `docs/THREAT_MODEL.md` as the authoritative
   mapping (applied in this phase).
2. **`README.md`** — status table updated to reflect completed documentation
   gates and the placeholder-only state of future modules (applied).
3. **Module naming drift** (`atlas/config` vs `config/`, `tests/test_config.py`
   vs `tests/config/`) — keep current Python-package layout; record the choice
   rather than force a directory move.
4. **Re-open `DECISIONS.md` at an approved gate** to fold in decisions that
   have accumulated since Phase 0 (sandbox posture, primary model, FastAPI
   deferred) if the human gatekeeper wants standing decisions centralized.
5. **Do not add Tool/ToolPermission/BenchmarkTask tables now** — schema drift
   belongs to the phases that define them (09, 21), not to this phase.

## 9. Verification (this phase)

- `pytest` → **36 passed**
- `ruff check .` → **All checks passed**
- `mypy atlas` → **Success: no issues found in 23 source files**

Files modified in this phase: `docs/ARCHITECTURE_RECONCILIATION.md` (created),
`SECURITY.md` (doc-only pointer), `README.md` (status table update).

---

## 10. Addendum — Phase 08 authorization (2026-10-01)

Sections 1–9 are the Phase 4 snapshot and are deliberately left unedited. This
addendum supersedes specific rows of that snapshot. The authoritative record of
what the layer does and does not establish is `docs/AUTHORIZATION_REVIEW.md`.

### 10.1 Components added

| Module | Responsibility | Status | Tests |
|---|---|---|---|
| `atlas/security/policy.py` | `Resource`, `Operation`, `DenyReason`, `Decision`, immutable `PERMITTED_OPERATIONS`, `decide_operation`, `decide_tool_invocation`, prohibited capability names, strict id validation | Implemented | `tests/test_authorization.py` |
| `atlas/security/errors.py` | `AuthorizationError` and subclasses; every external message is exactly `access denied` | Implemented | `tests/test_authorization.py` |
| `atlas/security/identity.py` | `Identity`, `IdentityResolver`; derives the actor from a session token via `AuthService.validate_session` | Implemented | `tests/test_authorization.py` |
| `atlas/security/service.py` | `AuthorizationService`; the single enforcement boundary, with no public method accepting a caller-supplied `user_id` | Implemented | `tests/test_authorization.py` |
| `atlas/storage/owned_resources.py` | Owner-scoped SQL for every task descendant and for provenance, with fixed join and ownership predicates | Implemented | `tests/test_authorization.py` |

### 10.2 Snapshot rows superseded

| Snapshot location | Phase 4 text | Now |
|---|---|---|
| §1, §2 — Authorization | "No authorization layer" / NOT IMPLEMENTED | **Implemented and tested.** Deny-by-default, ownership-only; no roles and no elevation path |
| §2 — Repository layer | PARTIALLY ALIGNED (ownership for users/sessions/tasks/provenance only) | ALIGNED for all eight task-descendant kinds; plans, plan steps, executions, artifacts, verifications, failures, and recovery attempts are now owner-scoped |
| §3.1, §3.2 | "No authorization layer" / "tool permissions … designed, not enforced" | §3.1 closed for storage-facing operations. §3.2 still open: tool *permission decisions* exist, but no registry, grant store, or execution path exists, so every tool decision denies |
| §4 — "Authorization (roles/permissions)" and "per-resource ownership beyond `TaskRepo.user_id`" | Absent | Both closed for user-owned data. No role model exists or is planned, so the "roles" half is accepted as not-applicable rather than delivered |
| §4 — Tool permission enforcement, sandbox, FS confinement, network restriction, runtime resource limits, provenance integrity, verification-bypass invariant | Absent | Unchanged. All remain Phase 09, 10, 12/14, and 13 work respectively |
| §6 — "Future tool execution" | Not implemented | Unchanged; Phase 09 |

### 10.3 Gaps that authorization did not close

- `evaluation_runs` has no owner and is denied by name (AZ-01). The ownership
  decision is still deferred to `docs/STORAGE_REVIEW.md` §12.3.
- Provenance events with neither `task_id` nor `execution_id` have no resolvable
  owner and are denied to every user (AZ-02).
- `AuthService.change_password(user_id, ...)` is still not bound to a session
  principal (AZ-03), and no surface exposes password management.
- Any component holding a `sqlite3.Connection` can still bypass every predicate.
  Authorization covers callers of `AuthorizationService`, not SQL itself.
- No HTTP, browser, or UI surface exists, so the boundary is exercised only
  in-process; no remote caller is gated yet.

### 10.4 Gate status

Section 7 item 4 (authorization implementation + review) is **complete**. Item 5
(tool registry) is next and is **not** started. The Phase 10 sandbox hard gate is
unchanged.

Verification for this addendum is recorded in `docs/AUTHORIZATION_REVIEW.md`.

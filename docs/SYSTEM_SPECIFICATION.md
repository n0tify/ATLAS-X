# ATLAS-X System Specification

Status: **specification gate (Phase 2).** Reference architecture for
implementation. No application functionality was implemented by this phase.

## 1. Definition

> ATLAS-X is a local-first research platform for studying reliable, verifiable,
> secure multi-step AI agents.

## 2. Central research question

> How do explicit planning, deterministic verification, provenance tracking,
> controlled tool execution, and bounded recovery affect the reliability and
> auditability of local multi-step AI agents?

Decomposed hypotheses (all measured, none assumed):

- H1 — Structured planning validated by deterministic code improves step
  success versus planning-free tool use.
- H2 — An independent deterministic verifier catches outputs the model would
  present as correct; PASS/FAIL rates are measurable across ablation variants.
- H3 — Bounded recovery (classification → diagnosis → replan → retry) improves
  final-task success without allowing unbounded loops.
- H4 — Provenance recording enables auditability: every step of a run can be
  replayed and attributed without additional model calls.

## 3. System boundaries

ATLAS-X **is**: a local, single-host, research-grade platform that plans tasks,
runs them through a whitelisted, bounded tool environment, verifies outputs
deterministically, records provenance, and measures reliability under ablation.

ATLAS-X **is NOT**:

- a general autonomous computer controller
- a cloud service or SaaS
- a general-purpose operating-system agent
- an unrestricted code execution system
- a system that claims factual correctness merely because an LLM produced an
  answer (outputs must pass the verifier before they are claims)
- a system that automatically performs privileged actions
- an identity provider or internet-scale auth system

## 4. Core execution lifecycle

Each stage names its owning component and the record it produces.

1. **User authentication** — `auth/`; establishes the caller (session).
2. **Authorization** — `security/` (Phase 8); checks the caller may perform the
   requested action on the target resource (ownership + permission).
3. **Task creation** — `storage/`; validated, bounded task stored with owner.
4. **Task validation** — input validation layer; length/schema/ownership checks
   against `Settings` bounds.
5. **Plan generation** — `planner/` (Phase 11); model produces a structured
   plan from the goal.
6. **Plan validation** — deterministic validator; malformed steps are failures,
   not execution paths.
7. **Tool authorization** — `tools/` + `security/`; step's tool must be
   registered, permitted for the caller, and argument-validated.
8. **Sandboxed execution** — `sandbox/` (Phase 10, hard security gate);
   subprocess sandbox with enforced resource, filesystem, and time bounds.
9. **Artifact generation** — artifacts written only inside the sandbox root,
   capped in size, checksummed.
10. **Deterministic verification** — `verifier/` (Phase 13); PASS/FAIL.
11. **Failure classification** — `recovery/` (Phase 15); a failure record with a
    category.
12. **Diagnosis** — deterministic inspection of the failure plus artifacts.
13. **Bounded recovery/replanning** — within `max_recovery_attempts`; a renewed
    plan re-enters validation.
14. **Re-execution** — a new `Execution` attempt under the same task.
15. **Re-verification** — verifier runs again; loop terminates at acceptance,
    attempt cap, or explicit stop.
16. **Provenance recording** — append-only `provenance_events` per lifecycle
    transition (actors: user, planner, executor, verifier, recovery).
17. **Final result** — only a verified result (or a bounded, recorded failure)
    is finalized and returned.
18. **Evaluation logging** — run-level metrics written for benchmarking, never
    conflated with live traffic.

## 5. Core entities

For each: purpose, essential fields, key relationships, security implications.
Persisted-where mapping refers to the schema in `atlas/storage/migrations.py`.

### User
- Purpose: the human identity that owns resources and sessions.
- Fields: `id`, `username`, `password_hash` (Argon2id only), `failed_login_attempts`,
  `locked_until`, `created_at`, `updated_at`.
- Relationships: owns sessions, tasks, and everything derived from tasks.
- Security: hashes only; generic auth errors (no enumeration); per-account
  lockout; deletion cascades owned data (by design, documented).

### Session
- Purpose: verifiable proof of an authenticated caller.
- Fields: `id`, `user_id`, `token_hash` (SHA-256 of opaque token), `created_at`,
  `expires_at`, `revoked_at`.
- Relationships: belongs to a User; backs every authorized action.
- Security: raw token never persisted; expiry enforced on every validation;
  revocation is hard-delete/flag; logout and password change revoke.

### Task
- Purpose: the unit of research work.
- Fields: `id`, `user_id`, `title`, `goal`, `status`, `created_at`, `updated_at`.
- Relationships: owned by a User; target of Plans and Executions; referenced by
  provenance events.
- Security: SQL-level ownership (`WHERE user_id = ?`); `goal` is untrusted text
  (prompt-injection surface) and is treated as data, never as instructions.

### Plan
- Purpose: structured decomposition of a goal.
- Fields: `id`, `task_id` (unique), `plan_json`, `validated` (0/1), timestamps.
- Relationships: exactly one per task; contains PlanSteps.
- Security: `plan_json` must pass the deterministic validator before any
  execution; unvalidated plans never reach tools.

### PlanStep
- Purpose: one atomic planned action.
- Fields: `id`, `plan_id`, `position`, `action`, `tool_name`, `input_json`,
  `status`, timestamps.
- Relationships: part of a Plan; selects a registered Tool.
- Security: `tool_name` must match a registered, permitted tool; `input_json`
  validated against the tool's declared input schema; `max_plan_steps` caps the
  plan length.

### Tool
- Purpose: named, schema'd capability the platform exposes to steps (Phase 9,
  `tools/`).
- Fields (planned): `id`, `name`, `description`, `input_schema`, `policy`,
  `enabled`.
- Relationships: referenced by PlanSteps; governed by ToolPermission.
- Security: deny-by-default registry; tools are assigned by id/name, never by
  free-text commands; no "run arbitrary shell" tool.

### ToolPermission
- Purpose: explicit grant of a tool to a caller.
- Fields (planned): `id`, `user_id`, `tool_id`, `granted_by`, timestamps, scope.
- Relationships: binds Users to Tools.
- Security: absence = denial; grants are auditable and revocable.

### Execution
- Purpose: one concrete attempt to run a task.
- Fields: `id`, `task_id`, `attempt`, `status`, `started_at`, `finished_at`,
  `result_json`, `error`.
- Relationships: belongs to a Task; parent of Artifacts, Verifications,
  Failures, RecoveryAttempts.
- Security: attempt counter enforces bounded recovery; result untrusted until a
  matching Verification PASS exists.

### Artifact
- Purpose: produced file or text output.
- Fields: `id`, `execution_id`, `name`, `kind`, `relative_path`, `content`,
  `size_bytes`, `checksum`, `created_at`.
- Relationships: belongs to an Execution.
- Security: only relative paths under the sandbox root; `max_artifact_bytes`
  enforced at write time; absolute host paths rejected; checksum supports
  integrity checks.

### Verification
- Purpose: deterministic acceptance check of an execution result.
- Fields: `id`, `execution_id`, `verifier`, `result` (PASS/FAIL), `detail_json`,
  `created_at`.
- Relationships: belongs to an Execution.
- Security: verifier is code, not model; it cannot be talked into PASS by
  prompt or argument.

### Failure
- Purpose: classified record of one failure.
- Fields: `id`, `execution_id`, `category`, `diagnosis`, `detail_json`,
  `created_at`.
- Relationships: belongs to an Execution; feeds recovery classification.
- Security: diagnosis is deterministic inspection output; full event audit trail
  retained.

### RecoveryAttempt
- Purpose: one bounded replan cycle.
- Fields: `id`, `execution_id`, `attempt_no`, `diagnosis`, `new_plan_json`,
  `outcome`, `created_at`.
- Relationships: belongs to an Execution.
- Security: `attempt_no` capped by `max_recovery_attempts`; `new_plan_json`
  re-enters plan validation before execution.

### ProvenanceEvent
- Purpose: immutable-ish audit record of a lifecycle transition.
- Fields: `id`, `task_id`, `execution_id`, `event_type`, `actor`, `detail_json`,
  `created_at`.
- Relationships: ties to a Task or Execution; survives task deletion with
  nullable keys.
- Security: append-only by application policy; detail payloads redact secrets;
  actor values are fixed roles (user/planner/executor/verifier/recovery).

### EvaluationRun
- Purpose: one reproducible benchmark run.
- Fields: `id`, `run_name` (unique), `config_json`, `status`, `results_json`,
  `started_at`, `finished_at`, `created_at`.
- Relationships: aggregates BenchmarkTasks; source of results for `reports/`.
- Security: config serialized with the run so results are reproducible; results
  are distinguished from hypotheses in every report.

### BenchmarkTask
- Purpose: one evaluation item inside a run (planned for `benchmarks/`).
- Fields (planned): `id`, `run_id`, `task_id`, `variant` (baseline/ablation id),
  `expected`, `metrics_json`.
- Relationships: belongs to an EvaluationRun; references a Task template.
- Security: inputs are canonically versioned to prevent silent mutation between
  ablations (poisoned-input defense is a modeled threat).

## 6. Security principles

| Principle | Enforcement |
|---|---|
| Least privilege | Tools and roles granted narrowly; caller only sees owned rows |
| Deny by default | Unknown tool, missing permission, missing session → denial |
| Explicit authorization | Authorization layer (Phase 8) precedes every action |
| Isolation | Sandbox boundary separates execution from host; project-scoped FS |
| No secret exposure | Passwords/keys/tokens never logged or returned; redaction filter |
| No arbitrary host execution | No privileged/OS-wide execution; whitelisted tools only |
| Bounded resource consumption | Every bound in `Settings` is positive and capped |
| Immutable/append-only audit events | Provenance events are append-only by policy |
| Safe error handling | Generic auth errors; failures become data (Failure records) |
| Input validation | Pydantic at the boundary; task/plan/tool-input validation |
| Output validation | Deterministic verifier gates every final result |

## 7. Research principles

| Principle | Enforcement |
|---|---|
| Reproducibility | `docker`-free local run documented; config serialized per run |
| Controlled baselines | Baseline variants defined in ATLAS-BENCH with fixed task sets |
| Ablation studies | Planning / verification / recovery toggled independently |
| Explicit metrics | Pre-registered metric names and definitions per run |
| No fabricated results | Every reported number traces to a stored EvaluationRun |
| No cherry-picking | Full result sets from runs, including failures, in `reports/` |
| Hypothesis vs measured | Research claims labelled as hypothesis or measured result |
| Deterministic verification | Verifier code is deterministic and repeatable |

## 8. Traceability

Lifecycle stage → module/phase → persisted record:

| Lifecycle stage | Component | Primary record |
|---|---|---|
| Authentication | `auth/` (done) | sessions, users |
| Authorization | `security/` Phase 8 | — |
| Task creation/validation | `storage/` (done) | tasks |
| Plan generation/validation | `planner/` Phase 11 | plans, plan_steps (validated) |
| Tool authorization | `tools/` + `security/` Phases 8-9 | tools, tool_permissions |
| Sandboxed execution | `sandbox/` Phase 10 | executions |
| Artifacts | `sandbox/` Phase 10 | artifacts |
| Verification | `verifier/` Phase 13 | verifications |
| Failure/diagnosis | `recovery/` Phase 15 | failures |
| Recovery | `recovery/` Phase 16 | recovery_attempts |
| Provenance | `provenance/` + `storage/` | provenance_events |
| Evaluation | `evaluation/` + `benchmarks/` | evaluation_runs, benchmark tasks |

## 9. Open items (not decided here)

- Exact tool catalog (Phase 9).
- Sandbox hardening details (Phase 10 — hard security gate).
- UI layout and CSRF posture (Phase 20).
- Benchmark task sets and metric weighting (Phases 21-33).
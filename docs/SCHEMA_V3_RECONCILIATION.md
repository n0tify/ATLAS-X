# Schema version 3 reconciliation

Status: **decision record.** Written before Phases 11-18, to answer one
question: the working tree arrived holding a half-applied schema v3 change whose
columns nothing read. This document maps every added column to a real consumer so
the change could be kept on evidence rather than reverted on reflex.

Status vocabulary: `IMPLEMENTED`, `PARTIAL`, `DOCUMENTED ONLY`, `PLANNED`,
`HISTORICAL/DEPRECATED`.

## 1. The question

`atlas/storage/migrations.py` declared `SCHEMA_VERSION = 3` and
`atlas/storage/db.py` ran `upgrade_to_v3()`, but:

* no production code read any added column;
* `data/atlas.db` was still at version 2;
* one of the nineteen accompanying tests failed.

A migration with no consumer is not groundwork, it is a liability: it moves the
floor under the data without anything standing on it. So the reconciliation had
three possible outcomes and one correct one to choose between them.

## 2. Outcome chosen

**Keep v3, finish it, and give every column a consumer.** Not one column was
removed, because each one turns out to be load-bearing for a phase that the
audit established is genuinely unbuilt. The alternative -- reverting to v2 --
would have meant reintroducing `UNIQUE(task_id)` on `plans`, which is a
constraint Phase 16 recovery cannot satisfy, and would have deferred the same
design problem to a later phase with the same cost.

The full decision and its evidence are in section 3.

## 3. Field to consumer matrix

Every column v3 adds, the requirement it serves, and the code that will read or
write it. "Writer" is the phase that writes it; "test" is the test that will
assert it once that phase lands.

### 3.1 `tasks`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `result_json` | The final verified result has to live somewhere the caller can fetch without replaying the run. | Phase 12 executor on completion; `atlas/executor/results.py` | Executor | E2E "final result linked to the verified execution" |
| `verified_at` | Proves *when* verification passed, which is what makes "verified" a fact about a moment rather than a claim. | Phase 13 verifier gate; Phase 18 result retrieval | Executor, on PASS | E2E "final result blocked without verification PASS" |
| `failure_category` | The task-level answer to "why did this not produce a result", without joining every failure row. | Phase 15 classifier; Phase 16 recovery | Failure classifier | Phase 15 classification tests |

### 3.2 `plans`

`UNIQUE(task_id)` is **removed** and the table is rebuilt. This is the only
non-additive change in v3 and the only reason a rebuild is needed: SQLite cannot
drop a column constraint.

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `source` | Distinguishes a plan the model proposed, one recovery proposed, and one that predates both. Without it a replanned run and a first run are indistinguishable in the audit record. | Phase 14 provenance; Phase 16 recovery | Planner, recovery | Phase 16 recovery-origin tests |
| `status` | Plan-level lifecycle, needed to reject a plan that was never validated before it is executed. | Phase 12 executor admission | Planner, validator, executor | Phase 12 "execution of invalid plan" |
| `model_id` | The system specification requires plan-to-model attribution; H1 compares planning variants, which is meaningless without knowing which model produced the plan. | Phase 11 planner; Phase 14 provenance | Planner | Phase 11 model-output tests |
| `digest` | Which plan content actually ran. Two runs that differ only in a whitespace change must be distinguishable. | Phase 11 validator; Phase 14 provenance | Planner | Phase 11 digest determinism |
| `supersedes_plan_id` | **The reason the rebuild exists.** Bounded recovery must keep the plan that failed beside the one that replaces it. With `UNIQUE(task_id)` there is nowhere to put the replacement. | Phase 16 recovery | Recovery | Phase 16 "recovery keeps the superseded plan" |
| `validation_json` | The validator's findings, so a rejected plan can be explained without re-running the model. | Phase 11 validator; Phase 15 plan errors | Plan validator | Phase 11 adversarial output tests |

### 3.3 `plan_steps`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `tool_id` | The registry is keyed by `tool_id`; `tool_name` is legacy free text. Validating a step against the registry needs the key, not the label. | Phase 11 validator; Phase 12 executor | Planner | Phase 11 "unknown tool" |
| `step_key` | Dependencies are expressed in the plan document, where row ids do not exist yet. A stable caller-chosen key is the only way to reference a step before it is persisted. | Phase 11 validator (dependency resolution) | Planner | Phase 11 "impossible dependency reference" |
| `depends_on_json` | The dependency graph itself, needed for cycle detection and for ordering. | Phase 11 validator | Planner | Phase 11 "dependency cycle" |
| `produces_artifact_kind` | The verifier must know what a step was supposed to produce, or "the artifact is missing" cannot be distinguished from "the artifact is the wrong kind". | Phase 13 verifier; Phase 17 artifacts | Planner | Phase 13 "missing artifact" |
| `provenance_event_id` | Which provenance event created this step. Without it the lineage chain has a gap the reconstruction walk cannot cross. | Phase 14 provenance | Planner, via provenance | E2E "provenance reconstructs the chain" |
| `failure_category` | Per-step failure attribution, so recovery can classify at step granularity. | Phase 15 classifier | Failure classifier | Phase 15 tests |

### 3.4 `executions`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `plan_id` | An execution must say which plan it ran. | Phase 12; Phase 14 | Executor | Phase 12 linkage tests |
| `plan_step_id` | An execution must say which *step* it ran. | Phase 12; Phase 13; Phase 16 | Executor | Phase 13 verification scope |
| `tool_id` | Which tool ran, for the ablation and audit record. | Phase 14 provenance | Executor | Phase 18 E2E |
| `invocation_id` | The correlation id threaded through execution, failure, recovery and provenance. Backed by a **partial unique** index so an execution row that is not part of a dispatch can still hold NULL. | Phase 14 provenance; Phase 15; Phase 16 | Executor | `test_an_invocation_id_can_identify_only_one_execution` (already present) |
| `origin` | Distinguishes `direct`, `plan_step` and `recovery`. This is what lets Phase 16 assert that a recovery re-execution went through the same sandbox and authorization as a first one. | Phase 16 recovery; Phase 12 | Executor | Phase 16 "recovery cannot bypass the sandbox" |
| `error_code` | Stable machine-readable failure code on the execution row itself, not only on the failures table. | Phase 15 classifier | Executor, on failure | Phase 15 tests |
| `created_at` | A queued execution has no `started_at`. Ordering by creation is what makes "duplicate execution" detectable before the first one starts. | Phase 12 duplicate detection | Executor | E2E "duplicate execution protection" |

`created_at` is deliberately **nullable** on a fresh database as well as an
upgraded one. SQLite cannot add a `NOT NULL` column to a table that already holds
rows without inventing values for them, so a `NOT NULL` here would mean a fresh
and an upgraded database disagreed about what is storable. Legacy v2 executions
genuinely have no creation timestamp distinct from `started_at`, so `NULL` is the
honest value.

### 3.5 `artifacts`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `source` | Distinguishes an artifact the sandbox returned from one ATLAS-X wrote. | Phase 17 storage | Artifact store | Phase 17 tests |
| `verified` | Per-artifact verification status, so "verified" is a stored fact and not a join the UI has to reconstruct. | Phase 13 verifier; Phase 17 | Verifier | Phase 13 PASS/FAIL tests |
| `metadata_json` | Size, checksum and kind travel together; splitting them across three columns invites a row where they disagree. | Phase 17 | Artifact store | Phase 17 boundary tests |
| `created_by` | Provenance: which actor produced this artifact. | Phase 14 provenance | Artifact store | Phase 14 tests |

### 3.6 `verifications`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `artifact_id` | **A verification must name the artifact it checked.** Without it the only answer available is "the artifacts of this execution", which cannot distinguish which one passed. This is the column that makes per-artifact verification possible at all. | Phase 13 verifier; Phase 17 | Verifier | Phase 13 "verification of the wrong artifact" |
| `plan_step_id` | Verification is per step, not per run. A step's result is what is verified. | Phase 13; Phase 16 | Verifier | Phase 13 tests |
| `verifier_version` | H2 measures PASS/FAIL rates across ablations. A verifier that changes between runs makes those numbers incomparable. | Phase 13; benchmark phase | Verifier | Phase 13 tests |
| `evidence_json` | The observable evidence the verdict rested on. A verdict with no evidence is not reproducible. | Phase 13; Phase 14 provenance | Verifier | Phase 13 evidence tests |

### 3.7 `failures`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `plan_step_id` | Which step failed. | Phase 16 recovery | Classifier | Phase 15 tests |
| `invocation_id` | Correlates a failure to the dispatch that caused it. | Phase 14 provenance; Phase 15 | Executor | E2E provenance reconstruction |
| `error_code` | Stable code, separate from the human-readable `diagnosis`. | Phase 15; Phase 16 | Classifier | Phase 15 "every code is stable" |
| `retryable` | **The gate that stops recovery looping on things that must not be retried.** A security violation is not retryable, so this column is the mechanism, not a convenience. | Phase 16 recovery admission | Classifier | Phase 16 "never auto-recover a security violation" |

### 3.8 `recovery_attempts`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `failure_id` | Which failure is being recovered. Without it two attempts on different failures are indistinguishable. | Phase 16 | Recovery | Phase 16 tests |
| `limit_no` | **Which bound stopped the attempt.** "Exhausted" is not an audit answer; "exhausted at attempt 2 of 2" is. | Phase 16 reporting | Recovery | Phase 16 "recovery limit enforcement" |
| `detail_json` | Bounded diagnostics for the attempt. | Phase 16 | Recovery | Phase 16 tests |
| `finished_at` | Separates an in-flight attempt from a settled one. | Phase 16 | Recovery | Phase 16 tests |

### 3.9 `provenance_events`

| Field | Why required | Consumer | Writer | Test |
|---|---|---|---|---|
| `plan_id` | Lineage through the plan. | Phase 14 reconstruction | Provenance recorder | E2E provenance reconstruction |
| `plan_step_id` | Lineage through the step. | Phase 14 reconstruction | Provenance recorder | E2E provenance reconstruction |
| `tool_id` | Lineage through the tool. | Phase 14 reconstruction | Provenance recorder | E2E provenance reconstruction |
| `invocation_id` | Lineage through a single dispatch, which is the join key for the whole graph. | Phase 14 reconstruction | Provenance recorder | E2E provenance reconstruction |
| `sequence_no` | Per-task ordering. Reconstruction needs a total order, and timestamps alone do not give one for events written in the same transaction. | Phase 14 reconstruction | Provenance recorder | E2E provenance reconstruction |
| `chain_digest` | See section 4. **Detects, does not prevent.** | Phase 14 verification of the chain | Provenance recorder | Phase 14 chain tests |

## 4. What `chain_digest` does and does not prove

This deserves its own section because the audit's standing complaint about
ATLAS-X's provenance is that it is not tamper-evident, and adding a column named
`chain_digest` is exactly the kind of change that could turn that into a false
claim.

Each event records `SHA-256(previous event's chain_digest || this event's
canonical fields)`. With no external anchor and no key, this proves:

* **an event was deleted or reordered** -- the recomputed chain will not match;
* **a field was edited after the fact** -- same.

It does **not** prove that an event was not rewritten. Anyone able to write to
the database can recompute the whole chain from the edit forward. There is no
secret, no signature, no external timestamp and no append-only enforcement.

So: an **integrity and ordering check against accidental corruption and against
the ordinary bug of a row being updated**, and nothing more. It is not
tamper evidence, it is not tamper *proofing*, and the documentation in
`atlas/provenance/` must say so in those words. `SECURITY.md` already refuses to
claim tamper evidence, and that line must stay true.

## 5. Fields considered and rejected

| Considered | Why rejected |
|---|---|
| A separate `plan_revisions` table | A self-referencing `supersedes_plan_id` already expresses revision chains, and a second table would need the same joins plus its own authorization vocabulary. |
| `executions.sandbox_run_id` | The invocation id already reaches the sandbox, and `invocation_id` is what the provenance graph is keyed on. A second correlation id would be a second thing to keep consistent. |
| `artifacts.storage_path` absolute | An absolute host path in the database is a host path the model could one day influence, and a Windows absolute path is meaningless inside the Linux guest. Phase 17 stores a project-relative path and resolves it itself. |
| `failures.recovery_attempt_id` | The recovery attempt already points at the failure via `failure_id`. The reverse edge is a join, and storing it would let the two disagree. |
| A `verification_result` column on `tasks` | `verified_at` plus the verifications rows answer the question without a second source of truth that can drift from them. |

## 6. Defects found and fixed during reconciliation

The half-applied change was not merely incomplete; running it against the full
suite surfaced four defects that the earlier targeted run had not reached.

| Defect | Severity | Fix |
|---|---|---|
| `test_an_invocation_id_can_identify_only_one_execution` inserted a task for nonexistent user 1, so it failed on the foreign key before reaching its actual subject | test defect | Build a real owner. **The foreign key was not weakened.** |
| The same test then asserted a row count after inserting a duplicate `invocation_id`, but the duplicate is correctly *refused*. The test could never have passed as written. | test defect | Assert the refusal, and assert that two NULL invocations coexist, which is what the partial index is for. |
| `executions.created_at` was `TEXT NOT NULL` in the fresh schema and `TEXT` when added by `ALTER TABLE`, so a fresh and an upgraded database disagreed about what was storable. | **schema defect** | Nullable on both paths, with the reason recorded in the schema comment. |
| `upgrade_to_v3` reported "the database was left at its original shape" on failure, but only rolled back when the *caller* did. `Database.initialize` happened to; a direct call did not. | **atomicity defect** | `upgrade_to_v3` now opens and commits its own transaction when it is not already inside one. |

The last two are the reason the reconciliation was worth doing rather than
skipping: they were only reachable by running the whole suite against a database
produced by the migration, which is what the fresh-versus-upgraded comparison now
does permanently.

## 7. Test coverage added

| Test | Property |
|---|---|
| `test_a_v3_lineage_column_refuses_a_dangling_reference` (8 cases) | Every added lineage column is a real, enforced foreign key, and a refused insert leaves nothing behind. |
| `test_deleting_a_plan_leaves_the_execution_that_used_it` | `ON DELETE SET NULL`, so tidying a plan cannot destroy evidence of a run that happened. |
| `test_the_fresh_and_the_upgraded_schema_are_the_same_shape` | A fresh database and an upgraded one are semantically identical: same columns with types, nullability, defaults and primary keys, same foreign keys, same indexes. |
| `test_an_upgrade_that_cannot_finish_leaves_the_database_untouched` | A refused upgrade rolls back whole rather than leaving half the schema applied. |
| `test_the_upgrade_leaves_an_empty_directory_for_init_db_to_create` | Existing. |

## 8. What was deliberately not done

* **The live `data/atlas.db` was not migrated.** It stays at version 2, verified
  by SHA-256 against a copy at
  `../ATLAS-X.backup-2026-10-02-pre-v3-reconcile/atlas-v2-LIVE-ORIGINAL.db`,
  with its DDL recorded in `atlas-v2-LIVE-SCHEMA.sql` beside it. Migration is a
  deliberate operator action, not something a test run should do.
* **No foreign key was weakened, no test was deleted, no bound was raised.**
* **`SANDBOX_DESIGN.md` and `ARCHITECTURE_RECONCILIATION.md` were not touched.**
  They remain historical records.
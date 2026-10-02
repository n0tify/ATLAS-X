# ATLAS-X Architecture Decisions

This document records decisions that are already explicitly established by the
project requirements. No additional architecture decisions are made here; they
are deferred to the relevant phases.

Established decisions:

- **Local-first** — everything runs on the operator's own machine.
- **Free tooling** — zero monetary cost for the entire stack.
- **One local model** — a single primary local model for experiments (others
  may exist locally for incidental tasks only if needed).
- **Laptop-safe execution** — must run within ordinary laptop resources
  (RAM, CPU, disk, time).
- **Bounded resources** — all executions are limited by explicit, conservative
  configuration and never by unlimited defaults.
- **SQLite-first persistence** — SQLite is the default relational store.
- **JSONL for append-oriented event/evaluation data** where appropriate — e.g.
  provenance events, evaluation runs.
- **NetworkX only where graph representation materially helps** — not as a
  blanket dependency.
- **SQLite FTS where lightweight local search is useful** — not a general
  search engine.
- **Streamlit-first UI** — Streamlit before any heavier frontend framework.
- **Authentication and authorization are security priorities** — treated as
  first-class requirements, not afterthoughts.
- **Sandboxed tool execution** — tool calls run under an explicit sandbox
  boundary; no privileged host execution.
- **Deterministic verification** — a verification layer independent from the
  model checks outputs deterministically where possible.
- **Bounded recovery** — failures may trigger classification/diagnosis/replan,
  but only within strict, configured limits.
- **Provenance** — every meaningful execution event is recorded for auditability
  and reproducibility.
- **Reproducible experiments** — a benchmark must yield repeatable results from
  the repository alone.
- **No fabricated results** — all claims in outputs must be traceable to real,
  measured executions.
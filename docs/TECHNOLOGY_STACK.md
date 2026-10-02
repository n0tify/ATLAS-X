# ATLAS-X Technology Stack

Status: **decision document (Phase 1 gate).** Nothing here was installed by this
phase; the document justifies and freezes the minimum viable stack.

Scope aligns with the established constraints: zero monetary cost, local-first,
open-source where practical, laptop-safe, minimal dependencies, reproducible,
secure, maintainable, easy to install, academically credible.

Machine context (from `docs/environment-reconnaissance.md`): Windows 11,
Python 3.11.0 (default `python`), 15.7 GB RAM, i5-1335U (10c/12t), 197 GB free
disk, **no Docker**, Ollama 0.34.4 with three local models already on disk.

## Evaluation criteria

1. Zero monetary cost
2. Local execution
3. Open-source software where practical
4. Lightweight on a normal laptop
5. Minimal dependencies
6. Reproducibility
7. Security
8. Long-term maintainability
9. Ease of installation
10. Academic credibility

## Selected stack

### Language

| Item | Selection | License | Rationale |
|---|---|---|---|
| Language | Python | PSF License | Academic standard for AI/ML research; identical code runs on the laptop and on university machines; largest research library ecosystem. |

No alternative considered seriously: Python is the default for the stated
research domain.

### Persistence and data

| Item | Selection | License | Why chosen | Why not a simpler/fancier alternative | Resource impact | Security notes |
|---|---|---|---|---|---|---|
| Relational store | SQLite (stdlib `sqlite3`) | Public domain | Zero install; single-file; transactional (ACID); foreign keys; concurrency sufficient for one laptop | PostgreSQL/MySQL require a server process and an installer; not needed for local single-node workloads | ~0 daemon; a handful of MB per DB file | `PRAGMA foreign_keys=ON`; WAL; parameterized SQL only; DB file is host-owned (OS permissions are the boundary) |
| Append-only event/evaluation records | JSONL | n/a (format) | Natural append-only log for provenance and evaluation rows; trivially diffable and reviewable | Parquet/SQLite overload for event streams; JSONL is the canonical research-log format | Linear file growth, bounded by `max_log_bytes` | Append-only by convention; no inline secrets; redaction layer applies to any logging path |
| Graph representation | NetworkX (only where a graph genuinely helps) | BSD-3-Clause | Provenance/dependency graphs for experiments where topology matters | Building custom graph code, or bloating the stack with a graph DB | In-memory graphs only; dataset sizes are small by design | Pure-Python library; no new attack surface for typical usage |
| Local search | SQLite FTS (via FTS5, stdlib) | Public domain | Lightweight full-text search over task/artifact summaries without a service | Elasticsearch/Solr/Meilisearch are heavyweight, externally hosted or installer-heavy | Index inside the same SQLite file | Same parameterized access discipline as the rest of SQLite |

### Application layer

| Item | Selection | License | Why chosen | Why not simpler | Resource impact | Security notes |
|---|---|---|---|---|---|---|
| Backend/service core | FastAPI (deferred; only if an HTTP API is genuinely needed) | MIT | Real-time async web framework if a remote client/API surface is later justified | Streamlit can serve the local researcher directly; an HTTP API adds attack surface and packaging without a demonstrated need | Middleweight when added; currently not installed | If added later: auth via existing session layer; input validation via Pydantic at the boundary |
| Validation | Pydantic | MIT | Field-level validation and settings validation; already in use for config | Hand-rolled validation is error-prone and unmaintainable | Small; schema-driven | Central entry-point validation; fail-closed configuration |
| UI | Streamlit (first) | Apache-2.0 | Single-file local UI; auth + session state supported; fastest path from experiment to interactive view | React/Next.js add a build toolchain, a dev server, and npm risk with zero research value for a local tool | Moderate; one Python process | Session-based auth must be wired to the ATLAS-X session layer; CSRF considerations deferred to the UI phase |

Chosen UI remains Streamlit-first per the established decisions; React was
deliberately dropped for the core (the folder shape no longer includes an
`apps/web` frontend).

### AI runtime and models

| Item | Selection | License | Why chosen | Why not simpler | Resource impact | Security notes |
|---|---|---|---|---|---|---|
| Runtime | Ollama | MIT (software) | Installed already (0.34.4); local; models already present; trivial CLI/API | llama.cpp bindings are more fiddly; a hosted API violates the free/local constraints | Daemon ~idle; a few hundred MB when active | Local only; no cloud call; model I/O is untrusted input (prompt injection is a modeled threat) |
| Primary model | `llama3.1:8b` (default; configurable) | Meta Llama 3.1 Community License (weights, not OSI) | Already local (4.9 GB); fits 15.7 GB RAM; strong general multi-step reasoning for the planning/verification studies | A 70B model would not fit laptop constraints; a coding-only model (qwen2.5-coder:1.5b) is a candidate for tool-heavy variants via configuration | ~5 GB on disk; ~6-8 GB RAM at inference; CPU-only on this machine is slower but viable for small datasets | Weight license is not OSI open source; see model licensing section below |

Model selection is **configuration**, never a download: ATLAS-X will refuse to
fetch models automatically. `qwen2.5-coder:1.5b-base` (Apache-2.0 weights) and
`nomic-embed-text` (Apache-2.0 weights) are already-present alternatives for
specific ablations; `llama3.1:8b` is the one primary default.

### Quality, testing, science

| Item | Selection | License | Why chosen | Resource impact | Security notes |
|---|---|---|---|---|---|
| Testing | pytest | MIT | Standard; parametrized; zero-config with `pyproject.toml` | Small | Tests must never hit the network |
| Linter | Ruff | MIT | Fast, one binary, single config | Small | — |
| Type checking | mypy | MIT | Where useful; catches auth/ownership typos | Small | — |
| Data science | NumPy / pandas / SciPy / scikit-learn / matplotlib | BSD-3-Clause (all five) | Benchmark aggregation, statistics, plots, reproducibility of results | Bounded by small datasets | — |
| E2E/UI verification | Streamlit app testing via pytest (when UI lands) | — | No Playwright/Selenium needed for a local tool | Small | — |

### Execution and sandboxing

| Item | Selection | License | Why chosen | Why not simpler | Resource impact | Security notes |
|---|---|---|---|---|---|---|
| Sandbox | Subprocess with strict process/filesystem/resource limits (default) | n/a (stdlib) | Docker is **not installed** on this machine and WSL has no distributions; a subprocess sandbox with `resource`-style limits, a project-scoped working directory, timeouts and size caps is install-free and laptop-safe today | Docker would be stronger isolation but adds a large install + license change to the host; it is documented as an optional later enhancement (see `docker/README.md`) | One short-lived child process per execution; CPU/memory bounds enforced | Sandboxing reduces risk; it does not make generated code safe. Threat model (Phase 3) treats escape attempts as in-scope adversarial tests |

## Model licensing: software vs. weights

Three things are frequently conflated and ATLAS-X keeps them separate:

1. **Software license** — the runtime and library licenses above (e.g., Ollama
   is MIT).
2. **Model-weight license** — the terms on the weights themselves. This governs
   redistribution, modification, and commercial use of the trained parameters.
3. **Availability** — being freely downloadable is not the same as open source.

Current local models and their weight terms:

| Model | Availability | Weight license | Research use | Notes |
|---|---|---|---|---|
| `llama3.1:8b` | Free download | Meta Llama 3.1 Community License (custom, **not OSI-approved open source**) | Permitted, incl. research | Monthly-active-user threshold >700M requires Meta approval; academic use is under the permitted umbrella |
| `qwen2.5-coder:1.5b-base` | Free download | Apache-2.0 (weights) | Permitted | Apache-licensed weights |
| `nomic-embed-text` | Free download | Apache-2.0 (weights) | Permitted | Apache-licensed weights |

Therefore the project README/SECURITY text must say precisely:

> "ATLAS-X uses locally hosted models whose licenses permit the intended
> research and educational use."

and must **not** claim "everything is open source."

## Dependencies We Explicitly Avoid

| Avoided | Why |
|---|---|
| Kubernetes | A container orchestrator is catastrophic overkill for one laptop |
| Kafka | Server-side event pipeline; JSONL/sqlite serve local event needs |
| Redis | Server dependency; session storage lives in SQLite |
| Elasticsearch | Heavyweight search server; SQLite FTS suffices |
| Cloud databases (e.g. AWS RDS, Supabase/BaaS) | Violates local-first and zero-cost |
| Paid APIs / hosted LLM APIs (OpenAI, Anthropic, Google, etc.) | Violates free/local; also pushes wallet into the build |
| Vector databases (Pinecone, Weaviate, Qdrant server) | No retrieval pipeline is a research requirement at this point |
| Multi-agent frameworks | Unless a later experiment demonstrates a concrete research need |
| React/Next.js frontend | Streamlit-first; a frontend toolchain adds risk without research value |
| Jupyter-as-application-shell | Notebooks are fine for analysis, but the product runs as a Python package |
| Docker-required runtime | Docker is not installed; sandbox must not assume it |

## Decision record

Locked now: every row in the two tables above, the model-licensing wording,
and the subprocess-first sandbox posture (Docker as optional enhancement).

Still open (later gates): exact primary model default is config-dependent but
defaults to `llama3.1:8b`; FastAPI only if a real API requirement appears;
Streamlit layout details; final LICENSE selection for the repository.
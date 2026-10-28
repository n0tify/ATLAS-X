# Development and Research Guide

## Prerequisites

- Windows 10/11 (development target) with PowerShell.
- Python 3.11 (`.venv`).
- Node.js 20 (for frontend).
- Ollama (optional, for planning) with model `llama3.1:8b`.
- WSL2 with `Ubuntu-24.04` (optional, for sandboxed tool execution).

## Setup (Windows)

```powershell
cd "C:\Users\<you>\Desktop\ATLAS-X"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Frontend:

```powershell
cd frontend
npm install
```

## Environment configuration

Copy `.env.example` to `.env` and adjust. Key variables (backend reads `ATLAS_`
prefix via `Settings.from_environ`):

- `ATLAS_ENVIRONMENT` (development/production)
- `ATLAS_DATABASE_PATH` (default `data/atlas.db`)
- `ATLAS_APPLICATION_SECRET_KEY` (required in production)
- `ATLAS_MODEL_BASE_URL` (default `http://127.0.0.1:11434`)
- `ATLAS_MODEL_NAME` (default `llama3.1:8b`)
- `ATLAS_AUTH_SESSION_TTL_MINUTES`, `ATLAS_AUTH_MAX_LOGIN_ATTEMPTS`, etc.
- `CORS_ALLOWED_ORIGINS` (comma-separated; defaults to localhost Vite ports)

Frontend: copy `frontend/.env.example` to `frontend/.env` (sets `VITE_API_URL`).

Never commit `.env` or real secrets. Use placeholders.

## Start backend

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Or smoke check:

```powershell
atlas-x
```

Health: `GET http://127.0.0.1:8000/health`
Readiness: `GET http://127.0.0.1:8000/ready`

## Start frontend

```powershell
cd frontend
npm run dev
```

Opens `http://localhost:5173`; proxies `/api` to backend.

## Ollama setup (optional, for planning)

```powershell
ollama serve
ollama pull llama3.1:8b
```

Verify: `curl http://127.0.0.1:11434/api/tags`

## WSL2 sandbox setup (optional, for tools)

```powershell
python -m atlas.sandbox.provision
```

Verify health via `SandboxSupervisor.health()`.

## Run tests

Backend (all, documented from source; last collected 740, 737 excluding live planner):

```powershell
python -m pytest
```

Live model tests (require Ollama running):

```powershell
python -m pytest tests/test_planner_live.py
```

Frontend browser tests:

```powershell
cd frontend
npx playwright test
```

## Quality checks

```powershell
ruff check .
mypy atlas
cd frontend
npm run lint
npm run build
```

## Reproducing research experiments

Benchmark/experiment scaffolding exists under `benchmarks/`, `experiments/`,
`datasets/`. See `docs/ATLAS_BENCH.md`, `docs/EXPERIMENT_PROTOCOL.md`,
`docs/METRICS.md`, `docs/REPRODUCIBILITY.md`. No benchmark results are claimed
by this audit; run definitions locally and record under `reports/` or
`experiments/output/`.

## Troubleshooting

- `SandboxUnavailable`: ensure WSL2 distribution provisioned; run health check.
- `ModelUnavailable`/timeout: ensure Ollama running and model pulled; plan
  prompts can take ~94s on CPU.
- `database is locked`: SQLite contention; retry; single-writer design.
- Readiness 503: check DB path and permissions.
- CORS errors: set `CORS_ALLOWED_ORIGINS`.

## Notes

Commands documented from source and prior reports; not all re-executed during
this audit. Label historical results as historical.

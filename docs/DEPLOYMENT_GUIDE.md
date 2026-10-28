# ATLAS-X Deployment Guide

**Version:** 0.1.0
**Last Updated:** 2026-10-18

---

## Overview

ATLAS-X consists of:
- **Frontend:** React + TypeScript + Vite (served as static files)
- **Backend:** FastAPI + Python (uvicorn ASGI server)
- **Database:** SQLite (local file, `data/atlas.db`)
- **Optional:** Ollama for local LLM planning, WSL2/bubblewrap for sandbox

## Deployment Compatibility (verified constraints)

ATLAS-X requires:
- Python 3.11, Node 20 (build-time).
- SQLite file storage with persistence.
- Local Ollama on loopback for planning (optional; without it, planning is unavailable).
- WSL2 (Windows) for the tool sandbox (no in-process fallback).

| Target | Feasible? | Notes |
|---|---|---|
| Local demo (Windows + WSL2 + Ollama) | Yes | Full capability. |
| Single-host self-managed (Windows server with WSL2 + Ollama) | Yes | Full capability; owner manages backups/updates. |
| Conventional managed cloud (Linux containers, no WSL2/Ollama) | Reduced capability only | Planner and sandbox must be explicitly disabled/unavailable; do not claim full agent execution. |

Containerization is not implemented and is not recommended for the full sandbox path because WSL2 cannot be provided inside a standard Linux container. A reduced-capability container (UI + API + SQLite, planner/sandbox disabled) is possible but is not the complete research system.

## Recommended deployment mode

Prefer **single-host self-managed deployment on a Windows machine with WSL2 and Ollama**. This is the only target that genuinely supports every capability ATLAS-X claims. Do not deploy to a conventional cloud host while advertising sandboxed tool execution or local planning.

---

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- SQLite 3 (included with Python)
- Optional: Ollama (for AI planning), WSL2 (for sandbox on Windows)

### Quick Start

```bash
# 1. Clone and enter repository
cd ATLAS-X

# 2. Install Python dependencies
pip install -e .

# 3. Install frontend dependencies
cd frontend
npm install
cd ..

# 4. Start backend (Terminal 1)
python -m uvicorn api:app --host 127.0.0.1 --port 8000

# 5. Start frontend (Terminal 2)
cd frontend
npm run dev
```

### Verified URLs
- Frontend: http://localhost:5173
- Backend API: http://127.0.0.1:8000
- API Docs (Swagger): http://127.0.0.1:8000/docs
- Health Check: http://127.0.0.1:8000/health
- Readiness Check: http://127.0.0.1:8000/ready

### Environment Variables (actual names)

Create `.env` in project root (copy from `.env.example`). Backend reads `ATLAS_`-prefixed variables via `Settings.from_environ`; CORS is read directly.

```bash
# Required in production
ATLAS_ENVIRONMENT=production
ATLAS_APPLICATION_SECRET_KEY=<long-random-value>

# Database
ATLAS_DATABASE_PATH=data/atlas.db

# Authentication
ATLAS_AUTH_SESSION_TTL_MINUTES=60
ATLAS_AUTH_MAX_LOGIN_ATTEMPTS=5
ATLAS_AUTH_LOCKOUT_MINUTES=15
ATLAS_AUTH_FAILURE_DELAY_SECONDS=0.1

# Model (local Ollama, loopback only)
ATLAS_MODEL_BASE_URL=http://127.0.0.1:11434
ATLAS_MODEL_NAME=llama3.1:8b

# CORS (production: explicit origins, never '*')
CORS_ALLOWED_ORIGINS=https://your-domain.example
```

Frontend environment (copy `frontend/.env.example` to `frontend/.env`):

```bash
# Leave empty in production when served by the backend; set for split hosting.
VITE_API_BASE_URL=
```

---

## Production Build

### Frontend

```bash
cd frontend
npm run build
# Output: frontend/dist/
```

The build outputs optimized static assets to `frontend/dist/`. The FastAPI backend serves these files when `frontend/dist` exists.

### Backend

No separate build step. Install production dependencies:

```bash
pip install -e . --no-dev
# Or use pip install with requirements.txt
```

---

## Docker Deployment

### Dockerfile (Frontend + Backend)

```dockerfile
# Build stage
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Python stage
FROM python:3.11-slim
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy application code
COPY api/ ./api/
COPY atlas/ ./atlas/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# Create data directory for SQLite
RUN mkdir -p /app/data

# Environment
ENV DATABASE_PATH=/app/data/atlas.db
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

# Run
CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Build and Run

```bash
# Build image
docker build -t atlas-x .

# Run container
docker run -d \
  --name atlas-x \
  -p 8000:8000 \
  -v atlas-x-data:/app/data \
  -e DATABASE_PATH=/app/data/atlas.db \
  atlas-x
```

### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - atlas-x-data:/app/data
    environment:
      - DATABASE_PATH=/app/data/atlas.db
      - CORS_ALLOW_ORIGINS=https://your-domain.com
      - AUTH_SESSION_TTL_MINUTES=60
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s

volumes:
  atlas-x-data:
```

---

## Railway Deployment

### Prerequisites
- Railway account
- GitHub repository connected

### Configuration Files

**railway.toml**
```toml
[build]
builder = "dockerfile"
dockerfilePath = "Dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3

[[services]]
name = "api"
```

**Dockerfile** (use the one above)

### Environment Variables (Railway Dashboard)

Set in Railway project settings:

```
DATABASE_PATH=/app/data/atlas.db
CORS_ALLOW_ORIGINS=https://your-app.railway.app
AUTH_SESSION_TTL_MINUTES=60
AUTH_MAX_LOGIN_ATTEMPTS=5
AUTH_LOCKOUT_MINUTES=15
AUTH_FAILURE_DELAY_SECONDS=1
PYTHONUNBUFFERED=1
```

### Persistent Volume

1. In Railway dashboard, go to **Volumes**
2. Create volume: `atlas-x-data` mounted at `/app/data`
3. Attach to `api` service

### Deploy

1. Push to GitHub
2. Railway auto-deploys on push
3. Check logs for startup verification
4. Access via provided Railway URL

### Health Checks

Railway uses `/health` endpoint. Ensure it returns 200 OK:
```json
{"status": "healthy"}
```

---

## SQLite Persistence

### Local Development
- Database file: `data/atlas.db`
- Automatically created on first run
- Migrations applied on startup

### Production
- Use persistent volume (Docker volume, Railway volume, etc.)
- Mount at `/app/data` (container) or equivalent
- Backup strategy: Copy `atlas.db` file regularly

### Migrations

Migrations run automatically on startup via `Database.initialize()`:

```python
# In api/__init__.py or startup script
from atlas.storage.db import Database
from atlas.config.settings import Settings

db = Database(Settings().database_path)
db.initialize()  # Runs migrations
```

---

## CORS Configuration

### Development
```python
# api/__init__.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Production
```python
# Restrict to actual frontend origin
allow_origins=["https://your-domain.com", "https://www.your-domain.com"]
```

---

## Authentication in Production

### Current: Bearer Token + localStorage
- Simple, works for SPA
- Token stored in localStorage (XSS risk)
- Suitable for local development

### Recommended for Production
1. **HttpOnly Cookies** - Move token to HttpOnly, Secure, SameSite=Strict cookie
2. **Refresh Tokens** - Short-lived access tokens + long-lived refresh tokens
3. **CSRF Protection** - Double-submit cookie or SameSite=Strict

### Migration Path
Update `api/routers/auth.py`:
- Set `secure=True` for cookies in production
- Add refresh token endpoint
- Update frontend `api.ts` to use cookie-based auth

---

## Monitoring & Logging

### Structured Logging
Backend uses Python logging with JSON format option:

```python
# In production, configure JSON logging
import logging
import json_logging

json_logging.init_non_web(framework_name="fastapi")
```

### Health Endpoints
- `/health` - Liveness (process alive)
- `/ready` - Readiness (dependencies OK)

### Metrics (Future)
- Request latency, error rate
- Active sessions, tasks
- Sandbox execution metrics

---

## Backup & Recovery

### Database Backup
```bash
# Simple file copy (SQLite is a single file)
cp data/atlas.db backups/atlas-$(date +%Y%m%d).db
```

### Automated Backup (Cron)
```bash
# Daily at 2 AM
0 2 * * * cp /app/data/atlas.db /app/backups/atlas-$(date +\%Y\%m\%d).db
```

### Recovery
1. Stop application
2. Replace `atlas.db` with backup
3. Restart application
4. Verify data integrity

---

## Troubleshooting

### Backend Won't Start
- Check port 8000 not in use: `netstat -ano | findstr :8000`
- Verify Python dependencies: `pip install -e .`
- Check database path permissions

### Frontend Build Fails
- Clear node_modules: `rm -rf frontend/node_modules && cd frontend && npm install`
- Check Node version: `node --version` (requires 18+)

### CORS Errors
- Verify `CORS_ALLOW_ORIGINS` includes frontend origin
- Check browser console for specific error

### Authentication Issues
- Clear localStorage: `localStorage.clear()` in browser console
- Check token expiry: `AUTH_SESSION_TTL_MINUTES`
- Verify backend logs for auth errors

### SQLite Locked
- Ensure single writer (no concurrent processes)
- Check for stale locks: `rm -f data/atlas.db-wal data/atlas.db-shm`

---

## Security Checklist (Pre-Production)

- [ ] Restrict CORS to production domain
- [ ] Enable HTTPS (TLS termination at proxy/load balancer)
- [ ] Move auth token to HttpOnly Secure cookie
- [ ] Implement refresh token rotation
- [ ] Add rate limiting (slowapi or nginx)
- [ ] Attach SecretsRedactionFilter to logging
- [ ] Set strong `application_secret_key`
- [ ] Enable CSRF protection
- [ ] Audit password policies
- [ ] Review sandbox configuration for production
- [ ] Disable debug endpoints in production
- [ ] Set up log aggregation
- [ ] Configure backup retention policy

---

## Rollback Procedure

1. **Docker:** `docker tag atlas-x:previous atlas-x:latest && docker restart atlas-x`
2. **Railway:** Use Railway dashboard to rollback to previous deployment
3. **Database:** Restore `atlas.db` from backup
4. **Verify:** Check `/health` and `/ready` endpoints
5. **Smoke test:** Login, create task, view dashboard
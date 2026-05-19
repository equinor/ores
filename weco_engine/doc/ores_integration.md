# ORES Integration Guide

## Overview

WeCo is integrated into ORES (the Equinor OSDU web frontend) as an **in-process
Python package**. The WeCo C++ correlation engine runs inside the ORES container
— no separate microservice or Radix app is needed.

```
┌─────────────────────────────────────────────────────────┐
│  ORES Radix App ("ores")                                │
│                                                         │
│  app/main.py         ← FastAPI web app                  │
│  app/weco_router.py  ← calls WeCo directly (in-process) │
│  weco package        ← pip installed, includes C++ .so  │
│                                                         │
│  Browser → /weco/    ← weco.html (Wells/Params/Results) │
│  Browser → /weco/run ← calls weco.engine C++ directly   │
└─────────────────────────────────────────────────────────┘
```

## Repository Structure

Two separate git repositories, linked by a submodule:

| Repo | Purpose | Radix trigger |
|------|---------|---------------|
| `ores` (github.com/equinor/ores) | Web frontend + all routers | Push to `main` → dev, `release` → prod |
| `weco` (github.com/equinor/weco) | Correlation engine + API + desktop GUI | No Radix trigger (standalone) |

The ORES repo contains `weco_engine/` as a **git submodule** pointing to the
WeCo repo. This is only used at Docker build time.

## Key Files in ORES

| File | Role |
|------|------|
| `app/weco_router.py` | FastAPI router — serves `/weco/` page + all API endpoints |
| `app/templates/weco.html` | Jinja2 template — 3-tab UI (Wells → Parameters → Results) |
| `app/static/weco.js` | Frontend JS — calls `/weco/*` endpoints |
| `app/templates/base.html` | Nav bar — includes "Correlation" link |
| `Dockerfile` | Multi-stage build — compiles WeCo C++ in builder stage |
| `weco_engine/` | Git submodule → WeCo source (for Docker build) |

## How It Works

1. **No HTTP between ORES and WeCo** — the router imports `weco.rddms`,
   `weco.api`, `weco.ext` directly. The C++ engine (`.so`) is loaded in-process.

2. **Lazy imports** — WeCo modules are imported inside endpoint functions, not
   at module level. If WeCo is missing, only WeCo endpoints fail (rest of ORES
   is unaffected).

3. **Single-worker process** — ORES runs with `--workers 1` (SQLite token store
   constraint). WeCo's global C++ state is safe within one process, with
   `reset_options()` called before every run.

4. **Session state** — imported wells are cached in `_cached_well_list` (module
   global). This works for single-user/single-worker. Multi-user would need
   session-keyed storage.

## Data Flow

```
User → /weco/ (HTML page)
     → /weco/import   (RDDMS → WeCo well list, cached in memory)
     → /weco/suggest-defaults (auto-tune params from well data)
     → /weco/run      (C++ engine runs correlation)
     → /weco/export   (results → RDDMS markers)
```

All data comes from RDDMS (OSDU). No file upload/browse in the web UI.
The ORES session token is passed through to RDDMS calls.

## Development Workflow

### Local Setup

```bash
# 1. Clone both repos
cd ~
git clone ... ores
git clone ... weco

# 2. Use a shared venv (or separate, your choice)
cd ~/weco
python -m venv .venv && source .venv/bin/activate
pip install -e .                    # editable WeCo (compiles C++)
pip install fastapi uvicorn jinja2  # ORES deps

# 3. Install WeCo editable in same venv
cd ~/ores
pip install -e ~/weco

# 4. Run ORES locally
cd ~/ores
uvicorn app.main:app --port 9000 --reload

# 5. Open http://localhost:9000/weco/
```

### Making Changes to WeCo

```bash
cd ~/weco
# edit weco/*.py or src/*.cpp
# if C++ changed: pip install -e . (recompiles)
# if Python only: changes are live (editable install)

# Test directly:
pytest pytest/

# ORES picks up changes immediately (editable install)
```

### Making Changes to ORES Web UI

```bash
cd ~/ores
git checkout feature/weco-integration
# edit app/templates/weco.html, app/static/weco.js, app/weco_router.py
# uvicorn --reload picks up changes live
```

## Deployment to Radix

### Architecture

```
GitHub push → Radix detects → Docker build → Deploy container
```

Radix builds from a single repo (`ores`) using the Dockerfile.
The WeCo submodule is cloned automatically (`--recurse-submodules`).

### Build Process (Dockerfile)

```dockerfile
# Stage 1: Builder — compiles WeCo C++ engine
FROM python:3.12-slim AS builder
RUN apt-get install -y build-essential g++ cmake ninja-build
COPY weco_engine/ /build/weco_engine/
RUN pip install scikit-build-core pybind11
RUN pip install /build/weco_engine/

# Stage 2: Runtime — slim image
FROM python:3.12-slim
RUN apt-get install -y libgomp1  # OpenMP runtime for C++ engine
COPY --from=builder /opt/venv /opt/venv
COPY app/ ./app/
```

### Updating WeCo Version on Radix

```bash
cd ~/ores

# Pull latest WeCo commit into the submodule
git submodule update --remote weco_engine

# Commit the new pointer
git add weco_engine
git commit -m "chore: bump weco engine to $(cd weco_engine && git rev-parse --short HEAD)"
git push origin main    # → triggers Radix dev build
```

**Important:** Pushing to `~/weco` alone does NOT trigger an ORES rebuild.
You must explicitly bump the submodule pointer in ORES.

### Environment Triggers

| Branch pushed | Radix environment | URL |
|---------------|-------------------|-----|
| `main` | `dev` | ores-dev.radix.equinor.com |
| `release` | `prod` | ores.radix.equinor.com |

### Promoting to Production

```bash
cd ~/ores
git checkout release
git merge main
git push origin release   # → triggers Radix prod build
```

## Radix Configuration

In `radixconfig.yaml`, no extra config needed for WeCo — it's compiled into the
same container. Relevant env vars:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DEFAULT_DATASPACE` | Pre-filled dataspace in UI | `maap/drogon` |

## Dependencies

### Required in Docker

- `libgomp1` — OpenMP runtime (C++ engine parallelism)
- `scikit-build-core`, `pybind11` — build-time only (builder stage)
- `numpy`, `scipy`, `matplotlib` — WeCo Python deps
- `resqml` package — for RDDMS import/export (see below)

### The resqml Dependency

`weco.rddms` imports from the `resqml` package (`~/gocad/lib/scripts/resqml/`).
This is needed for RDDMS well import and result export.

**Current status:** Not pip-installable (no pyproject.toml). Needs to be:
1. Made into a proper pip package, OR
2. Added as a second submodule in ORES, OR
3. Vendored into the WeCo repo

**Graceful degradation:** If `resqml` is not installed, RDDMS endpoints return
HTTP 501 ("RESQML support not available"). The demo endpoint and direct engine
calls still work.

## Testing Before Merge

### Local Smoke Tests

```bash
cd ~/ores
uvicorn app.main:app --port 9000 &

# 1. Health check (engine loads?)
curl http://localhost:9000/weco/health
# → {"connected":true,"version":"0.9.31","engine":true}

# 2. Demo run (no RDDMS needed)
curl -X POST "http://localhost:9000/weco/run/demo?demo_id=ds1.1&n_best=3"
# → {"status":"ok","n_results":3,"results":[...]}

# 3. Page renders
curl -s http://localhost:9000/weco/ | grep "Well Correlation"

# 4. Existing pages still work
curl -s http://localhost:9000/login-page | grep -i "login"
curl -s http://localhost:9000/strat | grep "Stratigraphy"
```

### Docker Build Test

```bash
cd ~/ores
docker build -t ores-weco-test .
docker run --rm -p 9000:8000 ores-weco-test
curl http://localhost:9000/weco/health
```

### Risk Checklist

- [ ] ORES starts without errors (no top-level WeCo import failures)
- [ ] `/login-page` responds (Radix health probe)
- [ ] `/strat` page works (existing functionality)
- [ ] `/weco/health` returns `connected: true`
- [ ] `/weco/run/demo` returns correlation results
- [ ] Docker image builds successfully
- [ ] C++ engine doesn't segfault on demo data

## Known Limitations

1. **Single-user session** — `_cached_well_list` is a process global. If two
   users import different well sets simultaneously, they overwrite each other.
   Fix: key by session ID.

2. **Blocking correlation** — the C++ engine blocks the event loop. Other
   requests wait. Fix: run in `asyncio.to_thread()` or a process pool.

3. **No file-based routes** — the web UI only supports RDDMS data. Local file
   correlation requires the desktop GUI or CLI.

4. **resqml not in Docker yet** — RDDMS endpoints return 501 until resolved.

## Future Improvements

- Session-keyed well storage (Redis or per-user temp dirs)
- `asyncio.to_thread()` wrapper for engine calls (non-blocking)
- Progress reporting via SSE/WebSocket for long correlations
- Correlation visualization (SVG/Canvas rendering of marker ties)
- Multi-worker support (if SQLite constraint is lifted)

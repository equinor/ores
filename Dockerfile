# ── Build stage: install Python deps into a virtual-env ──────────────
FROM python:3.12-slim AS builder

# Build tools needed for WeCo C++ extension
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential g++ cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Build WeCo C++ engine from subtree
COPY weco_engine/ /build/weco_engine/
RUN /opt/venv/bin/pip install --no-cache-dir scikit-build-core pybind11 \
    && /opt/venv/bin/pip install --no-cache-dir /build/weco_engine/

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.12-slim

# Security: non-root user (numeric UID required by Radix runAsNonRoot policy)
RUN groupadd -g 1001 ores && useradd -u 1001 -g 1001 -r -d /app -s /sbin/nologin ores

# Runtime: libgomp needed by WeCo C++ engine (OpenMP)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual-env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Optional: set GRAPHQL_PG_CONN_STRING at runtime to enable direct PostgreSQL
# access for the GraphQL deep-search module (bypasses REST API).
# Example: -e GRAPHQL_PG_CONN_STRING="host=pg port=5432 dbname=openetp user=app password=secret"

# Copy application code
COPY app/          ./app/
COPY demo/         ./demo/
COPY md/           ./md/

# Copy WeCo demo datasets (for /demos API endpoint)
COPY weco_engine/demo/data/ ./demo/data/

# Own everything by the non-root user
RUN mkdir -p /data && chown -R ores:ores /app /data

USER 1001

EXPOSE 8000

# Kubernetes probes can hit GET /login-page (public, no auth required)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/login-page')"]

# Single worker: SQLite tokenstore cannot share state across processes.
# For multi-worker, replace SQLite with PostgreSQL or Redis.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]

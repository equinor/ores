# ============================================================
#  WeCo — Multi-well Correlation Engine
#  Docker build for headless (server / API / batch) usage
# ============================================================
#
#  Build:
#    docker build -t weco:latest .
#
#  Run tests:
#    docker run --rm weco:latest pytest -v pytest/
#
#  Run the REST API:
#    docker run --rm -p 8000:8000 weco:latest \
#        python -m uvicorn weco.api:app --host 0.0.0.0 --port 8000
#
#  Interactive Python:
#    docker run --rm -it weco:latest python
#
# ============================================================

# ---- Stage 1: build C++ extension -------------------------------------------
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential g++ cmake ninja-build git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only what's needed for the build (maximise layer cache)
COPY VERSION CMakeLists.txt pyproject.toml setup.cfg MANIFEST.in ReadMe.md ./
COPY cmake/       cmake/
COPY include/     include/
COPY src/         src/
COPY binding/     binding/
COPY pybind11/    pybind11/
COPY weco/        weco/
COPY demo/        demo/
COPY pytest/      pytest/

# Install build deps and build wheel
RUN pip install --no-cache-dir scikit-build-core pybind11 && \
    pip wheel --no-build-isolation -w /wheels .

# ---- Stage 2: slim runtime image -------------------------------------------
FROM python:3.12-slim AS runtime

LABEL maintainer="RING Team <ring@georessources.univ-lorraine.fr>"
LABEL description="WeCo — Multi-well stratigraphic correlation engine"
LABEL version="0.9.31"

# Runtime system deps (none beyond Python — everything is statically linked)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the wheel + optional extras
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && \
    pip install --no-cache-dir \
        scikit-learn>=1.3 \
        fastapi uvicorn[standard] && \
    rm -rf /wheels

# Copy demo data, scripts, and tests
COPY demo/   demo/
COPY pytest/ pytest/

# Smoke test: import the engine
RUN python -c "import weco.engine; print('WeCo engine OK — version', open('VERSION').read().strip() if False else 'built')"

# Default entrypoint: run tests
CMD ["pytest", "-v", "pytest/"]

# Expose API port
EXPOSE 8000

# ---- Build Stage ----
FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir build && \
    python -m build --wheel --outdir /app/dist

# ---- Runtime Stage ----
FROM python:3.12-slim AS runtime

LABEL maintainer="FlowMesh Contributors"
LABEL description="FlowMesh — Distributed Task Orchestration Engine"

RUN groupadd --gid 1000 flowmesh && \
    useradd --uid 1000 --gid flowmesh --shell /bin/bash --create-home flowmesh

WORKDIR /app

COPY --from=builder /app/dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

USER flowmesh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["uvicorn", "flowmesh.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

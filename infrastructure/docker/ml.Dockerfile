# Planning engine image. The forecast model and embedding model are built in, so it runs offline.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON_DOWNLOADS=0
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src src
COPY ml/src ml/src
# uv rebuilds a cached local project only when pyproject.toml changes, so force it: otherwise the
# image can silently ship the previous build's code
RUN --mount=type=cache,target=/root/.cache/uv     uv sync --frozen --no-dev --no-editable --reinstall-package ai-scm-platform
COPY ml/experiments ml/experiments
ENV PATH=/opt/venv/bin:$PATH FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python -m scm_ml.forecast --source synthetic \
    && python -c "from scm_ml.knowledge import FastEmbedEmbedder; FastEmbedEmbedder()"

FROM python:3.12-slim-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home scm \
    && mkdir -p /var/lib/scm && chown scm /var/lib/scm
COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/fastembed /opt/fastembed
COPY --from=build /app/ml/artifacts /app/ml/artifacts
COPY --from=build /app/ml/experiments /app/ml/experiments
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    HF_HUB_OFFLINE=1 \
    SCM_ML_HOST=0.0.0.0 \
    SCM_ML_PORT=8001 \
    SCM_ML_EXPERIMENT_DIR=/app/ml/experiments \
    SCM_ML_STATE_PATH=/var/lib/scm/engine-state.sqlite
WORKDIR /app
USER 10001
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=2)"
CMD ["python", "-m", "scm_ml.service"]

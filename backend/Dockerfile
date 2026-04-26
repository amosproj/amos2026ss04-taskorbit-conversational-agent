# syntax=docker/dockerfile:1.7
#
# Multi-stage Dockerfile.
#
#   `dev`  — has Poetry installed, source bind-mounted, hot reload on.
#            Used by docker-compose.yml.
#   `prod` — slim runtime image with only the resolved venv copied in.
#
# Build a specific stage with:
#   docker build --target dev -t taskorbit-backend:dev backend/
#   docker build --target prod -t taskorbit-backend:prod backend/

# ---------- Base ----------
    FROM python:3.11-slim AS base

    ENV PYTHONUNBUFFERED=1 \
        PYTHONDONTWRITEBYTECODE=1 \
        PIP_NO_CACHE_DIR=1 \
        PIP_DISABLE_PIP_VERSION_CHECK=1 \
        POETRY_VERSION=1.8.4 \
        POETRY_NO_INTERACTION=1 \
        POETRY_VIRTUALENVS_IN_PROJECT=1
    
    WORKDIR /app
    
    RUN apt-get update \
        && apt-get install -y --no-install-recommends \
            build-essential \
            curl \
            ffmpeg \
        && rm -rf /var/lib/apt/lists/*
    
    RUN pip install "poetry==${POETRY_VERSION}"
    
    # ---------- Builder: install deps into /app/.venv ----------
    FROM base AS builder
    
    COPY pyproject.toml poetry.lock* ./
    # `--no-root` so the project itself is not installed yet — sources are copied in the next step.
    RUN poetry install --only main --no-root --no-ansi
    
    COPY src ./src
    RUN poetry install --only main --no-ansi
    
    # ---------- Dev image ----------
    FROM base AS dev
    
    ENV PATH="/app/.venv/bin:${PATH}"
    
    COPY --from=builder /app/.venv /app/.venv
    COPY pyproject.toml poetry.lock* ./
    COPY src ./src
    COPY tests ./tests
    
    EXPOSE 8000
    CMD ["poetry", "run", "taskorbit-api", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    
    # ---------- Prod image ----------
    FROM python:3.11-slim AS prod
    
    ENV PYTHONUNBUFFERED=1 \
        PYTHONDONTWRITEBYTECODE=1 \
        PATH="/app/.venv/bin:${PATH}"
    
    WORKDIR /app
    
    RUN apt-get update \
        && apt-get install -y --no-install-recommends ffmpeg \
        && rm -rf /var/lib/apt/lists/*
    
    COPY --from=builder /app/.venv /app/.venv
    COPY src ./src
    
    EXPOSE 8000
    CMD ["uvicorn", "taskorbit.main:app", "--host", "0.0.0.0", "--port", "8000"]
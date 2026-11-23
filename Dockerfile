# The api and the worker: one image, two commands (see docker-compose.yml).
FROM python:3.12-slim

# ffmpeg and ffprobe decode uploads; git fetches dopplertrack at its pinned commit.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
# dependencies first, so a change to our code does not download them again
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend ./backend
COPY README.md LICENSE ./
RUN uv sync --frozen --no-dev

# Runs as whatever user compose gives it (the host's, so files in ./data stay yours), which
# may have no home: point anything that wants one at /tmp.
ENV PATH="/app/.venv/bin:$PATH" HOME=/tmp MPLCONFIGDIR=/tmp/matplotlib \
    DATA_DIR=/data DOPPLERTRACK_CACHE=/data/cache/dopplertrack PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

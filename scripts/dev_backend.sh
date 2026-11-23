#!/usr/bin/env bash
# The api and the worker together, for development. Settings come from .env (see .env.example).
#   scripts/dev_backend.sh [port]
set -euo pipefail
cd "$(dirname "$0")/.."
# the worker watches this script and stops if it is killed, so none is ever left behind
TRACE_EXIT_WITH_PID=$$ uv run python -m app.worker &
WORKER=$!
trap 'kill $WORKER 2>/dev/null || true' EXIT INT TERM
uv run uvicorn app.api.main:app --host 127.0.0.1 --port "${1:-8000}"

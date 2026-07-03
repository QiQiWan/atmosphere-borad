#!/usr/bin/env bash
set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$ROOT_DIR/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r "$BACKEND_DIR/requirements.txt"

# Load environment variables before choosing default host/port and before the pre-start cache checker.
set -a
if [ -f "$ROOT_DIR/.env" ]; then
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
fi
if [ -f "$BACKEND_DIR/.env" ]; then
  # shellcheck disable=SC1091
  source "$BACKEND_DIR/.env"
fi
set +a

export BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
export BACKEND_PORT="${BACKEND_PORT:-52000}"

if [ "${SKIP_KILL_BACKEND_PORT:-false}" != "true" ]; then
  echo "Checking stale backend processes on port ${BACKEND_PORT}..."
  if command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -tiTCP:${BACKEND_PORT} -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      echo "Stopping stale backend process(es): $PIDS"
      kill $PIDS 2>/dev/null || true
      sleep 1
      kill -9 $PIDS 2>/dev/null || true
    fi
  elif command -v fuser >/dev/null 2>&1; then
    if fuser ${BACKEND_PORT}/tcp >/dev/null 2>&1; then
      echo "Stopping stale backend process(es) by fuser on ${BACKEND_PORT}/tcp"
      fuser -k ${BACKEND_PORT}/tcp >/dev/null 2>&1 || true
    fi
  else
    echo "lsof/fuser not found; skip stale port cleanup."
  fi
fi

echo "Running pre-start server database cache checker..."
python "$BACKEND_DIR/cache_checker.py"

cd "$BACKEND_DIR"
echo "Starting Flask backend on ${BACKEND_HOST}:${BACKEND_PORT}"
exec python app.py

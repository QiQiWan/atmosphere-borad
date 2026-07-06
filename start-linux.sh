#!/usr/bin/env bash
set -e

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$ROOT_DIR/.venv"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required."
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required. Recommended version: Node 18 or later."
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


export BACKEND_PORT="${BACKEND_PORT:-52000}"
export BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"

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

echo "Starting backend at http://127.0.0.1:${BACKEND_PORT}"
cd "$BACKEND_DIR"
python app.py &
BACKEND_PID=$!

echo "Waiting for backend health check..."
for i in $(seq 1 30); do
  if command -v python >/dev/null 2>&1 && python - <<PY >/dev/null 2>&1
import json, urllib.request, sys
try:
    with urllib.request.urlopen("http://127.0.0.1:${BACKEND_PORT}/api/borad/health", timeout=2) as r:
        data = json.loads(r.read().decode("utf-8"))
    sys.exit(0 if data.get("version") == "1.7.9" else 1)
except Exception:
    sys.exit(1)
PY
  then
    echo "Backend v1.7.9 is ready."
    break
  fi
  sleep 1
done

cleanup() {
  echo "Stopping backend..."
  kill "$BACKEND_PID" >/dev/null 2>&1 || true
}
trap cleanup EXIT

cd "$ROOT_DIR"
if [ ! -d node_modules ]; then
  if command -v pnpm >/dev/null 2>&1; then
    pnpm install
  else
    npm install
  fi
fi

if command -v pnpm >/dev/null 2>&1; then
  pnpm dev
else
  npm run dev
fi

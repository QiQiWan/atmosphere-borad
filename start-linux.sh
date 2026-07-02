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

if [ -f "$BACKEND_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$BACKEND_DIR/.env"
  set +a
fi

export BACKEND_PORT="${BACKEND_PORT:-52000}"
export BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"

echo "Starting backend at http://127.0.0.1:${BACKEND_PORT}"
cd "$BACKEND_DIR"
python app.py &
BACKEND_PID=$!

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

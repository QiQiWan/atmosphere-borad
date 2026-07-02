#!/usr/bin/env bash
set -e
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if command -v pnpm >/dev/null 2>&1; then
  pnpm install
  pnpm build
else
  npm install
  npm run build
fi

echo "Frontend build completed: $ROOT_DIR/dist"
echo "Copy dist/ to /opt/borad-vue3/dist or keep Nginx root pointed to this dist directory."

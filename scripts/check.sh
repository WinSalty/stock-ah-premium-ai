#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
ruff check app tests
pytest

cd "$ROOT_DIR/frontend"
npm run build
npm audit --omit=dev

echo "Checks completed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port "${BACKEND_PORT:-8000}" --reload

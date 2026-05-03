#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/opt/homebrew/bin/python3.13}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found: $PYTHON_BIN" >&2
  echo "Set PYTHON_BIN to a Python 3.11+ executable." >&2
  exit 1
fi

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
. .venv/bin/activate
pip install -e ".[dev]"

cd "$ROOT_DIR/frontend"
npm install

echo "Bootstrap completed."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MYSQL_BIN="${MYSQL_BIN:-/opt/homebrew/opt/mysql@5.7/bin/mysql}"

if [[ ! -x "$MYSQL_BIN" ]]; then
  echo "MySQL client not found: $MYSQL_BIN" >&2
  echo "Set MYSQL_BIN or check /Users/salty/codeProject/ai/doc/mysqluse.md." >&2
  exit 1
fi

"$MYSQL_BIN" -u root < "$ROOT_DIR/resources/sql/00_create_database.sql"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
alembic upgrade head

"$MYSQL_BIN" -u root stock_ah_ai < "$ROOT_DIR/resources/sql/01_readonly_views.sql"

echo "Database initialized."

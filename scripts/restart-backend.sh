#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

print_section "Restart backend"
"$ROOT_DIR/scripts/stop-backend.sh"
log_info "Starting backend in foreground."
exec "$ROOT_DIR/scripts/start-backend.sh"

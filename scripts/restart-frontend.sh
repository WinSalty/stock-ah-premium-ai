#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

print_section "Restart frontend"
"$ROOT_DIR/scripts/stop-frontend.sh"
log_info "Starting frontend in foreground."
exec "$ROOT_DIR/scripts/start-frontend.sh"

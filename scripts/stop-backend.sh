#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"

print_section "Stop backend"
log_info "Target port: $BACKEND_PORT"
stop_port "backend" "$BACKEND_PORT"

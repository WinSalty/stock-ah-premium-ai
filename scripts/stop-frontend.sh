#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

FRONTEND_PORT="${FRONTEND_PORT:-5173}"

print_section "Stop frontend"
log_info "Target port: $FRONTEND_PORT"
stop_port "frontend" "$FRONTEND_PORT"

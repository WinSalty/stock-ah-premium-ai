#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"

print_section "Restart project services"
mkdir -p "$LOG_DIR"

"$ROOT_DIR/scripts/stop.sh"

log_info "Starting backend in background. Log: $LOG_DIR/backend.log"
BACKEND_PORT="$BACKEND_PORT" "$ROOT_DIR/scripts/start-backend.sh" >"$LOG_DIR/backend.log" 2>&1 &
printf "%s\n" "$!" > "$RUNTIME_DIR/backend.pid"

if ! wait_for_port "backend" "$BACKEND_PORT" 25; then
  log_error "Backend failed to start. Last log lines:"
  tail -40 "$LOG_DIR/backend.log" >&2 || true
  exit 1
fi

log_info "Starting frontend in background. Log: $LOG_DIR/frontend.log"
FRONTEND_PORT="$FRONTEND_PORT" "$ROOT_DIR/scripts/start-frontend.sh" >"$LOG_DIR/frontend.log" 2>&1 &
printf "%s\n" "$!" > "$RUNTIME_DIR/frontend.pid"

if ! wait_for_port "frontend" "$FRONTEND_PORT" 25; then
  log_error "Frontend failed to start. Last log lines:"
  tail -40 "$LOG_DIR/frontend.log" >&2 || true
  exit 1
fi

print_section "Restart complete"
log_info "Backend: http://127.0.0.1:$BACKEND_PORT"
log_info "Frontend: http://127.0.0.1:$FRONTEND_PORT"
log_info "Backend log: $LOG_DIR/backend.log"
log_info "Frontend log: $LOG_DIR/frontend.log"
log_info "Stop command: ./scripts/stop.sh"

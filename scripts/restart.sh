#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"

print_section "Restart project services"

# 整项目重启走后台模式，日志和 pid 文件都放在 .runtime 目录下。
mkdir -p "$LOG_DIR"

# 先清理旧监听进程，确保后续 strictPort 检查不会误判为端口占用。
"$ROOT_DIR/scripts/stop.sh"

log_info "Starting backend in background. Log: $LOG_DIR/backend.log"
BACKEND_PORT="$BACKEND_PORT" "$ROOT_DIR/scripts/start-backend.sh" >"$LOG_DIR/backend.log" 2>&1 &
printf "%s\n" "$!" > "$RUNTIME_DIR/backend.pid"

# 等端口开始监听后再启动前端，避免前端代理刚启动就连不上后端。
if ! wait_for_port "backend" "$BACKEND_PORT" 25; then
  log_error "Backend failed to start. Last log lines:"
  tail -40 "$LOG_DIR/backend.log" >&2 || true
  exit 1
fi

log_info "Starting frontend in background. Log: $LOG_DIR/frontend.log"

# 把 BACKEND_PORT 传给前端启动脚本和 Vite 配置，保证 /api 代理目标一致。
BACKEND_PORT="$BACKEND_PORT" FRONTEND_PORT="$FRONTEND_PORT" "$ROOT_DIR/scripts/start-frontend.sh" >"$LOG_DIR/frontend.log" 2>&1 &
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

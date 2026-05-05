#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

# 可通过环境变量覆盖默认端口；BACKEND_PORT 会同步给 Vite 代理配置使用。
#   FRONTEND_PORT=5174 BACKEND_PORT=8001 ./scripts/start-frontend.sh
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

print_section "Frontend startup diagnostics"
log_info "Project root: $ROOT_DIR"
log_info "Frontend directory: $ROOT_DIR/frontend"
log_info "Bind address: http://$FRONTEND_HOST:$FRONTEND_PORT"
log_info "Backend proxy target: http://127.0.0.1:$BACKEND_PORT"
log_info "VITE_API_BASE_URL: ${VITE_API_BASE_URL:-not set, using Vite /api proxy}"

# 前端开发服务使用 strictPort，端口被占用时明确失败并给出占用进程。
require_command lsof "Install lsof or use macOS system lsof."
require_command npm "Install Node.js/npm, then run scripts/bootstrap.sh."
ensure_port_free "frontend" "$FRONTEND_PORT"

cd "$ROOT_DIR/frontend"
if [[ ! -d node_modules ]]; then
  log_error "Frontend node_modules is missing. Run scripts/bootstrap.sh first."
  exit 1
fi
log_info "Node: $(node --version 2>&1)"
log_info "npm: $(npm --version 2>&1)"
log_info "Stop command: ./scripts/stop-frontend.sh"
log_info "Restart command: ./scripts/restart-frontend.sh"
print_section "Frontend process output"

# start-frontend.sh 是前台开发模式；需要后台运行时使用 ./scripts/restart.sh。
exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort

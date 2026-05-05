#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

print_section "Restart backend"

# 单服务重启保持前台运行，方便开发时直接查看 uvicorn reload 日志。
"$ROOT_DIR/scripts/stop-backend.sh"
log_info "Starting backend in foreground."
exec "$ROOT_DIR/scripts/start-backend.sh"

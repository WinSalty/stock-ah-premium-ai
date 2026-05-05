#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

print_section "Restart frontend"

# 单服务重启保持前台运行，方便开发时直接查看 Vite 输出。
"$ROOT_DIR/scripts/stop-frontend.sh"
log_info "Starting frontend in foreground."
exec "$ROOT_DIR/scripts/start-frontend.sh"

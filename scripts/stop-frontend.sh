#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

# 停止脚本按端口处理，避免依赖 pid 文件是否存在或是否过期。
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

print_section "Stop frontend"
log_info "Target port: $FRONTEND_PORT"
stop_port "frontend" "$FRONTEND_PORT"

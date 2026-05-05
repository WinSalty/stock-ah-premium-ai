#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

print_section "Stop project services"

# 先停前端再停后端，避免浏览器代理继续把请求打到正在退出的后端。
"$ROOT_DIR/scripts/stop-frontend.sh"
"$ROOT_DIR/scripts/stop-backend.sh"
log_info "Project services stopped."

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$ROOT_DIR/scripts/lib-runtime.sh"

# 可通过环境变量覆盖默认监听地址：
#   BACKEND_HOST=0.0.0.0 BACKEND_PORT=8001 ./scripts/start-backend.sh
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
BACKEND_ENV_FILE="$ROOT_DIR/backend/.env"

# 这些值只用于启动前诊断，不会把密钥内容打印到终端。
DATABASE_URL="$(read_env_value "$BACKEND_ENV_FILE" "STOCK_AH_DB_URL" | mask_database_url)"
TUSHARE_TOKEN_FILE="$(read_env_value "$BACKEND_ENV_FILE" "TUSHARE_TOKEN_FILE")"
LLM_API_KEY_FILE="$(read_env_value "$BACKEND_ENV_FILE" "LLM_API_KEY_FILE")"
QWEN_API_KEY_FILE="$(read_env_value "$BACKEND_ENV_FILE" "QWEN_API_KEY_FILE")"
SYNC_SCHEDULER_ENABLED="$(read_env_value "$BACKEND_ENV_FILE" "SYNC_SCHEDULER_ENABLED")"
ALERT_SCHEDULER_ENABLED="$(read_env_value "$BACKEND_ENV_FILE" "ALERT_SCHEDULER_ENABLED")"

print_section "Backend startup diagnostics"
log_info "Project root: $ROOT_DIR"
log_info "Backend directory: $ROOT_DIR/backend"
log_info "Bind address: http://$BACKEND_HOST:$BACKEND_PORT"
log_info "Health check: http://$BACKEND_HOST:$BACKEND_PORT/api/health"
log_info "Public settings: http://$BACKEND_HOST:$BACKEND_PORT/api/settings/public"

# .env 缺失时仍继续输出后续诊断，让用户一次看到更多问题。
if [[ -f "$BACKEND_ENV_FILE" ]]; then
  log_info "Env file: $BACKEND_ENV_FILE"
else
  log_warn "Env file missing: $BACKEND_ENV_FILE"
  log_warn "Create it with: cp backend/.env.example backend/.env"
fi

if [[ -n "$DATABASE_URL" ]]; then
  log_info "Database URL: $DATABASE_URL"
else
  log_warn "STOCK_AH_DB_URL is not set in backend/.env; app will use code defaults or environment."
fi

# 只检查密钥文件是否存在，避免把 token 或 API key 打到日志里。
if [[ -n "$TUSHARE_TOKEN_FILE" ]]; then
  [[ -f "$TUSHARE_TOKEN_FILE" ]] && log_info "Tushare token file exists: $TUSHARE_TOKEN_FILE" || log_warn "Tushare token file not found: $TUSHARE_TOKEN_FILE"
fi
if [[ -n "$LLM_API_KEY_FILE" ]]; then
  [[ -f "$LLM_API_KEY_FILE" ]] && log_info "DeepSeek key file exists: $LLM_API_KEY_FILE" || log_warn "DeepSeek key file not found: $LLM_API_KEY_FILE"
fi
if [[ -n "$QWEN_API_KEY_FILE" ]]; then
  [[ -f "$QWEN_API_KEY_FILE" ]] && log_info "Qwen key file exists: $QWEN_API_KEY_FILE" || log_warn "Qwen key file not found: $QWEN_API_KEY_FILE"
fi
log_info "Sync scheduler enabled: ${SYNC_SCHEDULER_ENABLED:-not set}"
log_info "Alert scheduler enabled: ${ALERT_SCHEDULER_ENABLED:-not set}"

# 先检查端口占用，避免 uvicorn 报错信息被 reload 进程刷屏淹没。
require_command lsof "Install lsof or use macOS system lsof."
ensure_port_free "backend" "$BACKEND_PORT"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  log_error "Backend .venv is missing. Run scripts/bootstrap.sh first."
  exit 1
fi
. .venv/bin/activate
log_info "Python: $(python --version 2>&1)"
log_info "Uvicorn: $(uvicorn --version 2>&1)"

# 启动失败常见原因是本地库未执行最新迁移，所以启动前打印当前 revision。
if ALEMBIC_CURRENT="$(alembic current 2>&1)"; then
  log_info "Alembic current: ${ALEMBIC_CURRENT:-no revision}"
else
  log_warn "Alembic current failed: $ALEMBIC_CURRENT"
  log_warn "If startup fails with missing columns, run: cd backend && ./.venv/bin/alembic upgrade head"
fi
if ALEMBIC_HEADS="$(alembic heads 2>&1)"; then
  log_info "Alembic heads: ${ALEMBIC_HEADS:-no revision}"
fi
log_info "Stop command: ./scripts/stop-backend.sh"
log_info "Restart command: ./scripts/restart-backend.sh"
print_section "Backend process output"

# start-backend.sh 是前台开发模式；需要后台运行时使用 ./scripts/restart.sh。
exec uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload

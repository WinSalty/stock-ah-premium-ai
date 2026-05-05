#!/usr/bin/env bash

# 运行脚本公共工具库：
# - 统一输出带时间戳的日志，方便排查后台日志。
# - 统一检查端口占用、停止端口监听进程。
# - 读取 .env 中的非敏感配置，并对数据库密码做脱敏展示。

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

# 普通信息输出到 stdout，便于 restart.sh 写入日志文件。
log_info() {
  printf "[%s] %s\n" "$(timestamp)" "$*"
}

# 告警和错误输出到 stderr，终端里更容易和正常日志区分。
log_warn() {
  printf "[%s] WARN: %s\n" "$(timestamp)" "$*" >&2
}

log_error() {
  printf "[%s] ERROR: %s\n" "$(timestamp)" "$*" >&2
}

print_section() {
  printf "\n== %s ==\n" "$*"
}

require_command() {
  local command_name="$1"
  local install_hint="$2"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    log_error "Command not found: $command_name"
    log_error "$install_hint"
    exit 1
  fi
}

# 返回指定端口上的 LISTEN 进程 PID；没有占用时返回空。
port_pids() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

# 展示端口占用详情，保留 COMMAND/PID/USER 等 lsof 字段。
print_port_processes() {
  local port="$1"
  local pids
  pids="$(port_pids "$port")"
  if [[ -z "$pids" ]]; then
    log_info "Port $port is free."
    return
  fi
  log_warn "Port $port is already in use:"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN >&2 || true
}

# 启动前先失败退出，而不是让后端或 Vite 自己报一串不直观的端口错误。
ensure_port_free() {
  local service_name="$1"
  local port="$2"
  if [[ -z "$(port_pids "$port")" ]]; then
    log_info "$service_name port $port is free."
    return
  fi
  print_port_processes "$port"
  log_error "$service_name cannot start because port $port is occupied."
  log_error "Run ./scripts/stop-${service_name}.sh, or choose another port, for example ${service_name^^}_PORT=$((port + 1)) ./scripts/start-${service_name}.sh"
  exit 1
}

# 按端口停止服务：
# - 先发 SIGTERM，给 uvicorn/vite 清理机会。
# - 若短时间内仍未释放端口，再发 SIGKILL，避免重启脚本卡住。
stop_port() {
  local service_name="$1"
  local port="$2"
  local pids
  pids="$(port_pids "$port" | tr "\n" " " | xargs || true)"
  if [[ -z "$pids" ]]; then
    log_info "$service_name is not listening on port $port."
    return
  fi
  print_port_processes "$port"
  log_info "Stopping $service_name on port $port. PIDs: $pids"
  kill $pids 2>/dev/null || true
  for _ in {1..20}; do
    if [[ -z "$(port_pids "$port")" ]]; then
      log_info "$service_name stopped."
      return
    fi
    sleep 0.25
  done
  local remaining
  remaining="$(port_pids "$port" | tr "\n" " " | xargs || true)"
  if [[ -n "$remaining" ]]; then
    log_warn "$service_name did not stop gracefully; sending SIGKILL to: $remaining"
    kill -9 $remaining 2>/dev/null || true
  fi
}

# restart.sh 后台拉起服务后，只关心端口是否开始监听。
# 真正的业务健康检查仍由用户或后端 /api/health 判断。
wait_for_port() {
  local service_name="$1"
  local port="$2"
  local seconds="${3:-20}"
  for _ in $(seq 1 "$seconds"); do
    if [[ -n "$(port_pids "$port")" ]]; then
      log_info "$service_name is listening on port $port."
      return 0
    fi
    sleep 1
  done
  log_error "$service_name did not listen on port $port within ${seconds}s."
  return 1
}

# 轻量读取 key=value 配置；只用于启动诊断，不承担完整 dotenv 解析。
read_env_value() {
  local env_file="$1"
  local key="$2"
  if [[ ! -f "$env_file" ]]; then
    return
  fi
  grep -E "^${key}=" "$env_file" | tail -1 | cut -d "=" -f 2- || true
}

# 日志里只展示数据库连接形态，不泄露本机数据库密码。
mask_database_url() {
  sed -E "s#(mysql\\+pymysql://[^:/@]+:)[^@]+@#\\1***@#"
}

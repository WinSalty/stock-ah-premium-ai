#!/usr/bin/env bash

timestamp() {
  date "+%Y-%m-%d %H:%M:%S"
}

log_info() {
  printf "[%s] %s\n" "$(timestamp)" "$*"
}

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

port_pids() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

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

read_env_value() {
  local env_file="$1"
  local key="$2"
  if [[ ! -f "$env_file" ]]; then
    return
  fi
  grep -E "^${key}=" "$env_file" | tail -1 | cut -d "=" -f 2- || true
}

mask_database_url() {
  sed -E "s#(mysql\\+pymysql://[^:/@]+:)[^@]+@#\\1***@#"
}

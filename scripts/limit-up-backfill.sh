#!/usr/bin/env bash
# 打板回测数据回填入口：信号/对照组/不复权行情 + a_stock_st 历史，一次性运维工具。
# 依赖真实 Tushare(a_stock_st)与腾讯行情(quotes)，会产生外部请求，仅手动执行不进 CI。
# 顺序依赖：行情(quotes)先于对照组(pool)与最终回测；a_stock_st 先于 signals。
# 用法示例：
#   ./scripts/limit-up-backfill.sh --step all                                  # 全量按序串跑
#   ./scripts/limit-up-backfill.sh --step a_stock_st --st-start-date 2025-08-12
#   ./scripts/limit-up-backfill.sh --step quotes --resume                      # 行情断点续跑
#   ./scripts/limit-up-backfill.sh --step signals --start-date 2026-05-07 --end-date 2026-06-12
#   ./scripts/limit-up-backfill.sh --step pool
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
python tests/backfill/limit_up_backfill.py "$@"

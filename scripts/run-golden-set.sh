#!/usr/bin/env bash
# 金标集跑批入口：依赖真实 LLM 调用并产生费用，仅供 dev 环境手动执行，不进 CI。
# 用法示例：
#   ./scripts/run-golden-set.sh --limit 10                  # 采样 10 条
#   ./scripts/run-golden-set.sh --category refusal          # 只跑拒答类
#   ./scripts/run-golden-set.sh --resume --report-tag baseline  # 断点续跑并标记报告
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
python tests/golden/run_golden_set.py "$@"

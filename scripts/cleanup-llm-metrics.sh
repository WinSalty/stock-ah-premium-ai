#!/usr/bin/env bash
# LLM 调用指标保留期清理（旧评审 R4）：删除早于 LLM_METRIC_RETENTION_DAYS 天的指标记录。
# 按需手动执行或挂 cron（如每日凌晨）。保留天数 <=0 时不清理。
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR/backend"
if [[ ! -d .venv ]]; then
  echo "Backend .venv is missing. Run scripts/bootstrap.sh first." >&2
  exit 1
fi
. .venv/bin/activate
python - <<'PY'
from app.db.session import SessionLocal
from app.services.llm_metric_maintenance import cleanup_expired_metrics

with SessionLocal() as db:
    deleted = cleanup_expired_metrics(db)
    print(f"已删除过期 LLM 指标 {deleted} 条")
PY

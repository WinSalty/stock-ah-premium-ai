import { requestJson } from './client';
import type {
  DividendReinvestmentHealth,
  DividendReinvestmentRun,
  DividendReinvestmentSummaryParams,
  DividendReinvestmentSummaryResponse,
  DividendReinvestmentYearlyItem
} from '../types/domain';

export function fetchDividendReinvestmentHealth() {
  // 查询数据健康状态，用于判断分红、行情和最新指标是否足够支撑筛选榜单展示。
  return requestJson<DividendReinvestmentHealth>('/api/dividend-reinvestment/health');
}

export function fetchDividendReinvestmentRuns(limit = 20) {
  // 只读取最近批次，避免回测历史过多时拖慢筛选页初始化。
  return requestJson<DividendReinvestmentRun[]>(`/api/dividend-reinvestment/runs?limit=${limit}`);
}

export function fetchDividendReinvestmentSummaries(params: DividendReinvestmentSummaryParams) {
  // 过滤空参数，确保用户清空筛选项后不会把空字符串传给后端查询条件。
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<DividendReinvestmentSummaryResponse>(
    `/api/dividend-reinvestment/summaries?${search.toString()}`
  );
}

export function fetchDividendReinvestmentYearly(tsCode: string, runId?: number | null) {
  // 年度明细按股票代码和可选批次读取；未指定批次时后端使用最新成功回测结果。
  const search = new URLSearchParams();
  if (runId) {
    search.set('run_id', String(runId));
  }
  return requestJson<DividendReinvestmentYearlyItem[]>(
    `/api/dividend-reinvestment/yearly/${encodeURIComponent(tsCode)}?${search.toString()}`
  );
}

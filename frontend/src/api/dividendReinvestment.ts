import { API_BASE_URL, ApiError, getAuthToken, requestJson } from './client';
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

export async function exportDividendReinvestmentSummaries(params: DividendReinvestmentSummaryParams) {
  // 导出沿用榜单筛选和排序参数，但不传分页，让后端一次性生成完整筛选结果与年度明细。
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (!['page', 'page_size'].includes(key) && value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  const token = getAuthToken();
  const response = await fetch(
    `${API_BASE_URL}/api/dividend-reinvestment/export?${search.toString()}`,
    {
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      }
    }
  );
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.detail || response.statusText);
  }
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(response.headers.get('Content-Disposition'))
  };
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

/** 从后端 Content-Disposition 中解析 UTF-8 文件名，失败时使用稳定兜底名。 */
function parseDownloadFilename(contentDisposition: string | null) {
  const match = contentDisposition?.match(/filename\*=UTF-8''([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '分红再投筛选.xlsx';
}

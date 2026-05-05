import { requestJson } from './client';
import type { LlmMetricParams, LlmMetricResponse } from '../types/domain';

/**
 * 查询 LLM 调用耗时指标。
 * 创建日期：2026-05-05
 * author: sunshengxian
 */
export function fetchLlmMetrics(params: LlmMetricParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<LlmMetricResponse>(`/api/llm-metrics?${search.toString()}`);
}

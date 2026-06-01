import { requestJson } from './client';
import type { LlmMetricParams, LlmMetricResponse, LlmMetricSummary, LlmMetricSummaryParams } from '../types/domain';

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

/**
 * 懒加载 LLM 调用耗时统计摘要。
 * 创建日期：2026-06-01
 * author: sunshengxian
 */
export function fetchLlmMetricSummary(params: LlmMetricSummaryParams) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<LlmMetricSummary>(`/api/llm-metrics/summary?${search.toString()}`);
}

/**
 * 懒加载单条 LLM 调用耗时指标详情。
 * 创建日期：2026-06-02
 * author: sunshengxian
 */
export function fetchLlmMetricDetail(metricId: number) {
  return requestJson<LlmMetricResponse['rows'][number]>(`/api/llm-metrics/${metricId}`);
}

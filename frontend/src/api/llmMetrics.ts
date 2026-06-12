import { requestJson } from './client';
import type {
  LlmMetricParams,
  LlmMetricResponse,
  LlmMetricSummary,
  LlmMetricSummaryParams,
  LlmRoundParams,
  LlmRoundResponse
} from '../types/domain';

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

/**
 * 查询"按对话轮"聚合的 LLM 耗时列表。
 * 聚合口径：一轮 = 一个 question_id，后端把该轮全部阶段记录汇总为一行（阶段数 / LLM 调用数 / 工具执行数 /
 * 是否含失败 / 耗时求和 / 起止时间），按轮起始时间倒序返回；阶段明细需另调 fetchLlmMetrics 按 question_id 懒加载。
 * 创建日期：2026-06-12
 * author: sunshengxian
 */
export function fetchLlmMetricRounds(params: LlmRoundParams) {
  const search = new URLSearchParams();
  // 与 fetchLlmMetrics 保持一致：跳过空值参数，避免后端把空字符串当作有效筛选条件。
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<LlmRoundResponse>(`/api/llm-metrics/rounds?${search.toString()}`);
}

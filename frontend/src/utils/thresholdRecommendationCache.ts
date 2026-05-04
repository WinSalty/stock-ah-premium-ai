import type { PremiumDirection } from '../types/domain';

const CACHE_PREFIX = 'stock-ah-premium-ai:threshold-recommendation:v1';
const CACHE_TIME_ZONE = 'Asia/Shanghai';

export interface ThresholdRecommendationCacheInput {
  aTsCode: string;
  hkTsCode: string;
  direction: PremiumDirection;
}

export interface ThresholdRecommendationCacheValue {
  answer: string;
  cacheDate: string;
  recommendedAt: string;
}

function todayInEast8() {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: CACHE_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).format(new Date());
}

function cacheKey(input: ThresholdRecommendationCacheInput, cacheDate = todayInEast8()) {
  return [
    CACHE_PREFIX,
    cacheDate,
    input.aTsCode.toUpperCase(),
    input.hkTsCode.toUpperCase(),
    input.direction
  ].join(':');
}

/**
 * 读取同股同方向当天的 AI 阈值推荐。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export function getCachedThresholdRecommendation(input: ThresholdRecommendationCacheInput) {
  const cacheDate = todayInEast8();
  const raw = window.localStorage.getItem(cacheKey(input, cacheDate));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as ThresholdRecommendationCacheValue;
    if (parsed.cacheDate !== cacheDate || !parsed.answer) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

/**
 * 保存同股同方向当天的 AI 阈值推荐，避免重复调用 LLM。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export function setCachedThresholdRecommendation(
  input: ThresholdRecommendationCacheInput,
  answer: string
) {
  const cacheDate = todayInEast8();
  const value: ThresholdRecommendationCacheValue = {
    answer,
    cacheDate,
    recommendedAt: new Date().toISOString()
  };
  window.localStorage.setItem(cacheKey(input, cacheDate), JSON.stringify(value));
  return value;
}

import { requestJson } from './client';
import type { DataQueryParams, DataQueryResponse, QueryDatasetInfo } from '../types/domain';

/**
 * 查询可查看的数据集。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export function fetchQueryDatasets() {
  return requestJson<QueryDatasetInfo[]>('/api/query/datasets');
}

/**
 * 查询指定数据集的同步数据。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export function fetchQueryRows(params: DataQueryParams) {
  const search = new URLSearchParams();
  search.set('dataset', params.dataset);
  search.set('page', String(params.page));
  search.set('page_size', String(params.page_size));
  if (params.keyword) {
    search.set('keyword', params.keyword);
  }
  if (params.start_date) {
    search.set('start_date', params.start_date);
  }
  if (params.end_date) {
    search.set('end_date', params.end_date);
  }
  return requestJson<DataQueryResponse>(`/api/query/rows?${search.toString()}`);
}

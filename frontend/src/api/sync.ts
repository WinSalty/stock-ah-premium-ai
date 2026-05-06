import { requestJson } from './client';
import type {
  DatasetInfo,
  EastmoneyUnadjustedSyncBatchCreate,
  EastmoneyUnadjustedSyncBatchResponse,
  SyncBatchCreate,
  SyncRun,
  SyncRunCreate,
  SyncRunFilters
} from '../types/domain';

export function fetchDatasets() {
  return requestJson<DatasetInfo[]>('/api/datasets');
}

export function fetchSyncRuns(filters: SyncRunFilters = {}) {
  const search = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, String(value));
    }
  });
  return requestJson<SyncRun[]>(`/api/sync/runs?${search.toString()}`);
}

export function createSyncRun(payload: SyncRunCreate) {
  return requestJson<SyncRun>('/api/sync/runs', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function createAhPremiumSyncBatch(payload: SyncBatchCreate) {
  return requestJson<SyncRun[]>('/api/sync/batches/ah-premium', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function createEastmoneyUnadjustedSyncBatch(payload: EastmoneyUnadjustedSyncBatchCreate) {
  return requestJson<EastmoneyUnadjustedSyncBatchResponse>(
    '/api/sync/batches/eastmoney-unadjusted',
    {
      method: 'POST',
      body: JSON.stringify(payload)
    }
  );
}

import { requestJson } from './client';
import type {
  DatasetInfo,
  DividendReinvestmentSyncBatchCreate,
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

export function createDividendReinvestmentSyncBatch(payload: DividendReinvestmentSyncBatchCreate) {
  return requestJson<SyncRun>('/api/sync/batches/dividend-reinvestment-data', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

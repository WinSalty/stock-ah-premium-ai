import { requestJson } from './client';
import type { DatasetInfo, SyncRun, SyncRunCreate } from '../types/domain';

export function fetchDatasets() {
  return requestJson<DatasetInfo[]>('/api/datasets');
}

export function fetchSyncRuns() {
  return requestJson<SyncRun[]>('/api/sync/runs');
}

export function createSyncRun(payload: SyncRunCreate) {
  return requestJson<SyncRun>('/api/sync/runs', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

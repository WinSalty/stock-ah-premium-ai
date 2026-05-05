import { requestJson } from './client';
import type { OverviewChartSettings } from '../types/domain';

export function fetchOverviewChartSettings() {
  return requestJson<OverviewChartSettings>('/api/settings/overview-chart');
}

export function updateOverviewChartSettings(payload: OverviewChartSettings) {
  return requestJson<OverviewChartSettings>('/api/settings/overview-chart', {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}

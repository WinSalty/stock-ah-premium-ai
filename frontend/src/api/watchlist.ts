import { requestJson } from './client';
import type {
  WatchlistCreate,
  WatchlistOpportunity,
  WatchlistStock,
  WatchlistUpdate
} from '../types/domain';

export function fetchWatchlist(activeOnly = true) {
  const search = new URLSearchParams({ active_only: String(activeOnly) });
  return requestJson<WatchlistOpportunity[]>(`/api/watchlist?${search.toString()}`);
}

export function createWatchlistItem(payload: WatchlistCreate) {
  return requestJson<WatchlistStock>('/api/watchlist', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function updateWatchlistItem(id: number, payload: WatchlistUpdate) {
  return requestJson<WatchlistStock>(`/api/watchlist/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
}

export function deleteWatchlistItem(id: number) {
  return requestJson<{ ok: boolean }>(`/api/watchlist/${id}`, {
    method: 'DELETE'
  });
}

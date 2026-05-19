import { requestJson } from './client';
import type {
  WatchlistCandidate,
  WatchlistCreate,
  WatchlistOpportunity,
  WatchlistStock,
  WatchlistTargetType,
  WatchlistUpdate
} from '../types/domain';

export function fetchWatchlist(activeOnly = true) {
  const search = new URLSearchParams({ active_only: String(activeOnly) });
  return requestJson<WatchlistOpportunity[]>(`/api/watchlist?${search.toString()}`);
}

export function fetchWatchlistCandidates(
  targetType: WatchlistTargetType,
  keyword?: string,
  limit = 20
) {
  const search = new URLSearchParams({ target_type: targetType, limit: String(limit) });
  if (keyword?.trim()) {
    search.set('keyword', keyword.trim());
  }
  return requestJson<WatchlistCandidate[]>(`/api/watchlist/candidates?${search.toString()}`);
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

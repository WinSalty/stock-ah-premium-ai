import { requestJson } from './client';
import type { ImportResponse } from '../types/domain';

export type ImportKind = 'ah-pairs' | 'fx-rates';

export function importCsv(kind: ImportKind, content: string) {
  return requestJson<ImportResponse>(`/api/manual-import/${kind}/csv`, {
    method: 'POST',
    body: JSON.stringify({ content })
  });
}

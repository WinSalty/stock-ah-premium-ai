const EAST8_OFFSET_MS = 8 * 60 * 60 * 1000;
const DATE_ONLY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const TIMEZONE_PATTERN = /(z|[+-]\d{2}:?\d{2})$/i;
const DATETIME_FIELD_PATTERN = /(^|_)(created|updated|started|finished|resolved|source_updated)_at$|time$/i;

interface FormatDateTimeOptions {
  naiveAsEast8?: boolean;
}

/**
 * 将接口时间统一格式化为东八区 yyyy-MM-dd HH:mm:ss。
 * 创建日期：2026-05-04
 * author: sunshengxian
 */
export function formatEast8DateTime(value?: string | null, options?: FormatDateTimeOptions) {
  if (!value) {
    return '-';
  }
  if (DATE_ONLY_PATTERN.test(value)) {
    return value;
  }
  const normalized = value.trim().replace(' ', 'T');
  if (options?.naiveAsEast8 && !TIMEZONE_PATTERN.test(normalized)) {
    return formatNaiveDateTime(normalized);
  }
  const withTimezone = TIMEZONE_PATTERN.test(normalized) ? normalized : `${normalized}Z`;
  const parsed = new Date(withTimezone);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  const east8 = new Date(parsed.getTime() + EAST8_OFFSET_MS);
  return [
    east8.getUTCFullYear(),
    pad(east8.getUTCMonth() + 1),
    pad(east8.getUTCDate())
  ].join('-') + ` ${pad(east8.getUTCHours())}:${pad(east8.getUTCMinutes())}:${pad(east8.getUTCSeconds())}`;
}

export function formatFieldValue(value: unknown, fieldKey?: string) {
  if (value === null || value === undefined || value === '') {
    return '-';
  }
  if (typeof value === 'string' && shouldFormatAsDateTime(value, fieldKey)) {
    return formatEast8DateTime(value);
  }
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function shouldFormatAsDateTime(value: string, fieldKey?: string) {
  if (DATE_ONLY_PATTERN.test(value)) {
    return false;
  }
  return Boolean(
    (fieldKey && DATETIME_FIELD_PATTERN.test(fieldKey)) ||
      /^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}/.test(value)
  );
}

function pad(value: number) {
  return String(value).padStart(2, '0');
}

function formatNaiveDateTime(value: string) {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?/);
  if (!match) {
    return value;
  }
  return `${match[1]} ${match[2]}:${match[3]}:${match[4] || '00'}`;
}

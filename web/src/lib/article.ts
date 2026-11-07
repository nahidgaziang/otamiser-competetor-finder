/**
 * Helpers for rendering a stored ArticleDraft (pipeline/src/compare_pipeline/models_article.py) on the
 * public hub. Article content is model-written, so everything here is defensive: missing or malformed
 * fields render as nothing instead of crashing the page, and links are only emitted for safe URLs.
 */

export type Run = { text?: string; bold?: boolean; href?: string | null };
export type Paragraph = string | { runs?: Run[] };
export type Cell = { state?: string; text_content?: string | null };
export type Row = { feature_name?: string; competitor_cell?: Cell; baseline_cell?: Cell };
export type Category = { category_name?: string; rows?: Row[] };

/** Returns `value` when it is an array, otherwise an empty array. */
export function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

/**
 * Returns a URL that is safe to put in an `href`, or null.
 * Allows absolute http(s) URLs and same-site paths ("/pricing"). Rejects javascript:, data:, mailto:,
 * protocol-relative ("//evil.example") and backslash tricks ("/\evil.example"), which browsers treat
 * as another host.
 */
export function safeHref(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const value = raw.trim();
  if (!value || /[\u0000-\u001f\u007f\s]/.test(value)) return null;
  if (value.startsWith('/')) {
    return value[1] === '/' || value[1] === '\\' ? null : value;
  }
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.href : null;
  } catch {
    return null;
  }
}

/** True for absolute URLs (opened in a new tab with rel=noopener). */
export function isExternal(href: string): boolean {
  return /^https?:\/\//i.test(href);
}

/** "7 November 2026", or null for a missing or invalid date. */
export function formatDate(value: unknown): string | null {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(d);
}

/** First letter for a monogram badge. */
export function initial(name: unknown): string {
  const s = typeof name === 'string' ? name.trim() : '';
  return (s.match(/[\p{L}\p{N}]/u)?.[0] ?? '?').toUpperCase();
}

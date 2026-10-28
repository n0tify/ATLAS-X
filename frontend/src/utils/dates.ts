/** Safe timestamp formatting helpers. */

export function formatTimestamp(value: unknown, fallback = '-'): string {
  if (value === null || value === undefined || value === '') return fallback;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return fallback;
  try {
    return date.toLocaleString();
  } catch {
    return fallback;
  }
}

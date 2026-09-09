/**
 * localStorage access that never throws (private mode can raise
 * SecurityError). Called by AnalyticsPage for the persisted range;
 * every other UI state lives in react-query or the URL.
 */

/** Read a string value; null when storage is unavailable or the key is missing. */
export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

/** Write a string value; silently skips when storage is unavailable. */
export function storageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // ignore: the setting simply does not persist in this browser
  }
}

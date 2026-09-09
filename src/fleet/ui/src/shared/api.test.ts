/**
 * Unit tests for shared/api.ts: qs building, ApiError body parsing and
 * the 401 notification behind TokenGate (fetch is stubbed per test).
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, isNotFound, onAuthRequired, qs } from './api';

function stubFetch(status: number, body: string): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(body, { status, headers: { 'Content-Type': 'application/json' } }),
    ),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('qs', () => {
  it('builds an encoded query string', () => {
    expect(qs({ days: 7 })).toBe('?days=7');
    expect(qs({ query: 'a b&c', level: 'info' })).toBe('?query=a%20b%26c&level=info');
  });

  it('skips empty params and returns empty string when all are empty', () => {
    expect(qs({ offset: 0, limit: undefined, kind: null, q: '' })).toBe('?offset=0');
    expect(qs({ level: undefined })).toBe('');
    expect(qs({})).toBe('');
  });
});

describe('request error bodies', () => {
  it('parses {error} from the body into ApiError', async () => {
    stubFetch(500, JSON.stringify({ error: 'boom' }));
    const err = await api.getTasks().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(500);
    expect((err as ApiError).message).toBe('boom');
  });

  it('parses {detail} from the body into ApiError', async () => {
    stubFetch(404, JSON.stringify({ detail: 'task gone' }));
    const err = await api.getTask('x').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe('task gone');
    expect(isNotFound(err)).toBe(true);
    expect(isNotFound(new Error('nope'))).toBe(false);
  });

  it('falls back to METHOD path → status for non-JSON bodies', async () => {
    stubFetch(503, 'bad gateway');
    const err = await api.getTasks().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe('GET /api/tasks → 503');
  });

  it('notifies auth listeners on 401 instead of prompting', async () => {
    stubFetch(401, JSON.stringify({ detail: 'unauthorized' }));
    const listener = vi.fn();
    const unsubscribe = onAuthRequired(listener);
    const err = await api.getTasks().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(401);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
  });
});

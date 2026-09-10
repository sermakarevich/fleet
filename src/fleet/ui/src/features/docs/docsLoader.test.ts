// docsLoader: every manifest page resolves to a non-empty bundled body.
import { describe, expect, it } from 'vitest';
import { findDoc, loadDocs } from './docsLoader';

describe('docsLoader', () => {
  it('gives every manifest page a non-empty body', () => {
    const pages = loadDocs();
    expect(pages.length).toBeGreaterThan(0);
    for (const p of pages) {
      expect(p.slug.length).toBeGreaterThan(0);
      expect(p.body.trim().length, p.slug).toBeGreaterThan(0);
    }
  });

  it('finds pages by slug and misses unknown slugs', () => {
    expect(findDoc('overview')?.title).toBe('Overview');
    expect(findDoc('no-such-page')).toBeUndefined();
  });
});

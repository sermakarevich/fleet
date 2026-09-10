// resolveDocHref: external/anchor passthrough, .md resolution, rest kept.
import { describe, expect, it } from 'vitest';
import { resolveDocHref } from './docLinks';
import type { DocPage } from './docsLoader';

const pages: DocPage[] = [
  { slug: 'overview', title: 'Overview', section: 'Learn', file: 'docs/OVERVIEW.md', body: 'x' },
  { slug: 'concepts', title: 'Concepts', section: 'Learn', file: 'docs/guide/concepts.md', body: 'x' },
  { slug: 'getting-started', title: 'Getting started', section: 'Learn', file: 'docs/guide/getting-started.md', body: 'x' },
];

describe('resolveDocHref', () => {
  it('leaves https links unchanged', () => {
    expect(resolveDocHref('https://example.com/a.md', 'docs/guide/concepts.md', pages)).toBe(
      'https://example.com/a.md',
    );
  });

  it('leaves mailto and bare anchors unchanged', () => {
    expect(resolveDocHref('mailto:a@b.c', 'docs/guide/concepts.md', pages)).toBe('mailto:a@b.c');
    expect(resolveDocHref('#first-run-setup', 'docs/guide/concepts.md', pages)).toBe('#first-run-setup');
  });

  it('resolves a same-directory .md link to its slug', () => {
    expect(resolveDocHref('getting-started.md', 'docs/guide/concepts.md', pages)).toBe(
      '/docs/getting-started',
    );
  });

  it('resolves a parent-directory .md link to its slug', () => {
    expect(resolveDocHref('../OVERVIEW.md', 'docs/guide/concepts.md', pages)).toBe('/docs/overview');
  });

  it('keeps the #anchor when resolving a .md link', () => {
    expect(resolveDocHref('getting-started.md#quick-start', 'docs/guide/concepts.md', pages)).toBe(
      '/docs/getting-started#quick-start',
    );
  });

  it('leaves images and unknown .md targets unchanged', () => {
    expect(resolveDocHref('../../assets/x.png', 'docs/guide/concepts.md', pages)).toBe(
      '../../assets/x.png',
    );
    expect(resolveDocHref('missing.md', 'docs/guide/concepts.md', pages)).toBe('missing.md');
  });
});

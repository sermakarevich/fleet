// DocPager: ends of the walk, ADR details skipped for guide readers but
// kept when the current page is itself an ADR.
import { describe, expect, it, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DocPager, pagerOf } from './DocPager';
import type { DocPage } from './docsLoader';

const pages: DocPage[] = [
  { slug: 'overview', title: 'Overview', section: 'Learn', file: 'docs/OVERVIEW.md', body: 'x' },
  { slug: 'commands', title: 'Command reference', section: 'Reference', file: 'docs/guide/commands.md', body: 'x' },
  { slug: 'adr', title: 'Decisions (ADRs)', section: 'Internals', file: 'docs/adr/README.md', body: 'x' },
  { slug: 'adr-0001', title: 'ADR 0001', section: 'Internals', file: 'docs/adr/0001.md', body: 'x' },
  { slug: 'adr-0002', title: 'ADR 0002', section: 'Internals', file: 'docs/adr/0002.md', body: 'x' },
];

function renderPager(slug: string): void {
  render(
    <MemoryRouter>
      <DocPager pages={pages} slug={slug} />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe('pagerOf', () => {
  it('first page has no Previous', () => {
    expect(pagerOf(pages, 'overview').prev).toBeUndefined();
    expect(pagerOf(pages, 'overview').next?.slug).toBe('commands');
  });

  it('last walk page has no Next', () => {
    expect(pagerOf(pages, 'adr').next).toBeUndefined();
    expect(pagerOf(pages, 'adr').prev?.slug).toBe('commands');
  });

  it('skips ADR detail pages for guide readers', () => {
    expect(pagerOf(pages, 'commands').next?.slug).toBe('adr');
  });

  it('keeps ADR neighbours on ADR pages', () => {
    expect(pagerOf(pages, 'adr-0001').prev?.slug).toBe('adr');
    expect(pagerOf(pages, 'adr-0001').next?.slug).toBe('adr-0002');
  });
});

describe('DocPager', () => {
  it('renders both links mid-walk', () => {
    renderPager('commands');
    expect(screen.getByRole('link', { name: /Previous: Overview/ })).toHaveAttribute(
      'href',
      '/docs/overview',
    );
    expect(screen.getByRole('link', { name: /Next: Decisions/ })).toHaveAttribute('href', '/docs/adr');
  });

  it('renders no Previous on the first page', () => {
    renderPager('overview');
    expect(screen.queryByRole('link', { name: /Previous/ })).toBeNull();
    expect(screen.getByRole('link', { name: /Next/ })).toBeInTheDocument();
  });
});

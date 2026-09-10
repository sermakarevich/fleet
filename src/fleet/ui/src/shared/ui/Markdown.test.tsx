// Markdown: heading ids, external links in a new tab, internal links via
// resolveHref rendered as router links.
import { describe, expect, it, afterEach } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { Markdown } from './Markdown';

function renderMd(source: string, resolveHref?: (href: string) => string): void {
  render(
    <MemoryRouter>
      <Markdown source={source} resolveHref={resolveHref} />
    </MemoryRouter>,
  );
}

afterEach(cleanup);

describe('Markdown', () => {
  it('gives headings slugified ids', () => {
    renderMd('## Hello World!\n\n### Quick Start\n');
    expect(document.getElementById('hello-world')?.tagName).toBe('H2');
    expect(document.getElementById('quick-start')?.tagName).toBe('H3');
  });

  it('opens external links in a new tab', () => {
    renderMd('[site](https://example.com)\n');
    const link = screen.getByRole('link', { name: 'site' });
    expect(link).toHaveAttribute('href', 'https://example.com');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('resolves internal links through resolveHref', () => {
    renderMd('[start](getting-started.md)', () => '/docs/getting-started#quick-start');
    expect(screen.getByRole('link', { name: 'start' })).toHaveAttribute(
      'href',
      '/docs/getting-started#quick-start',
    );
  });
});

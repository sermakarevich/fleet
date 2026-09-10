// DocsPage: default overview, command reference, empty state, internal
// .md links rewritten to /docs routes, sidebar filter hides non-matches.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { DocsPage } from './DocsPage';

afterEach(cleanup);

beforeEach(() => {
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }) as unknown as typeof window.matchMedia;
});

function renderAt(path: string): void {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/docs/:slug" element={<DocsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('DocsPage', () => {
  it('renders Overview by default', () => {
    renderAt('/docs');
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument();
  });

  it('shows the Command reference heading for /docs/commands', () => {
    renderAt('/docs/commands');
    expect(screen.getAllByRole('heading', { name: 'Command reference' }).length).toBeGreaterThan(0);
  });

  it('shows the empty state for an unknown slug', () => {
    renderAt('/docs/no-such-page');
    expect(screen.getByText(/No page called no-such-page/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Back to Docs/ })).toHaveAttribute('href', '/docs');
  });

  it('renders a relative .md link as a /docs route', () => {
    renderAt('/docs/commands');
    expect(screen.getByRole('link', { name: 'Quick start' })).toHaveAttribute(
      'href',
      '/docs/getting-started#quick-start',
    );
  });

  it('filter input hides non-matching pages', () => {
    renderAt('/docs');
    fireEvent.change(screen.getByPlaceholderText('Filter pages…'), { target: { value: 'telegram' } });
    expect(screen.getByRole('link', { name: 'Telegram' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Overview' })).toBeNull();
  });
});

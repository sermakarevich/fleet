// Tests for the Bead tab (ADR 0017 U3): dependencies with worker links
// and blocked notes, the children list with its digest, comments, and the
// raw JSON payload with its copy button.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { api } from '../../../../shared/api';
import type { BeadDetail } from '../../../../shared/types';
import { BeadTab } from './BeadTab';

afterEach(cleanup);
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

function makeBead(partial?: Partial<BeadDetail>): BeadDetail {
  return {
    id: 'w1',
    title: 'worker one',
    status: 'blocked',
    priority: 2,
    issue_type: 'bug',
    assignee: 'coder-a',
    description: 'does things',
    notes: 'blocked on dep-1',
    created_at: '2026-09-09T10:00:00Z',
    updated_at: '2026-09-09T11:00:00Z',
    closed_at: null,
    close_reason: null,
    dependencies: [
      { id: 'dep-1', title: 'Dep one', status: 'open', dependency_type: 'blocks' },
      { id: 'dep-2', title: 'Dep two', status: 'closed', dependency_type: null },
    ],
    comments: [{ id: 1, author: 'alice', text: 'first comment', created_at: '2026-09-09T10:30:00Z' }],
    ...partial,
  } as BeadDetail;
}

describe('BeadTab', () => {
  it('renders dependencies with links, blocked notes, children, comments and raw JSON', async () => {
    vi.spyOn(api, 'getTaskChildren').mockResolvedValue({
      children: [
        {
          id: 'c1',
          title: 'Child one',
          status: 'open',
          result_status: 'done',
          result_summary: 'did stuff',
        },
      ],
      children_md: 'digest text',
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });

    render(<BeadTab taskId="w1" bead={makeBead()} />, { wrapper });

    // Dependencies section with worker links and blocked notes.
    expect(await screen.findByRole('heading', { name: 'Dependencies' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Why blocked' })).toBeInTheDocument();
    expect(screen.getByText('blocked on dep-1')).toBeInTheDocument();
    const depLinks = screen.getAllByRole('link', { name: 'dep-1' });
    expect(depLinks.length).toBeGreaterThanOrEqual(1);
    expect(depLinks[0].getAttribute('href')).toBe('/workers/dep-1');

    // Children section with links and the digest.
    expect(await screen.findByText('did stuff')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'c1' }).getAttribute('href')).toBe('/workers/c1');
    expect(screen.getByText('digest text')).toBeInTheDocument();

    // Comments section.
    expect(screen.getByRole('heading', { name: 'Comments' })).toBeInTheDocument();
    expect(screen.getByText('first comment')).toBeInTheDocument();

    // Raw section: collapsed details with pretty-printed payload and copy.
    expect(screen.getByRole('heading', { name: 'Raw' })).toBeInTheDocument();
    expect(screen.getByText('Bead JSON')).toBeInTheDocument();
    expect(screen.getByText(/"issue_type": "bug"/).tagName).toBe('PRE');
    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledTimes(1);
  });

  it('shows "No comments." when the thread is empty', async () => {
    vi.spyOn(api, 'getTaskChildren').mockResolvedValue({ children: [], children_md: null });
    render(<BeadTab taskId="w1" bead={makeBead({ comments: [] })} />, { wrapper });

    expect(await screen.findByText('No comments.')).toBeInTheDocument();
  });

  it('shows its own error text when the children fetch fails', async () => {
    vi.spyOn(api, 'getTaskChildren').mockRejectedValue(new Error('children down'));
    render(<BeadTab taskId="w1" bead={makeBead()} />, { wrapper });

    expect(await screen.findByText('Children failed to load: children down')).toBeInTheDocument();
    // The rest of the tab still renders.
    expect(screen.getByRole('heading', { name: 'Dependencies' })).toBeInTheDocument();
    expect(screen.getByText('first comment')).toBeInTheDocument();
  });

  it('surfaces a clipboard failure as an inline message', async () => {
    vi.spyOn(api, 'getTaskChildren').mockResolvedValue({ children: [], children_md: null });
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    render(<BeadTab taskId="w1" bead={makeBead()} />, { wrapper });

    fireEvent.click(await screen.findByRole('button', { name: 'Copy' }));
    expect(await screen.findByText('Copy failed: denied')).toBeInTheDocument();
  });
});

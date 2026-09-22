/**
 * Tests for ShortlistTab: candidates.json (research worker, ADR 0015)
 * filtered to shortlist/reserve/in_kb, ranked by relevance, title link.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { api, ApiError } from '../../../../shared/api';
import { ShortlistTab } from './ShortlistTab';

afterEach(cleanup);
afterEach(() => vi.restoreAllMocks());

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function candidatesDoc(candidates: unknown[]): { content: string; mtime: number; path: string } {
  return { content: JSON.stringify({ candidates }), mtime: 0, path: '' };
}

describe('ShortlistTab', () => {
  it('renders shortlist/reserve/in_kb rows ranked by relevance, excludes rejected', async () => {
    vi.spyOn(api, 'getArtifactCandidates').mockResolvedValue(
      candidatesDoc([
        {
          url: 'https://b.example',
          title: 'Low score',
          kind: 'paper',
          status: 'shortlist',
          subtopic: 'topic-b',
          scores: { relevance: 0.3 },
        },
        {
          url: 'https://a.example',
          title: 'High score',
          kind: 'paper',
          status: 'shortlist',
          subtopic: 'topic-a',
          scores: { relevance: 0.9 },
        },
        {
          url: 'https://c.example',
          title: 'Rejected candidate',
          kind: 'opinion',
          status: 'rejected',
          subtopic: 'topic-c',
          scores: { relevance: 0.99 },
        },
      ])
    );

    render(<ShortlistTab taskId="t1" />, { wrapper });

    const high = await screen.findByText('High score');
    const low = await screen.findByText('Low score');
    expect(high).toBeInTheDocument();
    expect(low).toBeInTheDocument();
    expect(screen.queryByText('Rejected candidate')).not.toBeInTheDocument();
    expect(high.getAttribute('href')).toBe('https://a.example');

    const links = screen.getAllByRole('link');
    expect(links[0].textContent).toBe('High score');
    expect(links[1].textContent).toBe('Low score');
  });

  it('shows an empty state when candidates.json is missing (404)', async () => {
    vi.spyOn(api, 'getArtifactCandidates').mockRejectedValue(new ApiError(404, 'not found'));

    render(<ShortlistTab taskId="t2" />, { wrapper });

    expect(await screen.findByText('candidates.json not available')).toBeInTheDocument();
  });
});

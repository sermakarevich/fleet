/**
 * Unit tests for the beads filter hook (state, URL sync, pagination).
 */
import { describe, expect, it } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';
import { useBeadFilters } from './useBeadFilters';
import type { Bead } from '../../shared/types';

function bead(id: string, status: string, title = `title ${id}`): Bead {
  return {
    id, title, status, priority: null, issue_type: null, assignee: null,
    created_at: null, updated_at: null, closed_at: null,
    dependency_count: null, dependent_count: null, comment_count: null,
  };
}

const BEADS = [bead('a', 'open'), bead('b', 'in_progress'), bead('c', 'blocked')];

function wrapper({ children }: { children: ReactNode }) {
  return <MemoryRouter initialEntries={['/bd']}>{children}</MemoryRouter>;
}

describe('useBeadFilters', () => {
  it('defaults to the in_progress filter', () => {
    const { result } = renderHook(() => useBeadFilters(BEADS), { wrapper });
    expect(result.current.statusFilter).toBe('in_progress');
    expect(result.current.pageItems.map((b) => b.id)).toEqual(['b']);
  });

  it('switches the status filter', () => {
    const { result } = renderHook(() => useBeadFilters(BEADS), { wrapper });
    act(() => result.current.setStatusFilter('all'));
    expect(result.current.sorted.map((b) => b.id).sort()).toEqual(['a', 'b', 'c']);
  });

  it('filters by search query across id, title and assignee', () => {
    const { result } = renderHook(() => useBeadFilters(BEADS), { wrapper });
    act(() => result.current.setStatusFilter('all'));
    act(() => result.current.setSearchQuery('title b'));
    expect(result.current.pageItems.map((b) => b.id)).toEqual(['b']);
  });

  it('paginates to a single page for few beads', () => {
    const { result } = renderHook(() => useBeadFilters(BEADS), { wrapper });
    act(() => result.current.setStatusFilter('all'));
    expect(result.current.totalPages).toBe(1);
    expect(result.current.page).toBe(0);
  });
});

// Render tests for the shared FilterBar: search input and filter
// buttons round-trip through the URL via useUrlFilters, and alert
// dots mark filters with waiting items.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useSearchParams } from 'react-router-dom';
import { FilterBar } from './FilterBar';
import { useUrlFilters } from '../hooks/useUrlFilters';

afterEach(cleanup);

const VALID = ['all', 'blocked', 'done'] as const;
type Status = (typeof VALID)[number];

const OPTIONS = [
  { key: 'all' as Status, label: 'All' },
  { key: 'blocked' as Status, label: 'Blocked', alertCount: 2 },
  { key: 'done' as Status, label: 'Done', count: 5 },
];

// Probe wiring FilterBar to useUrlFilters, plus the raw query string.
function Probe() {
  const filters = useUrlFilters<Status>({ valid: VALID, defaultStatus: 'all' });
  const [params] = useSearchParams();
  return (
    <>
      <FilterBar
        searchQuery={filters.searchQuery}
        onSearchQuery={filters.setSearchQuery}
        filters={OPTIONS}
        active={filters.status}
        onSelect={filters.setStatus}
      />
      <div data-testid="query">{params.toString()}</div>
      <div data-testid="page">{filters.page}</div>
    </>
  );
}

function renderProbe(initial = '/list') {
  render(
    <MemoryRouter initialEntries={[initial]}>
      <Probe />
    </MemoryRouter>,
  );
}

describe('FilterBar', () => {
  it('reads the initial state from the URL', () => {
    renderProbe('/list?q=hello&status=blocked&page=2');
    expect(screen.getByPlaceholderText('Search…')).toHaveValue('hello');
    expect(screen.getByTestId('page')).toHaveTextContent('2');
  });

  it('writes the status filter to the URL and resets the page', () => {
    renderProbe('/list?page=3');
    fireEvent.click(screen.getByRole('button', { name: /Blocked/ }));
    expect(screen.getByTestId('query')).toHaveTextContent('status=blocked');
    expect(screen.getByTestId('page')).toHaveTextContent('0');
  });

  it('writes the search query to the URL', () => {
    renderProbe('/list');
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'triage' } });
    expect(screen.getByTestId('query')).toHaveTextContent('q=triage');
  });

  it('shows alert dots and counts', () => {
    renderProbe('/list');
    expect(screen.getByText('Blocked').parentElement?.innerHTML).toContain('span');
    expect(screen.getByText('5')).toBeInTheDocument();
  });
});

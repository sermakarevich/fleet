/**
 * Tests for the legacy /bd redirect: every bd status value maps onto
 * the workers filter vocabulary, unknown or missing values land on the
 * default workers filter.
 */
import { describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { BdRedirect } from './App';

afterEach(cleanup);

function WorkersMarker() {
  const location = useLocation();
  return <div data-testid="workers">{location.pathname}{location.search}</div>;
}

function renderBd(entry: string) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path="/bd" element={children} />
          <Route path="/workers" element={<WorkersMarker />} />
        </Routes>
      </MemoryRouter>
    );
  }
  render(<BdRedirect />, { wrapper: Wrapper });
  return screen.findByTestId('workers');
}

describe('BdRedirect', () => {
  it.each([
    ['/bd?status=open', '/workers?status=queued'],
    ['/bd?status=in_progress', '/workers?status=running'],
    ['/bd?status=blocked', '/workers?status=blocked'],
    ['/bd?status=closed', '/workers?status=done'],
  ])('maps %s to %s', async (entry, expected) => {
    expect((await renderBd(entry)).textContent).toBe(expected);
  });

  it('lands on the default filter without a status', async () => {
    expect((await renderBd('/bd')).textContent).toBe('/workers');
  });

  it('lands on the default filter for unknown statuses', async () => {
    expect((await renderBd('/bd?status=deferred')).textContent).toBe('/workers');
  });
});

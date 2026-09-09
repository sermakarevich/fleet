/**
 * Unit tests for the legacy schedule-route redirects: /schedules and
 * /recurring land on the matching Scheduled sub-tab, and
 * /recurring/:id opens the schedule drawer there.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { RecurringIdRedirect, ScheduleIdRedirect } from '../../app/App';

afterEach(cleanup);

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}{location.search}</div>;
}

function wrapper(initialEntries: string[]) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={initialEntries}>
        {children}
        <LocationProbe />
      </MemoryRouter>
    );
  };
}

describe('schedule redirects', () => {
  it('redirects /schedules/:id into the workers Scheduled sub-tab', async () => {
    render(
      <Routes>
        <Route path="/schedules/:id" element={<ScheduleIdRedirect />} />
        <Route path="/workers" element={<div>workers marker</div>} />
      </Routes>,
      { wrapper: wrapper(['/schedules/sched-1']) },
    );
    expect(await screen.findByText('workers marker')).toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toBe(
      '/workers?tab=scheduled&schedule=sched-1',
    );
  });

  it('redirects /recurring/:id into the workflows Scheduled sub-tab', async () => {
    render(
      <Routes>
        <Route path="/recurring/:id" element={<RecurringIdRedirect />} />
        <Route path="/workflows" element={<div>workflows marker</div>} />
      </Routes>,
      { wrapper: wrapper(['/recurring/sched-9']) },
    );
    expect(await screen.findByText('workflows marker')).toBeInTheDocument();
    expect(screen.getByTestId('location').textContent).toBe(
      '/workflows?tab=scheduled&schedule=sched-9',
    );
  });
});

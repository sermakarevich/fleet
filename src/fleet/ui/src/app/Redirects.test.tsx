// Every legacy redirect component in the App route table
// (ADR 0009 UI 2-7): each one lands on a live four-tab route.
// (BdRedirect has its own test file; plain <Navigate> routes have no
// logic to test.) Rendered nowhere; each redirect component is mounted
// directly under its legacy path.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import {
  AnalyticsRedirect,
  ChatRedirect,
  ConfigRedirect,
  RecurringIdRedirect,
  ScheduleIdRedirect,
  TaskIdRedirect,
} from './App';

afterEach(cleanup);

function Marker() {
  const location = useLocation();
  return <div data-testid="loc">{location.pathname}{location.search}</div>;
}

async function renderRedirect(entry: string, legacyPath: string, element: ReactNode) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <MemoryRouter initialEntries={[entry]}>
        <Routes>
          <Route path={legacyPath} element={children} />
          <Route path="/workers" element={<Marker />} />
          <Route path="/workers/:id" element={<Marker />} />
          <Route path="/workflows" element={<Marker />} />
          <Route path="/inbox" element={<Marker />} />
          <Route path="/settings" element={<Marker />} />
        </Routes>
      </MemoryRouter>
    );
  }
  render(element, { wrapper: Wrapper });
  return (await screen.findByTestId('loc')).textContent;
}

describe('legacy redirect components', () => {
  it.each([
    ['/tasks/fleet-abc', '/tasks/:id', '/workers/fleet-abc', <TaskIdRedirect />],
    ['/schedules/s1', '/schedules/:id', '/workers?tab=scheduled&schedule=s1', <ScheduleIdRedirect />],
    ['/recurring/r1', '/recurring/:id', '/workflows?tab=scheduled&schedule=r1', <RecurringIdRedirect />],
    ['/chat', '/chat', '/inbox', <ChatRedirect />],
    ['/config', '/config', '/settings', <ConfigRedirect />],
    ['/analytics', '/analytics', '/workers', <AnalyticsRedirect />],
  ])('%s resolves to %s', async (entry, legacyPath, expected, element) => {
    expect(await renderRedirect(entry, legacyPath as string, element)).toBe(expected);
  });
});

/**
 * Tests for the shared Tabs strip: tablist semantics, click selection,
 * and arrow-key / Home / End navigation.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { useState } from 'react';
import { Tabs } from './Tabs';

const DEFS = [
  { id: 'live', label: 'Live' },
  { id: 'log', label: 'Log' },
  { id: 'files', label: 'Files' },
];

function show() {
  const onTabChange = vi.fn();
  function Harness() {
    const [active, setActive] = useState('live');
    return (
      <Tabs
        tabs={DEFS}
        activeTab={active}
        label="Views"
        onTabChange={(id) => {
          setActive(id);
          onTabChange(id);
        }}
      >
        <p>Panel for {active}</p>
      </Tabs>
    );
  }
  return { ...render(<Harness />), onTabChange };
}

describe('Tabs', () => {
  it('exposes tablist/tab/tabpanel semantics', () => {
    const { getByRole, unmount } = show();
    expect(getByRole('tablist', { name: 'Views' })).toBeInTheDocument();
    expect(getByRole('tab', { name: 'Live' })).toHaveAttribute('aria-selected', 'true');
    expect(getByRole('tab', { name: 'Log' })).toHaveAttribute('aria-selected', 'false');
    expect(getByRole('tabpanel')).toHaveTextContent('Panel for live');
    unmount();
  });

  it('selects a tab on click', () => {
    const { getByRole, onTabChange, unmount } = show();
    fireEvent.click(getByRole('tab', { name: 'Log' }));
    expect(onTabChange).toHaveBeenCalledWith('log');
    expect(getByRole('tab', { name: 'Log' })).toHaveAttribute('aria-selected', 'true');
    unmount();
  });

  it('moves with arrow keys and wraps around', () => {
    const { getByRole, onTabChange, unmount } = show();
    fireEvent.keyDown(getByRole('tab', { name: 'Live' }), { key: 'ArrowRight' });
    expect(onTabChange).toHaveBeenCalledWith('log');
    fireEvent.keyDown(getByRole('tab', { name: 'Log' }), { key: 'ArrowLeft' });
    expect(onTabChange).toHaveBeenCalledWith('live');
    fireEvent.keyDown(getByRole('tab', { name: 'Live' }), { key: 'ArrowLeft' });
    expect(onTabChange).toHaveBeenCalledWith('files');
    unmount();
  });

  it('jumps with Home and End', () => {
    const { getByRole, onTabChange, unmount } = show();
    fireEvent.keyDown(getByRole('tab', { name: 'Live' }), { key: 'End' });
    expect(onTabChange).toHaveBeenCalledWith('files');
    fireEvent.keyDown(getByRole('tab', { name: 'Files' }), { key: 'Home' });
    expect(onTabChange).toHaveBeenCalledWith('live');
    unmount();
  });

  it('renders count after label when given', () => {
    const { getByRole, unmount } = render(
      <Tabs
        tabs={[
          { id: 'runs', label: 'Runs', count: 300 },
          { id: 'scheduled', label: 'Scheduled' },
        ]}
        activeTab="runs"
        label="Views"
        onTabChange={() => undefined}
      >
        <p>Panel</p>
      </Tabs>,
    );
    expect(getByRole('tab', { name: /Runs/ })).toHaveTextContent('300');
    expect(getByRole('tab', { name: 'Scheduled' })).not.toHaveTextContent(/[0-9]/);
    unmount();
  });

  it('active tab has aria-selected and accent underline style', () => {
    const { getByRole, unmount } = show();
    const active = getByRole('tab', { name: 'Live' });
    expect(active).toHaveAttribute('aria-selected', 'true');
    // jsdom serializes colours to rgb(): this is T.colors.accent.
    expect(active.style.borderBottomColor).toBe('rgb(59, 130, 246)');
    unmount();
  });
});

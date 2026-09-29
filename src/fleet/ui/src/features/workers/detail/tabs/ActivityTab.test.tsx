// Tests for the Activity tab (ADR 0017): attempt dividers, filter chips,
// row expansion to raw JSON, the stderr panel, and the error+Retry state.
import { describe, expect, it, vi, afterEach } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import type { ActivityItem } from '../../../../shared/types';
import type { ActivityState } from '../useActivity';
import { ActivityTab } from './ActivityTab';

afterEach(cleanup);

function makeItem(seq: number, partial?: Partial<ActivityItem>): ActivityItem {
  return {
    seq,
    ts: '2026-09-29T10:00:00Z',
    attempt: 1,
    source: 'event',
    kind: 'assistant_text',
    tool_name: null,
    usage: null,
    summary: `row ${seq}`,
    raw: { seq },
    ...partial,
  } as ActivityItem;
}

function makeFeed(partial?: Partial<ActivityState>): ActivityState {
  return {
    items: [],
    stderr: null,
    latestAttempt: 1,
    hasEarlier: false,
    error: null,
    loading: false,
    lastUpdated: null,
    loadEarlier: vi.fn(),
    retry: vi.fn(),
    ...partial,
  };
}

const ITEMS = [
  makeItem(0, { kind: 'assistant_text', summary: 'hello world', raw: { text: 'hi' } }),
  makeItem(1, { kind: 'tool_use', tool_name: 'Bash', summary: 'ran ls', raw: { input: { cmd: 'ls' } } }),
  makeItem(2, {
    attempt: 2,
    kind: 'tool_result',
    summary: 'ls output',
    raw: { part: { state: { output: 'file.txt' } } },
  }),
  makeItem(3, { attempt: 2, source: 'log', kind: 'error', summary: 'fleet hiccup', raw: {} }),
];

describe('ActivityTab', () => {
  it('renders attempt dividers when the attempt changes', () => {
    render(<ActivityTab taskId="t1" status="closed" feed={makeFeed({ items: ITEMS, latestAttempt: 2 })} />);
    expect(screen.getAllByText('Attempt 1')).toHaveLength(1);
    expect(screen.getAllByText('Attempt 2')).toHaveLength(1);
  });

  it('filters rows by chip', () => {
    render(<ActivityTab taskId="t1" status="closed" feed={makeFeed({ items: ITEMS, latestAttempt: 2 })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Text' }));
    expect(screen.getByText('hello world')).toBeInTheDocument();
    expect(screen.queryByText('ran ls')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Tools' }));
    expect(screen.getByText('ran ls')).toBeInTheDocument();
    expect(screen.getByText('ls output')).toBeInTheDocument();
    expect(screen.queryByText('hello world')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Errors' }));
    expect(screen.getByText('fleet hiccup')).toBeInTheDocument();
    expect(screen.queryByText('ran ls')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Fleet log' }));
    expect(screen.getByText('fleet hiccup')).toBeInTheDocument();
    expect(screen.queryByText('hello world')).not.toBeInTheDocument();
  });

  it('expands a row to show the raw JSON', () => {
    render(<ActivityTab taskId="t1" status="closed" feed={makeFeed({ items: ITEMS, latestAttempt: 2 })} />);
    fireEvent.click(screen.getByText('ran ls'));
    expect(screen.getByText(/"cmd": "ls"/)).toBeInTheDocument();
  });

  it('shows tool_result output text above the JSON', () => {
    render(<ActivityTab taskId="t1" status="closed" feed={makeFeed({ items: ITEMS, latestAttempt: 2 })} />);
    fireEvent.click(screen.getByText('ls output'));
    expect(screen.getByText('file.txt')).toBeInTheDocument();
  });

  it('shows the stderr panel', () => {
    render(
      <ActivityTab
        taskId="t1"
        status="closed"
        feed={makeFeed({ items: ITEMS, latestAttempt: 2, stderr: { attempt: 2, lines: ['err-a', 'err-b'] } })}
      />,
    );
    expect(screen.getByText('stderr (attempt 2, last 40 lines)')).toBeInTheDocument();
    expect(screen.getByText(/err-a/)).toBeInTheDocument();
  });

  it('shows the error and Retry when error is set and items are empty', () => {
    const retry = vi.fn();
    render(<ActivityTab taskId="t1" status="closed" feed={makeFeed({ items: [], error: 'boom', retry })} />);
    expect(screen.getAllByText('boom').length).toBeGreaterThan(0);
    const retries = screen.getAllByRole('button', { name: 'Retry' });
    fireEvent.click(retries[0]);
    expect(retry).toHaveBeenCalledTimes(1);
  });
});

// Render tests for the shared EmptyState and LoadingState: one look
// each, with the caller's message.
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { EmptyState } from './EmptyState';
import { LoadingState } from './LoadingState';

afterEach(cleanup);

describe('EmptyState', () => {
  it('renders the caller message', () => {
    render(<EmptyState message="No tasks match this filter." />);
    expect(screen.getByText('No tasks match this filter.')).toBeInTheDocument();
  });
});

describe('LoadingState', () => {
  it('renders the default loading text', () => {
    render(<LoadingState />);
    expect(screen.getByText('Loading…')).toBeInTheDocument();
  });

  it('renders a custom loading message', () => {
    render(<LoadingState message="Loading analytics…" />);
    expect(screen.getByText('Loading analytics…')).toBeInTheDocument();
  });
});

// Render tests for the shared Confirm: one wording ("<Verb>?" with
// Confirm / Cancel) and no action without an explicit click.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Confirm } from './Confirm';

afterEach(cleanup);

describe('Confirm', () => {
  it('renders the verb question with Confirm and Cancel', () => {
    render(<Confirm verb="Delete" onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText('Delete?')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Confirm' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
  });

  it('confirms and cancels through the callbacks', () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<Confirm verb="Kill" onConfirm={onConfirm} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

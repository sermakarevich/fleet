/**
 * Tests for the shared Modal dialog: dialog semantics, Escape close,
 * overlay close, and focus trap with restore.
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { Modal } from './Modal';

function show(onClose: () => void = () => {}) {
  return render(
    <Modal labelledBy="dlg-title" onClose={onClose}>
      <h2 id="dlg-title">Dialog title</h2>
      <button>First</button>
      <button>Second</button>
    </Modal>,
  );
}

describe('Modal', () => {
  it('exposes dialog semantics', () => {
    const { getByRole, unmount } = show();
    const dialog = getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveAttribute('aria-labelledby', 'dlg-title');
    unmount();
  });

  it('moves focus to the first focusable element on open', () => {
    const { getByText, unmount } = show();
    expect(getByText('First')).toHaveFocus();
    unmount();
  });

  it('restores focus to the opener on close', () => {
    const { getByText, unmount } = show();
    expect(getByText('First')).toHaveFocus();
    unmount();
    expect(document.body).toHaveFocus();
  });

  it('closes on Escape', () => {
    const onClose = vi.fn();
    const { getByRole, unmount } = show(onClose);
    fireEvent.keyDown(getByRole('dialog'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('closes on overlay click but not on panel click', () => {
    const onClose = vi.fn();
    const { getByRole, getByText, unmount } = show(onClose);
    fireEvent.click(getByRole('dialog'));
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(getByText('Dialog title'));
    expect(onClose).not.toHaveBeenCalled();
    // Click the overlay itself (target === currentTarget).
    const overlay = getByRole('dialog').parentElement!;
    fireEvent.click(overlay);
    expect(onClose).toHaveBeenCalledTimes(1);
    unmount();
  });

  it('traps Tab inside the dialog', () => {
    const { getByText, getByRole, unmount } = show();
    const first = getByText('First');
    const second = getByText('Second');
    second.focus();
    fireEvent.keyDown(getByRole('dialog'), { key: 'Tab' });
    expect(first).toHaveFocus();
    fireEvent.keyDown(getByRole('dialog'), { key: 'Tab', shiftKey: true });
    expect(second).toHaveFocus();
    unmount();
  });
});

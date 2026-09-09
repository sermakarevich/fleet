/**
 * Tests for the shared Clickable primitive: button semantics and
 * activation by click, Enter and Space (and nothing else).
 */
import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { Clickable, useClickableProps } from './Clickable';

// One table row driven by the hook, as a real component so the
// rules-of-hooks lint passes.
function HookedRow({ onActivate }: { onActivate: () => void }) {
  return (
    <tr {...useClickableProps(onActivate)}>
      <td>row</td>
    </tr>
  );
}

function showRow(onActivate: () => void = () => {}) {
  return render(
    <table>
      <tbody>
        <HookedRow onActivate={onActivate} />
      </tbody>
    </table>,
  );
}

describe('Clickable', () => {
  it('exposes button semantics with keyboard focus', () => {
    const { getByRole, unmount } = render(<Clickable onActivate={() => {}}>Go</Clickable>);
    const el = getByRole('button', { name: 'Go' });
    expect(el).toHaveAttribute('tabindex', '0');
    unmount();
  });

  it('activates on click, Enter and Space', () => {
    const onActivate = vi.fn();
    const { getByRole, unmount } = render(<Clickable onActivate={onActivate}>Go</Clickable>);
    const el = getByRole('button', { name: 'Go' });
    fireEvent.click(el);
    fireEvent.keyDown(el, { key: 'Enter' });
    fireEvent.keyDown(el, { key: ' ' });
    expect(onActivate).toHaveBeenCalledTimes(3);
    unmount();
  });

  it('ignores other keys', () => {
    const onActivate = vi.fn();
    const { getByRole, unmount } = render(<Clickable onActivate={onActivate}>Go</Clickable>);
    fireEvent.keyDown(getByRole('button', { name: 'Go' }), { key: 'a' });
    expect(onActivate).not.toHaveBeenCalled();
    unmount();
  });

  it('hook props make a table row operable', () => {
    const onActivate = vi.fn();
    const { getByRole, unmount } = showRow(onActivate);
    const row = getByRole('button', { name: 'row' });
    fireEvent.keyDown(row, { key: 'Enter' });
    fireEvent.keyDown(row, { key: ' ' });
    expect(onActivate).toHaveBeenCalledTimes(2);
    unmount();
  });
});

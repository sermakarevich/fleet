/**
 * Unit tests for the shared StatusChip component.
 */
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import { StatusChip } from './StatusChip';
import * as T from '../styles/tokens';

describe('StatusChip', () => {
  it('renders the human label for a known status', () => {
    const { getByText } = render(<StatusChip status="in_progress" />);
    expect(getByText('In progress')).toBeInTheDocument();
  });

  it('renders the stopping overlay label', () => {
    const { getByText } = render(<StatusChip status="in_progress" stopping />);
    expect(getByText('Stopping…')).toBeInTheDocument();
  });

  it('applies the status background color', () => {
    const { getByText } = render(<StatusChip status="blocked" />);
    expect(getByText('Blocked')).toHaveStyle({ background: T.colors.amberDark });
  });
});

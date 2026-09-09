/**
 * Accessible modal dialog: the one overlay every dialog in the UI opens
 * through. Gives role="dialog" + aria-modal + labelled-by heading, moves
 * focus to the first focusable element on open (and restores it on close),
 * traps Tab inside the panel, closes on Escape and on overlay click.
 * Called by NewWorkerPanel, CommandPalette and TokenGate.
 */
import { useEffect, useRef } from 'react';

interface ModalProps {
  /** Id of the heading inside the panel that names this dialog. */
  labelledBy: string;
  /** Close the dialog (Escape key and overlay click call this). */
  onClose: () => void;
  /** Panel content; must contain the element with id `labelledBy`. */
  children: React.ReactNode;
  /** Centered dialog (default) or right-side drawer. */
  placement?: 'center' | 'right';
  /** Extra styles merged over the built-in panel (width, height). */
  panelStyle?: React.CSSProperties;
  /** Accessible name for the overlay region (defaults to "Close dialog"). */
  overlayLabel?: string;
}

// Elements that can receive keyboard focus, in tab order.
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), ' +
  'input:not([disabled]), select:not([disabled]), ' +
  '[tabindex]:not([tabindex="-1"])';

// First focusable element inside the dialog panel.
function firstFocusable(panel: HTMLElement): HTMLElement | null {
  return panel.querySelector<HTMLElement>(FOCUSABLE);
}

// Accessible modal dialog with focus trap, Escape and overlay close.
export function Modal({
  labelledBy,
  onClose,
  children,
  placement = 'center',
  panelStyle,
  overlayLabel = 'Close dialog',
}: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  // Latest onClose without re-running the mount effect when it changes
  // identity (re-running would steal focus back on every parent render).
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    firstFocusable(panelRef.current!)?.focus();
    return () => {
      previouslyFocused?.focus?.();
    };
  }, []);

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      closeRef.current();
      return;
    }
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE),
    ).filter((el) => !el.hasAttribute('disabled'));
    if (items.length === 0) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === e.currentTarget) closeRef.current();
  }

  const right = placement === 'right';
  return (
    // Overlay click is a mouse-only affordance on purpose: keyboard users
    // close with Escape and Tab is trapped inside the panel (see
    // handleKeyDown), so the overlay itself takes no tab stop or role.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      style={right ? styles.overlayRight : styles.overlayCenter}
      onClick={handleOverlayClick}
      onKeyDown={handleKeyDown}
      aria-label={overlayLabel}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        style={{ ...(right ? styles.panelRight : styles.panelCenter), ...panelStyle }}
      >
        {children}
      </div>
    </div>
  );
}

const styles = {
  overlayCenter: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.55)',
    zIndex: 2000,
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: '18vh',
  },
  overlayRight: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex',
    justifyContent: 'flex-end',
    zIndex: 900,
  },
  panelCenter: {
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  },
  panelRight: {
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
  },
};

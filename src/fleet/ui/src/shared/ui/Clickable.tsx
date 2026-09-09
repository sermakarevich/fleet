/**
 * Keyboard-operable clickable: the one way to make a non-button element
 * (row, card, table row, event line) activatable by mouse and keyboard.
 * useClickableProps gives role="button" + tabIndex + Enter/Space handling
 * to spread onto any element; Clickable is the same contract as a div.
 * Called by TaskRow, TaskCard, BeadRow, QuestionCard, EventsTab and
 * NeedsAttention instead of bare div onClick.
 */
interface ClickableProps {
  /** Run on click, Enter, or Space. */
  onActivate: () => void;
  /** Accessible name when the content alone does not name the action. */
  label?: string;
  /** aria-expanded for rows that expand/collapse detail. */
  expanded?: boolean;
  style?: React.CSSProperties;
  className?: string;
  children: React.ReactNode;
}

// Props that turn any element into a keyboard-operable button-like target.
export function useClickableProps(onActivate: () => void) {
  return {
    role: 'button' as const,
    tabIndex: 0,
    onClick: onActivate,
    onKeyDown: (e: React.KeyboardEvent) => {
      // Ignore keys bubbled up from inner controls (e.g. Enter on a button
      // inside a row): those controls handle the key themselves.
      if (e.target !== e.currentTarget) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onActivate();
      }
    },
  };
}

// Div that behaves like a button for mouse, touch and keyboard users.
export function Clickable({
  onActivate,
  label,
  expanded,
  style,
  className,
  children,
}: ClickableProps) {
  return (
    <div
      {...useClickableProps(onActivate)}
      aria-label={label}
      aria-expanded={expanded}
      style={style}
      className={className}
    >
      {children}
    </div>
  );
}

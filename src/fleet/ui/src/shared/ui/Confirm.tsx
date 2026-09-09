// Shared inline confirmation: one wording everywhere ("<Verb>?"
// with Confirm / Cancel). Rendered wherever a destructive action needs
// a second click: task kill, assignee removal, schedule/workflow delete.
// Replaces window.confirm and the per-row two-step button idioms.
import * as T from '../styles/tokens';
import * as R from '../styles/recipes';

interface ConfirmProps {
  /** Verb shown as "<verb>?", e.g. "Delete", "Kill", "Remove assignee". */
  verb: string;
  /** Runs the destructive action. */
  onConfirm: () => void;
  /** Aborts back to the trigger button. */
  onCancel: () => void;
  /** Danger styling for the Confirm button; defaults to true. */
  danger?: boolean;
}

export function Confirm({ verb, onConfirm, onCancel, danger = true }: ConfirmProps) {
  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }
  return (
    <span style={R.confirmStyle()}>
      <span style={R.confirmLabelStyle()}>{verb}?</span>
      <button
        style={danger ? R.confirmBtnStyle() : T.btnPrimary}
        onClick={(e) => { stop(e); onConfirm(); }}
      >
        Confirm
      </button>
      <button
        style={R.merge(T.btnGhost, { padding: '0.2rem 0.5rem', fontSize: '0.8125rem' })}
        onClick={(e) => { stop(e); onCancel(); }}
      >
        Cancel
      </button>
    </span>
  );
}

// Bead tab of the worker detail page: the raw bead JSON for debugging,
// pretty-printed with a copy button. Rendered by TaskDetailPage when
// the Bead tab is active.
import { useState } from 'react';
import type { BeadDetail } from '../../../../shared/types';
import * as T from '../../../../shared/styles/tokens';
import * as R from '../../../../shared/styles/recipes';
import { LoadingState } from '../../../../shared/ui/LoadingState';

interface Props {
  bead: BeadDetail | undefined;
  isLoading: boolean;
  error: unknown;
}

// Raw payload view: monospace pre plus clipboard copy with feedback.
export function BeadJsonTab({ bead, isLoading, error }: Props) {
  const [copied, setCopied] = useState(false);

  if (isLoading) return <LoadingState />;
  if (error) return <p style={R.errorMsgStyle()}>Bead detail failed to load.</p>;
  if (!bead) return <p style={R.dimStyle()}>No bead detail.</p>;

  async function copy() {
    try {
      await navigator.clipboard.writeText(JSON.stringify(bead, null, 2));
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div style={styles.wrap}>
      <div style={styles.bar}>
        <h3 style={styles.sectionTitle}>Bead JSON</h3>
        <button style={styles.copyBtn} onClick={() => void copy()}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre style={styles.pre}>{JSON.stringify(bead, null, 2)}</pre>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    padding: '1rem',
    overflowY: 'auto',
  },
  bar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    margin: 0,
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  copyBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  },
  pre: {
    margin: 0,
    padding: '0.625rem 0.75rem',
    background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.375rem',
    color: T.colors.textBody,
    fontSize: '0.75rem',
    fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: 1.5,
  },
};

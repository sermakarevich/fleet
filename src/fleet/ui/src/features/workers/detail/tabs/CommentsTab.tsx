// Comments tab of the worker detail page: the bead's comment thread,
// read-only (the API has no POST comment route). Rendered by
// TaskDetailPage when the Comments tab is active.
import type { BeadDetail } from '../../../../shared/types';
import * as T from '../../../../shared/styles/tokens';
import * as R from '../../../../shared/styles/recipes';
import { LoadingState } from '../../../../shared/ui/LoadingState';

interface Props {
  bead: BeadDetail | undefined;
  isLoading: boolean;
  error: unknown;
}

// Comment thread from the bead payload, newest last.
export function CommentsTab({ bead, isLoading, error }: Props) {
  if (isLoading) return <LoadingState />;
  if (error) return <p style={R.errorMsgStyle()}>Bead detail failed to load.</p>;
  if (!bead) return <p style={R.dimStyle()}>No bead detail.</p>;

  return (
    <div style={styles.wrap}>
      <h3 style={styles.sectionTitle}>Comments ({bead.comments.length})</h3>
      {bead.comments.length === 0 ? (
        <p style={R.dimStyle()}>No comments.</p>
      ) : (
        bead.comments.map((c, i) => (
          <div key={c.id ?? i} style={styles.comment}>
            <div style={styles.meta}>
              <span style={styles.author}>{c.author ?? 'unknown'}</span>
              {c.created_at && <span style={R.dimStyle()}>{c.created_at}</span>}
            </div>
            <div style={styles.text}>{c.text}</div>
          </div>
        ))
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    padding: '1rem',
    overflowY: 'auto',
  },
  sectionTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  comment: {
    padding: '0.5rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.25rem',
    fontSize: '0.75rem',
  },
  author: {
    color: T.colors.textSecondary,
    fontWeight: 600,
  },
  text: {
    color: T.colors.textBody,
    fontSize: '0.8125rem',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: 1.5,
  },
};

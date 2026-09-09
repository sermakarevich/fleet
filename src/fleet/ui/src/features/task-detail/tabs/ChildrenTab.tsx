import { useTaskChildren } from '../../../shared/hooks/useApi';
import { merge } from '../../../shared/styles/recipes';
import * as T from '../../../shared/styles/tokens';

interface Props {
  taskId: string;
}

// Children panel for epics (see workers/observe.py): one row per child
// bead (id, bead status, RESULT status) plus the observer's CHILDREN.md
// digest from the Artifacts area. Empty for non-epic tasks.
export function ChildrenTab({ taskId }: Props) {
  const { data, isLoading, error } = useTaskChildren(taskId);

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (error || !data) {
    return <p style={styles.msg}>Children not available.</p>;
  }

  if (data.children.length === 0) {
    return <p style={styles.msg}>No child beads.</p>;
  }

  return (
    <div style={styles.container}>
      <div style={styles.list}>
        {data.children.map(c => (
          <div key={c.id} style={styles.row}>
            <span style={styles.id}>{c.id}</span>
            <span style={styles.cell}>{c.status ?? '—'}</span>
            <span style={styles.cell}>{c.result_status ?? '—'}</span>
            <span style={merge(styles.cell, styles.summary)} title={c.result_summary ?? c.title ?? undefined}>
              {c.result_summary || c.title || '—'}
            </span>
          </div>
        ))}
      </div>
      {data.children_md && (
        <div style={styles.digest}>
          <div style={styles.digestLabel}>CHILDREN.md</div>
          <pre style={styles.pre}>{data.children_md}</pre>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflowY: 'auto',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.8rem',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    padding: '0.4rem 0.75rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
    color: T.colors.textPrimary,
  },
  id: {
    fontFamily: 'monospace',
    color: T.colors.link,
    whiteSpace: 'nowrap',
  },
  cell: {
    whiteSpace: 'nowrap',
    color: T.colors.textSecondary,
  },
  summary: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  digest: {
    padding: '0.5rem 0.75rem 1rem 0.75rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  digestLabel: {
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.75rem',
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    background: T.colors.bgDeeper,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '4px',
    padding: '0.5rem',
    margin: 0,
    color: T.colors.textBody,
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
  },
};

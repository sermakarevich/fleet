import { errorMessage, isNotFound } from '../../../../shared/api';
import { useShortlist } from '../../../../shared/hooks/useApi';
import * as T from '../../../../shared/styles/tokens';

interface Props {
  taskId: string;
}

// Research worker's scored shortlist tab (workers/research.py, ADR 0015):
// candidates.json rows whose status is shortlist/reserve/in_kb, ranked by
// relevance. Mirrors `fleet research <id>`'s Shortlist table.
export function ShortlistTab({ taskId }: Props) {
  const { rows, isLoading, isError, error } = useShortlist(taskId);

  if (isLoading || rows == null) {
    if (isError) {
      const text = !isNotFound(error) ? errorMessage(error) : 'candidates.json not available';
      return <p style={styles.msg}>{text}</p>;
    }
    return <p style={styles.msg}>Loading…</p>;
  }

  if (rows.length === 0) {
    return <p style={styles.msg}>No shortlisted candidates.</p>;
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.hRank}>#</span>
        <span style={styles.hStatus}>status</span>
        <span style={styles.hKind}>kind</span>
        <span style={styles.hScore}>score</span>
        <span style={styles.hSubtopic}>sub-topic</span>
        <span style={styles.hTitle}>title</span>
      </div>
      {rows.map(r => (
        <div key={`${r.rank}-${r.url}`} style={styles.row}>
          <span style={styles.rank}>{r.rank}</span>
          <span style={styles.status}>{r.status}</span>
          <span style={styles.kind}>{r.kind}</span>
          <span style={styles.score}>{r.score != null ? r.score.toFixed(2) : '-'}</span>
          <span style={styles.subtopic}>{r.subtopic}</span>
          <a
            href={r.url}
            target="_blank"
            rel="noreferrer"
            style={styles.title}
            title={r.url}
          >
            {r.title || r.url}
          </a>
        </div>
      ))}
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
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    padding: '0.4rem 0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    textTransform: 'uppercase',
  },
  hRank: { width: '1.5rem', textAlign: 'right' },
  hStatus: { width: '5rem' },
  hKind: { width: '5rem' },
  hScore: { width: '3rem', textAlign: 'right' },
  hSubtopic: { width: '7rem' },
  hTitle: { flex: 1 },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    padding: '0.4rem 0.75rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
    color: T.colors.textPrimary,
  },
  rank: { width: '1.5rem', textAlign: 'right', color: T.colors.textSecondary },
  status: { width: '5rem', color: T.colors.textSecondary, whiteSpace: 'nowrap' },
  kind: { width: '5rem', color: T.colors.textSecondary, whiteSpace: 'nowrap' },
  score: { width: '3rem', textAlign: 'right', color: T.colors.textSecondary },
  subtopic: {
    width: '7rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  title: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    color: T.colors.link,
  },
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
  },
};

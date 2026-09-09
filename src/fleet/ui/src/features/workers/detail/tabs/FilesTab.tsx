import { useQuery } from '@tanstack/react-query';
import { api } from '../../../../shared/api';
import { usePoll } from '../../../../shared/poll';
import type { FileOp } from '../../../../shared/types';
import * as T from '../../../../shared/styles/tokens';

interface Props {
  taskId: string;
  status?: string;
}

export function FilesTab({ taskId, status }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['task', taskId, 'files'],
    queryFn: () => api.getFiles(taskId),
    refetchInterval: usePoll('normal', !status || status === 'in_progress'),
  });

  const files: FileOp[] = data?.files ?? [];

  if (isLoading && !data) return <p style={styles.msg}>Loading…</p>;
  if (files.length === 0) return <p style={styles.msg}>No file operations recorded.</p>;

  return (
    <div style={styles.container}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.thPath}>Path</th>
            <th style={styles.thCount}>Read</th>
            <th style={styles.thCount}>Edit</th>
            <th style={styles.thCount}>Write</th>
          </tr>
        </thead>
        <tbody>
          {files.map(f => (
            <tr key={f.path} style={styles.row}>
              <td style={styles.tdPath}>{f.path}</td>
              <td style={styles.tdCount}>{f.read > 0 ? f.read : <span style={styles.zero}>—</span>}</td>
              <td style={styles.tdCount}>{f.edit > 0 ? f.edit : <span style={styles.zero}>—</span>}</td>
              <td style={styles.tdCount}>{f.write > 0 ? f.write : <span style={styles.zero}>—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.5rem',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  thPath: {
    textAlign: 'left',
    padding: '0.4rem 0.5rem',
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.7rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  thCount: {
    textAlign: 'right',
    padding: '0.4rem 0.75rem',
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.7rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  row: {
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  tdPath: {
    padding: '0.35rem 0.5rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 400,
  },
  tdCount: {
    padding: '0.35rem 0.75rem',
    textAlign: 'right',
    color: T.colors.textPrimary,
    fontWeight: 600,
  },
  zero: {
    color: T.colors.border,
  },
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
    margin: 0,
  },
};

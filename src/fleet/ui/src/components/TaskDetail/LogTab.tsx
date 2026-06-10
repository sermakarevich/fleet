import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import type { LogLine } from '../../types';

interface Props {
  taskId: string;
  status?: string;
}

const LEVELS = ['all', 'debug', 'info', 'warning', 'error'];

function levelColor(level: string): string {
  switch (level) {
    case 'error': return '#ef4444';
    case 'warning': return '#f59e0b';
    case 'info': return '#3b82f6';
    case 'debug': return '#71717a';
    default: return '#a1a1aa';
  }
}

export function LogTab({ taskId, status }: Props) {
  const [levelFilter, setLevelFilter] = useState('all');

  const { data, isLoading } = useQuery({
    queryKey: ['task', taskId, 'logs', levelFilter],
    queryFn: () => api.getLogs(taskId, levelFilter === 'all' ? undefined : levelFilter),
    refetchInterval: !status || status === 'in_progress' ? 5000 : false,
  });

  const lines: LogLine[] = data?.lines ?? [];

  function download() {
    const text = lines.map(l => `[${l.ts}] [${l.level}] ${l.message}`).join('\n');
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${taskId}-log.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <div style={styles.filters}>
          {LEVELS.map(l => (
            <button
              key={l}
              style={{ ...styles.chip, ...(levelFilter === l ? styles.chipActive : {}) }}
              onClick={() => setLevelFilter(l)}
            >
              {l}
            </button>
          ))}
        </div>
        <button style={styles.downloadBtn} onClick={download}>Download</button>
      </div>
      <div style={styles.list}>
        {isLoading && !data && <p style={styles.msg}>Loading…</p>}
        {!isLoading && lines.length === 0 && <p style={styles.msg}>No log entries.</p>}
        {lines.map((line, i) => (
          <div key={i} style={styles.row}>
            <span style={{ ...styles.level, color: levelColor(line.level) }}>{line.level}</span>
            <span style={styles.ts}>{line.ts.slice(0, 19).replace('T', ' ')}</span>
            <span style={styles.msg2}>{line.message}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0.4rem 0.75rem',
    borderBottom: '1px solid #27272a',
    background: '#18181b',
    gap: '0.5rem',
  },
  filters: {
    display: 'flex',
    gap: '0.25rem',
  },
  chip: {
    padding: '0.1rem 0.45rem',
    borderRadius: 9999,
    border: '1px solid #3f3f46',
    background: 'transparent',
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.7rem',
  },
  chipActive: {
    background: '#27272a',
    color: '#e4e4e7',
    borderColor: '#60a5fa',
  },
  downloadBtn: {
    padding: '0.2rem 0.6rem',
    borderRadius: 4,
    border: '1px solid #3f3f46',
    background: 'transparent',
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.7rem',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  row: {
    display: 'flex',
    gap: '0.5rem',
    alignItems: 'baseline',
    padding: '0.1rem 0.25rem',
    borderBottom: '1px solid #1c1c20',
  },
  level: {
    width: 56,
    flexShrink: 0,
    fontWeight: 600,
  },
  ts: {
    color: '#52525b',
    flexShrink: 0,
    width: 132,
  },
  msg2: {
    color: '#e4e4e7',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  msg: {
    padding: '0.5rem',
    color: '#71717a',
    margin: 0,
  },
};

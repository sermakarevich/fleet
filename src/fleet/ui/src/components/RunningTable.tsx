import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import type { TaskSummary } from '../types';
import { Sparkline } from './Sparkline';
import { StatusDot } from './StatusDot';

function formatElapsed(sec: number | null): string {
  if (sec == null) return '—';
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatTokens(n: number | null): string {
  if (n == null) return '—';
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

function formatRelative(iso: string | null): string {
  if (!iso) return '—';
  const diffSec = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diffSec < 60) return `${Math.floor(diffSec)}s ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  return `${Math.floor(diffSec / 3600)}h ago`;
}

interface ContextMenuState {
  task: TaskSummary;
  x: number;
  y: number;
}

interface Props {
  tasks: TaskSummary[];
  thresholdPct?: number;
}

export function RunningTable({ tasks, thresholdPct = 90 }: Props) {
  const navigate = useNavigate();
  const [menu, setMenu] = useState<ContextMenuState | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    function onClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenu(null);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setMenu(null);
    }
    document.addEventListener('mousedown', onClickOutside);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onClickOutside);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [menu]);

  if (tasks.length === 0) {
    return (
      <section style={styles.section}>
        <h2 style={styles.title}>Running ({tasks.length})</h2>
        <p style={styles.empty}>No running tasks</p>
      </section>
    );
  }

  return (
    <section style={styles.section}>
      <h2 style={styles.title}>Running ({tasks.length})</h2>
      <div style={styles.tableWrap}>
        <table style={styles.table}>
          <thead>
            <tr>
              {['', 'ID', 'Started', 'Elapsed', 'Idle', 'Context', 'Events', 'Coder', 'Model', 'Title', 'cwd', 'Last event'].map(h => (
                <th key={h} style={styles.th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tasks.map(task => {
              const cwd = task.cwd ? task.cwd.split('/').pop() ?? task.cwd : '—';
              const lastEvt = [task.last_event_kind, task.last_event_detail]
                .filter(Boolean)
                .join(' ');
              return (
                <tr
                  key={task.id}
                  style={styles.tr}
                  onClick={() => navigate(`/tasks/${task.id}`)}
                  onContextMenu={e => {
                    e.preventDefault();
                    setMenu({ task, x: e.clientX, y: e.clientY });
                  }}
                >
                  <td style={styles.td}>
                    <StatusDot task={task} thresholdPct={thresholdPct} />
                  </td>
                  <td style={{ ...styles.td, ...styles.idCell }}>
                    <span
                      style={styles.idLink}
                      onClick={e => {
                        e.stopPropagation();
                        navigate(`/tasks/${task.id}`);
                      }}
                    >
                      {task.id}
                    </span>
                  </td>
                  <td style={styles.td}>{formatRelative(task.started_at)}</td>
                  <td style={styles.td}>{formatElapsed(task.elapsed_sec)}</td>
                  <td style={styles.td}>{formatElapsed(task.idle_sec)}</td>
                  <td style={{ ...styles.td, ...styles.ctxCell }}>
                    <span>{formatTokens(task.context_tokens)}</span>
                    <Sparkline value={task.context_tokens} />
                  </td>
                  <td style={styles.td}>{task.events}</td>
                  <td style={{ ...styles.td, ...(task.coder ? styles.bold : styles.dim) }}>
                    {task.coder ?? '(default)'}
                  </td>
                  <td style={{ ...styles.td, ...(task.model ? styles.bold : styles.dim) }}>
                    {task.model ?? '(default)'}
                  </td>
                  <td style={{ ...styles.td, ...styles.titleCell }}>
                    {(task.title ?? '').slice(0, 40)}
                  </td>
                  <td style={styles.td}>
                    <span title={task.cwd ?? undefined}>{cwd}</span>
                  </td>
                  <td style={{ ...styles.td, ...styles.lastEvtCell }}>{lastEvt || '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {menu && (
        <div ref={menuRef} style={{ ...styles.ctxMenu, top: menu.y, left: menu.x }}>
          <button
            style={styles.menuItem}
            onClick={() => {
              void api.killTask(menu.task.id);
              setMenu(null);
            }}
          >
            Kill
          </button>
          <button
            style={styles.menuItem}
            onClick={() => {
              void api.requeueTask(menu.task.id);
              setMenu(null);
            }}
          >
            Re-queue
          </button>
          {menu.task.cwd && (
            <>
              <button
                style={styles.menuItem}
                onClick={() => {
                  window.open(`file://${menu.task.cwd}`);
                  setMenu(null);
                }}
              >
                Open cwd in Finder
              </button>
              <button
                style={styles.menuItem}
                onClick={() => {
                  window.open(`vscode://file/${menu.task.cwd}`);
                  setMenu(null);
                }}
              >
                Open cwd in VS Code
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}

const styles = {
  section: {
    marginBottom: '1.5rem',
  } as React.CSSProperties,
  title: {
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#71717a',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    marginBottom: '0.5rem',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
  tableWrap: {
    overflowX: 'auto' as const,
  } as React.CSSProperties,
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '0.8125rem',
    tableLayout: 'auto' as const,
  } as React.CSSProperties,
  th: {
    padding: '0.25rem 0.5rem',
    textAlign: 'left' as const,
    color: '#71717a',
    fontWeight: 500,
    borderBottom: '1px solid #27272a',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  tr: {
    cursor: 'pointer',
    borderBottom: '1px solid #1f1f23',
  } as React.CSSProperties,
  td: {
    padding: '0.3rem 0.5rem',
    color: '#d4d4d8',
    verticalAlign: 'middle' as const,
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  idCell: {
    fontFamily: 'monospace',
  } as React.CSSProperties,
  idLink: {
    color: '#60a5fa',
    cursor: 'pointer',
  } as React.CSSProperties,
  ctxCell: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.25rem',
  } as React.CSSProperties,
  titleCell: {
    maxWidth: '20rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  } as React.CSSProperties,
  lastEvtCell: {
    maxWidth: '16rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    color: '#71717a',
  } as React.CSSProperties,
  bold: {
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  dim: {
    color: '#52525b',
  } as React.CSSProperties,
  ctxMenu: {
    position: 'fixed' as const,
    background: '#27272a',
    border: '1px solid #3f3f46',
    borderRadius: 6,
    padding: '0.25rem',
    zIndex: 1000,
    minWidth: '10rem',
    boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  menuItem: {
    display: 'block',
    width: '100%',
    padding: '0.4rem 0.75rem',
    background: 'none',
    border: 'none',
    color: '#d4d4d8',
    fontSize: '0.875rem',
    textAlign: 'left' as const,
    cursor: 'pointer',
    borderRadius: 4,
  } as React.CSSProperties,
};

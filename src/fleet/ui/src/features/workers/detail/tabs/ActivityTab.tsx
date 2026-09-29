// Activity tab (ADR 0017): one time-ordered feed across attempts — coder
// events plus fleet log lines (warning+) with attempt dividers, kind
// filters, expandable raw payloads and a collapsible stderr tail.
// The page owns the useActivity feed so the gutter can share it.
import { useEffect, useRef, useState } from 'react';
import type { ActivityItem } from '../../../../shared/types';
import type { ActivityState } from '../useActivity';
import { formatClockTime } from '../../../../shared/format';
import { eventKindColor } from '../../../../shared/colors';
import { useClickableProps } from '../../../../shared/ui/Clickable';
import { EmptyState } from '../../../../shared/ui/EmptyState';
import { LoadingState } from '../../../../shared/ui/LoadingState';
import { merge, when } from '../../../../shared/styles/recipes';
import * as T from '../../../../shared/styles/tokens';

interface Props {
  taskId: string;
  status: string;
  feed: ActivityState;
}

type FilterKey = 'all' | 'text' | 'tools' | 'errors' | 'log';

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'text', label: 'Text' },
  { key: 'tools', label: 'Tools' },
  { key: 'errors', label: 'Errors' },
  { key: 'log', label: 'Fleet log' },
];

const TEXT_KINDS = new Set(['assistant_text', 'thinking']);
const TOOL_KINDS = new Set(['tool_use', 'tool_result']);

function matchesFilter(item: ActivityItem, filter: FilterKey): boolean {
  switch (filter) {
    case 'all':
      return true;
    case 'text':
      return TEXT_KINDS.has(item.kind);
    case 'tools':
      return TOOL_KINDS.has(item.kind);
    case 'errors':
      return (
        item.kind === 'error' ||
        item.kind === 'rate_limit' ||
        (item.source === 'log' && item.kind.toLowerCase() === 'error')
      );
    case 'log':
      return item.source === 'log';
  }
}

function badgeColor(item: ActivityItem): string {
  if (item.source === 'log') {
    const level = item.kind.toLowerCase();
    if (level === 'error') return T.colors.danger;
    if (level === 'warning') return T.colors.amber;
  }
  return eventKindColor(item.kind);
}

// tool_result payload text shown above the raw JSON when it is a string.
function resultOutput(raw: Record<string, unknown>): string | null {
  const part = raw.part as Record<string, unknown> | undefined;
  const state = part?.state as Record<string, unknown> | undefined;
  for (const value of [state?.output, raw.output, raw.content]) {
    if (typeof value === 'string' && value.length > 0) return value;
  }
  return null;
}

const OUTPUT_CAP = 4000;

function isLive(status: string): boolean {
  return status === 'in_progress';
}

export function ActivityTab({ taskId, status, feed }: Props) {
  void taskId;
  const [filter, setFilter] = useState<FilterKey>('all');
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const nearBottom = useRef(true);
  const [atBottom, setAtBottom] = useState(true);

  const live = isLive(status);

  // Auto-scroll to the end on new rows only when already near the bottom.
  useEffect(() => {
    if (nearBottom.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [feed.items.length]);

  function handleScroll(): void {
    const el = listRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight <= 40;
    nearBottom.current = near;
    setAtBottom(near);
  }

  function scrollToBottom(): void {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    nearBottom.current = true;
    setAtBottom(true);
  }

  const visible = feed.items.filter((item) => matchesFilter(item, filter));

  function statusLine(): React.ReactNode {
    if (feed.error) {
      return (
        <span style={styles.statusError}>
          {feed.error}{' '}
          <button style={styles.retryLink} onClick={() => feed.retry()}>
            Retry
          </button>
        </span>
      );
    }
    if (live) {
      const updated =
        feed.lastUpdated != null ? new Date(feed.lastUpdated).toTimeString().slice(0, 8) : null;
      return <span style={styles.status}>live{updated ? ` · updated ${updated}` : ''}</span>;
    }
    return <span style={styles.status}>finished</span>;
  }

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <div style={styles.filters}>
          {FILTERS.map((f) => (
            <button
              key={f.key}
              style={merge(styles.chip, when(filter === f.key, styles.chipActive))}
              onClick={() => {
                setFilter(f.key);
                setExpandedSeq(null);
              }}
            >
              {f.label}
            </button>
          ))}
        </div>
        {feed.hasEarlier && (
          <button style={styles.loadEarlier} onClick={() => feed.loadEarlier()}>
            Load earlier
          </button>
        )}
        {statusLine()}
      </div>
      <div ref={listRef} style={styles.list} onScroll={handleScroll}>
        {feed.loading && visible.length === 0 && !feed.error && <LoadingState />}
        {!feed.loading && feed.error && visible.length === 0 && (
          <div style={styles.errorBlock}>
            <span style={styles.statusError}>{feed.error}</span>{' '}
            <button style={styles.retryBtn} onClick={() => feed.retry()}>
              Retry
            </button>
          </div>
        )}
        {!feed.loading && !feed.error && visible.length === 0 && (
          <EmptyState message={live ? 'No activity yet.' : 'No activity recorded.'} />
        )}
        {visible.map((item, i) => {
          const prev = i > 0 ? visible[i - 1] : null;
          const showDivider =
            (i === 0 && feed.latestAttempt > 1) || (prev != null && prev.attempt !== item.attempt);
          return (
            <div key={item.seq}>
              {showDivider && <div style={styles.divider}>Attempt {item.attempt}</div>}
              <ActivityRow
                item={item}
                expanded={expandedSeq === item.seq}
                onToggle={() => setExpandedSeq(expandedSeq === item.seq ? null : item.seq)}
              />
            </div>
          );
        })}
      </div>
      {!atBottom && visible.length > 0 && (
        <button style={styles.newestBtn} onClick={scrollToBottom}>
          ↓ newest
        </button>
      )}
      {feed.stderr && (
        <details style={styles.stderr}>
          <summary style={styles.stderrSummary}>
            stderr (attempt {feed.stderr.attempt}, last 40 lines)
          </summary>
          <pre style={styles.stderrPre}>{feed.stderr.lines.join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

function ActivityRow({
  item,
  expanded,
  onToggle,
}: {
  item: ActivityItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const rowClick = useClickableProps(onToggle);
  const output = item.kind === 'tool_result' ? resultOutput(item.raw) : null;
  return (
    <div>
      <div
        style={merge(styles.row, when(item.kind === 'error', styles.rowError))}
        {...rowClick}
        aria-expanded={expanded}
      >
        <span style={styles.ts}>{formatClockTime(item.ts)}</span>
        <span
          style={merge(styles.badge, {
            background: `${badgeColor(item)}22`,
            color: badgeColor(item),
            borderColor: `${badgeColor(item)}66`,
          })}
        >
          {item.kind}
        </span>
        {item.tool_name && <span style={styles.toolName}>{item.tool_name}</span>}
        <span style={styles.summary}>{item.summary || item.kind}</span>
      </div>
      {expanded && (
        <div style={styles.expanded}>
          {output && (
            <pre style={styles.outputPre}>
              {output.length > OUTPUT_CAP ? `${output.slice(0, OUTPUT_CAP)}… (truncated)` : output}
            </pre>
          )}
          <pre style={styles.rawPre}>
            <code>{JSON.stringify(item.raw, null, 2)}</code>
          </pre>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: 'relative',
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.4rem 0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
  },
  filters: {
    display: 'flex',
    gap: '0.25rem',
    flexWrap: 'wrap',
  },
  chip: {
    padding: '0.1rem 0.45rem',
    borderRadius: '10rem',
    border: `1px solid ${T.colors.border}`,
    background: 'transparent',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.7rem',
  },
  chipActive: {
    background: T.colors.borderSubtle,
    color: T.colors.textPrimary,
    borderColor: T.colors.link,
  },
  loadEarlier: {
    padding: '0.1rem 0.5rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textDim,
    cursor: 'pointer',
    fontSize: '0.7rem',
    whiteSpace: 'nowrap',
  },
  status: {
    marginLeft: 'auto',
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    whiteSpace: 'nowrap',
  },
  statusError: {
    marginLeft: 'auto',
    color: T.colors.danger,
    fontSize: '0.7rem',
    whiteSpace: 'nowrap',
  },
  retryLink: {
    background: 'none',
    border: 'none',
    padding: 0,
    color: T.colors.link,
    cursor: 'pointer',
    fontSize: '0.7rem',
    textDecoration: 'underline',
  },
  retryBtn: {
    padding: '0.2rem 0.6rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.75rem',
  },
  errorBlock: {
    padding: '0.5rem',
    color: T.colors.danger,
    fontSize: '0.75rem',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  divider: {
    padding: '0.35rem 0.25rem 0.15rem',
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    fontWeight: 700,
  },
  row: {
    display: 'flex',
    gap: '0.4rem',
    alignItems: 'baseline',
    padding: '0.15rem 0.25rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
    cursor: 'pointer',
    fontSize: '0.74rem',
    lineHeight: 1.4,
  },
  rowError: {
    background: T.colors.dangerWash,
  },
  ts: {
    color: T.colors.textMuted,
    flexShrink: 0,
    width: 66,
  },
  badge: {
    flexShrink: 0,
    padding: '0.05rem 0.3rem',
    borderRadius: '0.25rem',
    border: '1px solid',
    fontSize: '0.65rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    width: 72,
    textAlign: 'center',
  },
  toolName: {
    color: T.colors.slateLight,
    flexShrink: 0,
    width: 90,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  summary: {
    color: T.colors.textPrimary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  expanded: {
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  outputPre: {
    margin: 0,
    padding: '0.3rem 0.5rem',
    background: T.colors.bgDeep,
    color: T.colors.textBody,
    fontSize: '0.7rem',
    overflow: 'auto',
    maxHeight: 160,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  rawPre: {
    margin: 0,
    padding: '0.3rem 0.5rem',
    background: T.colors.bgSurface,
    color: T.colors.textSecondary,
    fontSize: '0.7rem',
    overflow: 'auto',
    maxHeight: 240,
  },
  newestBtn: {
    position: 'absolute',
    right: '1rem',
    bottom: '0.75rem',
    padding: '0.2rem 0.6rem',
    background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '10rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.7rem',
  },
  stderr: {
    borderTop: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
    padding: '0.3rem 0.75rem',
    fontSize: '0.72rem',
  },
  stderrSummary: {
    cursor: 'pointer',
    color: T.colors.textSecondary,
  },
  stderrPre: {
    margin: '0.3rem 0 0',
    padding: '0.4rem 0.5rem',
    background: T.colors.bgDeep,
    color: T.colors.textSecondary,
    fontSize: '0.7rem',
    overflow: 'auto',
    maxHeight: 200,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
};

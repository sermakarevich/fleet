import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../shared/api';
import { usePoll } from '../../../shared/poll';
import type { StreamEvent } from '../../../shared/types';
import { fmtClockTime } from '../../../shared/format';
import { eventKindColor } from '../../../shared/status';
import { merge, when } from '../../../shared/styles/recipes';

interface Props {
  taskId: string;
  status?: string;
}

const KIND_FILTERS = [
  { label: 'All', kinds: undefined },
  { label: 'Text', kinds: 'assistant_text,thinking' },
  { label: 'Tools', kinds: 'tool_use,tool_result' },
  { label: 'Errors', kinds: 'error' },
  { label: 'Steps', kinds: 'session_started,session_ended' },
];

function loadEvents(taskId: string, offset: number, limit: number, kind: string | undefined): Promise<{ total: number; offset: number; events: StreamEvent[] }> {
  return api.getTaskEvents(taskId, { offset, limit, kind });
}

const MAX_RAW_HEIGHT = 240;

export function EventsTab({ taskId, status }: Props) {
  const [activeFilter, setActiveFilter] = useState(0);
  const [offset, setOffset] = useState<number | null>(null);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const [pageSize] = useState(100);

  const currentKinds = KIND_FILTERS[activeFilter]?.kinds;

  const { data, isLoading } = useQuery({
    queryKey: ['task', taskId, 'events', currentKinds ?? '_all', offset],
    queryFn: () => {
      // Default: no offset → load latest
      return loadEvents(taskId, offset ?? 0, pageSize, currentKinds);
    },
    refetchInterval: usePoll('normal', !status || status === 'in_progress'),
  });

  const events: StreamEvent[] = data?.events ?? [];
  const total: number = data?.total ?? 0;

  // Auto-scroll to bottom when new data arrives
  useEffect(() => {
    if (listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [data]);

  function handleLoadOlder() {
    if (data) {
      setOffset(data.offset - pageSize);
      setExpandedIdx(null);
    }
  }

  function handleToggleExpand(i: number) {
    if (expandedIdx === i) setExpandedIdx(null);
    else setExpandedIdx(i);
  }

  const hasMore = offset !== null && (offset - pageSize) >= 0;

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        <div style={styles.filters}>
          {KIND_FILTERS.map((f, i) => (
            <button
              key={i}
              style={merge(styles.chip, when(activeFilter === i, styles.chipActive))}
              onClick={() => { setActiveFilter(i); setOffset(null); setExpandedIdx(null); }}
            >
              {f.label}
            </button>
          ))}
        </div>
        <span style={styles.count}>{total} events</span>
      </div>
      {hasMore && (
        <button style={styles.loadMoreBtn} onClick={handleLoadOlder}>
          Load older ({(offset! - pageSize) + 1}..{offset})
        </button>
      )}
      <div ref={listRef} style={styles.list}>
        {isLoading && !data && <p style={styles.msg}>Loading…</p>}
        {!isLoading && events.length === 0 && <p style={styles.msg}>No events found.</p>}
        {events.map((evt, i) => {
          const prev = i > 0 ? events[i - 1] : null;
          const showSeparator = prev && prev.session_id !== evt.session_id && evt.session_id != null;
          return (
            <div key={i}>
              {showSeparator && <div style={styles.separator} />}
              <div
                style={merge(styles.row, when(evt.kind === 'error', styles.rowError), {  })}
                onClick={() => handleToggleExpand(i)}
              >
                <span style={styles.ts}>{fmtClockTime(evt.ts)}</span>
                <span
                  style={merge(styles.badge, { background: eventKindColor(evt.kind) + '22', color: eventKindColor(evt.kind), borderColor: eventKindColor(evt.kind) + '66',  })}
                >
                  {evt.kind}
                </span>
                {evt.tool_name && <span style={styles.toolName}>{evt.tool_name}</span>}
                <span style={styles.summary}>{evt.summary || evt.kind}</span>
                {' '}{(() => {
                  // render usage tokens right-aligned
                  if (evt.usage) {
                    const inTok = evt.usage.input_tokens ?? evt.usage.cache_creation_input_tokens;
                    const outTok = evt.usage.output_tokens ?? evt.usage.cache_read_input_tokens;
                    const parts: string[] = [];
                    if (typeof inTok === 'number') parts.push(`in:${inTok}`);
                    if (typeof outTok === 'number') parts.push(`out:${outTok}`);
                    if (parts.length) return <span style={styles.usage}>{parts.join(', ')}</span>;
                  }
                  return null;
                })()}
              </div>
              {expandedIdx === i && (
                <pre style={styles.rawPre}>
                  <code>{JSON.stringify(evt.raw, null, 2)}</code>
                </pre>
              )}
            </div>
          );
        })}
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
  count: {
    color: '#52525b',
    fontSize: '0.7rem',
    whiteSpace: 'nowrap',
  },
  loadMoreBtn: {
    margin: '0.4rem 0.75rem',
    padding: '0.3rem 0.75rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.72rem',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  row: {
    display: 'flex',
    gap: '0.4rem',
    alignItems: 'baseline',
    padding: '0.15rem 0.25rem',
    borderBottom: '1px solid #1c1c20',
    cursor: 'pointer',
    fontSize: '0.74rem',
    lineHeight: 1.4,
  },
  rowError: {
    background: '#ef444410',
  },
  ts: {
    color: '#52525b',
    flexShrink: 0,
    width: 66,
  },
  badge: {
    flexShrink: 0,
    padding: '0.05rem 0.3rem',
    borderRadius: 4,
    border: '1px solid',
    fontSize: '0.65rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    width: 72,
    textAlign: 'center',
  },
  toolName: {
    color: '#94a3b8',
    flexShrink: 0,
    width: 90,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  summary: {
    color: '#e4e4e7',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
  },
  usage: {
    color: '#71717a',
    flexShrink: 0,
    fontSize: '0.65rem',
    textAlign: 'right',
    width: 70,
  },
  separator: {
    height: 1,
    background: '#3f3f46',
    margin: '0.3rem 0.5rem',
    opacity: 0.5,
  },
  rawPre: {
    margin: 0,
    padding: '0.3rem 0.5rem',
    background: '#18181b',
    color: '#a1a1aa',
    fontSize: '0.7rem',
    overflow: 'auto',
    maxHeight: MAX_RAW_HEIGHT,
    borderBottom: '1px solid #1c1c20',
  },
  msg: {
    padding: '0.5rem',
    color: '#71717a',
    margin: 0,
  },
};

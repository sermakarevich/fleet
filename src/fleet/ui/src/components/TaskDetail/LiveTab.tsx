import { useEffect, useRef, useState } from 'react';
import type { FleetEvent } from '../../types';

interface EventPair {
  id: string;
  toolUse: FleetEvent;
  toolResult?: FleetEvent;
}

type RowItem =
  | { type: 'pair'; pair: EventPair; key: string }
  | { type: 'event'; event: FleetEvent; key: string };

interface Props {
  events: FleetEvent[];
}

const ALL_FILTER = 'all';

function kindColor(kind: string): string {
  switch (kind) {
    case 'tool_use': return '#3b82f6';
    case 'tool_result': return '#22c55e';
    case 'api_request': return '#8b5cf6';
    case 'api_response': return '#a855f7';
    case 'message': return '#f59e0b';
    case 'error': return '#ef4444';
    default: return '#71717a';
  }
}

function KindBadge({ kind, label }: { kind: string; label: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '0.05rem 0.35rem',
        borderRadius: 3,
        fontSize: '0.65rem',
        fontWeight: 700,
        color: '#fff',
        background: kindColor(kind),
        flexShrink: 0,
      }}
    >
      {label}
    </span>
  );
}

export function LiveTab({ events }: Props) {
  const [activeFilter, setActiveFilter] = useState(ALL_FILTER);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [events.length]);

  const kinds = [ALL_FILTER, ...Array.from(new Set(events.map(e => e.kind))).sort()];

  const rows: RowItem[] = [];
  const pairMap = new Map<string, EventPair>();

  events.forEach((event, idx) => {
    if (event.kind === 'tool_use') {
      const useId = (event.raw?.id as string | undefined) ?? `tool-${idx}`;
      const pair: EventPair = { id: useId, toolUse: event };
      pairMap.set(useId, pair);
      rows.push({ type: 'pair', pair, key: useId });
    } else if (event.kind === 'tool_result') {
      const toolUseId = event.raw?.tool_use_id as string | undefined;
      if (toolUseId && pairMap.has(toolUseId)) {
        pairMap.get(toolUseId)!.toolResult = event;
      } else {
        rows.push({ type: 'event', event, key: `evt-${idx}` });
      }
    } else {
      rows.push({ type: 'event', event, key: `evt-${idx}` });
    }
  });

  const filtered = rows.filter(row => {
    if (activeFilter === ALL_FILTER) return true;
    if (row.type === 'pair') return activeFilter === 'tool_use' || activeFilter === 'tool_result';
    return row.event.kind === activeFilter;
  });

  function toggleCollapse(id: string) {
    setCollapsedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  return (
    <div style={styles.container}>
      <div style={styles.filters}>
        {kinds.map(k => (
          <button
            key={k}
            style={{ ...styles.chip, ...(activeFilter === k ? styles.chipActive : {}) }}
            onClick={() => setActiveFilter(k)}
          >
            {k}
          </button>
        ))}
      </div>
      <div style={styles.list}>
        {filtered.map(row => {
          if (row.type === 'pair') {
            const { pair } = row;
            const isOpen = collapsedIds.has(pair.id);
            const toolName = (pair.toolUse.tool_name ?? pair.toolUse.raw?.name as string | undefined) ?? '?';
            const inputData = pair.toolUse.raw?.input as Record<string, unknown> | undefined;
            const inputPath = inputData?.file_path ?? inputData?.path;
            return (
              <div key={pair.id} style={styles.pairRow}>
                <div style={styles.pairMain}>
                  <button style={styles.pairToggle} onClick={() => toggleCollapse(pair.id)}>
                    {isOpen ? '▼' : '▶'}
                  </button>
                  <KindBadge kind="tool_use" label={toolName} />
                  {inputPath != null && (
                    <span style={styles.path}>{String(inputPath)}</span>
                  )}
                  <span style={styles.ts}>{pair.toolUse.ts.slice(11, 19)}</span>
                  {pair.toolResult && <span style={styles.resultDot}>✓</span>}
                </div>
                {isOpen && (
                  <pre style={styles.detail}>
                    {JSON.stringify(
                      { input: pair.toolUse.raw?.input, output: (pair.toolResult?.raw as Record<string, unknown> | undefined)?.content },
                      null,
                      2,
                    )}
                  </pre>
                )}
              </div>
            );
          }
          const { event, key } = row;
          return (
            <div key={key} style={styles.eventRow}>
              <KindBadge kind={event.kind} label={event.kind} />
              {event.tool_name && <span style={styles.toolName}>{event.tool_name}</span>}
              <span style={styles.ts}>{event.ts.slice(11, 19)}</span>
              {event.usage && (
                <span style={styles.tokens}>
                  {((event.usage.input_tokens ?? 0) + (event.usage.output_tokens ?? 0)).toLocaleString()}t
                </span>
              )}
            </div>
          );
        })}
        <div ref={bottomRef} />
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
  filters: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '0.25rem',
    padding: '0.5rem 0.75rem',
    borderBottom: '1px solid #27272a',
    background: '#18181b',
  },
  chip: {
    padding: '0.15rem 0.5rem',
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
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  pairRow: {
    padding: '0.2rem 0.25rem',
    borderBottom: '1px solid #1c1c20',
  },
  pairMain: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.35rem',
  },
  pairToggle: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: '#71717a',
    padding: '0 0.15rem',
    fontSize: '0.65rem',
    flexShrink: 0,
  },
  eventRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.35rem',
    padding: '0.2rem 0.25rem',
    borderBottom: '1px solid #1c1c20',
  },
  path: {
    color: '#71717a',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 300,
    flex: 1,
  },
  toolName: {
    color: '#a1a1aa',
    flexShrink: 0,
  },
  ts: {
    color: '#3f3f46',
    marginLeft: 'auto',
    flexShrink: 0,
  },
  tokens: {
    color: '#52525b',
    fontSize: '0.7rem',
    flexShrink: 0,
  },
  resultDot: {
    color: '#22c55e',
    fontSize: '0.7rem',
    flexShrink: 0,
  },
  detail: {
    width: '100%',
    background: '#09090b',
    color: '#a1a1aa',
    padding: '0.5rem',
    margin: '0.25rem 0 0',
    borderRadius: 4,
    overflow: 'auto',
    maxHeight: 200,
    fontSize: '0.7rem',
    boxSizing: 'border-box',
  },
};

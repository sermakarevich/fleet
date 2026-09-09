import { useEffect, useRef, useState } from 'react';
import type { FleetEvent } from '../../../shared/types';
import { computeLineDiff } from '../../../shared/diff';
import { formatInteger } from '../../../shared/format';
import * as T from '../../../shared/styles/tokens';
import { DIFF_LINE_STYLE, merge } from '../../../shared/styles/recipes';
import { eventKindColor } from '../../../shared/colors';

function DiffView({ oldStr, newStr }: { oldStr: string; newStr: string }) {
  const lines = computeLineDiff(oldStr, newStr);
  return (
    <pre style={merge(styles.detail, styles.diffReset)}>
      {lines.map((line, idx) => (
        <div
          key={idx}
          style={merge(styles.diffLine, DIFF_LINE_STYLE[line.type])}
        >
          {line.type === 'remove' ? '-' : line.type === 'add' ? '+' : ' '} {line.text}
        </div>
      ))}
    </pre>
  );
}

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

function KindBadge({ kind, label }: { kind: string; label: string }) {
  return (
    <span style={merge(styles.kindBadge, { background: eventKindColor(kind) })}>
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
            style={merge(styles.chip, activeFilter === k && styles.chipActive)}
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
                {isOpen && (() => {
                  if (toolName === 'Edit' && typeof inputData?.old_string === 'string' && typeof inputData?.new_string === 'string') {
                    return <DiffView oldStr={inputData.old_string as string} newStr={inputData.new_string as string} />;
                  }
                  if (toolName === 'Write' && typeof inputData?.content === 'string') {
                    return <DiffView oldStr="" newStr={inputData.content as string} />;
                  }
                  return (
                    <pre style={styles.detail}>
                      {JSON.stringify(
                        { input: pair.toolUse.raw?.input, output: (pair.toolResult?.raw as Record<string, unknown> | undefined)?.content },
                        null,
                        2,
                      )}
                    </pre>
                  );
                })()}
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
                  {formatInteger((event.usage.input_tokens ?? 0) + (event.usage.output_tokens ?? 0))}t
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
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
  },
  chip: {
    padding: '0.15rem 0.5rem',
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
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.25rem 0.5rem',
  },
  pairRow: {
    padding: '0.2rem 0.25rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
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
    color: T.colors.textDim,
    padding: '0 0.15rem',
    fontSize: '0.65rem',
    flexShrink: 0,
  },
  eventRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.35rem',
    padding: '0.2rem 0.25rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  path: {
    color: T.colors.textDim,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 300,
    flex: 1,
  },
  toolName: {
    color: T.colors.textSecondary,
    flexShrink: 0,
  },
  ts: {
    color: T.colors.border,
    marginLeft: 'auto',
    flexShrink: 0,
  },
  tokens: {
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    flexShrink: 0,
  },
  resultDot: {
    color: T.colors.success,
    fontSize: '0.7rem',
    flexShrink: 0,
  },
  detail: {
    width: '100%',
    background: T.colors.bgDeep,
    color: T.colors.textSecondary,
    padding: '0.5rem',
    margin: '0.25rem 0 0',
    borderRadius: '0.25rem',
    overflow: 'auto',
    maxHeight: 200,
    fontSize: '0.7rem',
    boxSizing: 'border-box',
  },
  diffReset: {
    padding: 0,
    overflow: 'auto',
  },
  diffLine: {
    padding: '0 0.4rem',
    whiteSpace: 'pre',
    lineHeight: '1.45',
  },
  kindBadge: {
    display: 'inline-block',
    padding: '0.05rem 0.35rem',
    borderRadius: 3,
    fontSize: '0.65rem',
    fontWeight: 700,
    color: T.colors.white,
    flexShrink: 0,
  },
};

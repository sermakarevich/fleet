/**
 * One pending question as a sidebar row.
 * Called by QuestionList.
 */
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { merge } from '../../shared/styles/recipes';

// Short type tag: text, choice or multi.
export function typeLabel(q: ChatQuestion): string {
  if (!q.options) return 'text';
  return q.multi_select ? 'multi' : 'choice';
}

interface Props {
  question: ChatQuestion;
  selected: boolean;
  age: string;
  onSelect: (id: string) => void;
}

// Sidebar row showing agent, age, prompt preview and tags.
export function QuestionCard({ question: q, selected, age, onSelect }: Props) {
  return (
    <div
      style={merge(styles.item, selected && styles.itemSel)}
      className="row-interactive"
      tabIndex={0}
      onClick={() => onSelect(q.id)}
    >
      <div style={styles.itemTop}>
        <span style={styles.agent}>{q.agent_id || 'unknown'}</span>
        <span style={styles.age}>{age}</span>
      </div>
      <div style={styles.preview}>{q.prompt}</div>
      <div style={styles.tags}>
        <span style={styles.tag}>{typeLabel(q)}</span>
        {q.priority > 0 && (
          <span style={merge(styles.tag, styles.tagPrio)}>prio {q.priority}</span>
        )}
        <span style={styles.tagId}>{q.id.slice(0, 8)}</span>
      </div>
    </div>
  );
}

const styles = {
  item: {
    padding: '11px 12px', marginBottom: 4, border: '1px solid transparent',
    borderRadius: 10, cursor: 'pointer',
  } as React.CSSProperties,
  itemSel: {
    background: colors.bgElevated, borderColor: '#818cf8',
  } as React.CSSProperties,
  itemTop: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8,
  } as React.CSSProperties,
  agent: {
    fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap', overflow: 'hidden',
    textOverflow: 'ellipsis', color: colors.textPrimary,
  } as React.CSSProperties,
  age: {
    color: colors.textSecondary, fontSize: 11.5,
    whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums',
  } as React.CSSProperties,
  preview: {
    color: colors.textSecondary, fontSize: 12.5, marginTop: 3, overflow: 'hidden',
    display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
  } as React.CSSProperties,
  tags: {
    display: 'flex', gap: 6, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  tag: {
    fontSize: 10.5, fontWeight: 600, letterSpacing: '0.4px', textTransform: 'uppercase' as const,
    padding: '1px 7px', borderRadius: 9999,
    background: colors.bgElevated, color: colors.textSecondary,
  } as React.CSSProperties,
  tagPrio: {
    background: '#2a2310', color: '#fbbf24',
  } as React.CSSProperties,
  tagId: {
    marginLeft: 'auto', color: colors.textSecondary, fontSize: 11,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  } as React.CSSProperties,
};

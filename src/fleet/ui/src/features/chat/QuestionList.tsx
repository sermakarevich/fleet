/**
 * Sidebar listing every pending chat question.
 * Called by ChatPage; rows render via QuestionCard.
 */
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { merge } from '../../shared/styles/recipes';
import { QuestionCard } from './QuestionCard';
import { relTime } from '../../shared/format';

interface Props {
  questions: ChatQuestion[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  serverOffset: number;
  now: number;
}

// Sidebar with presence dot, pending count and question rows.
export function QuestionList({ questions, selectedId, onSelect, serverOffset, now }: Props) {
  return (
    <aside style={styles.sidebar}>
      <div style={styles.sideHead}>
        <div style={styles.brand}>
          <span
            style={merge(styles.dot, questions.length === 0 && styles.dotIdle)}
            title={questions.length ? `${questions.length} unanswered` : 'No pending questions'}
          />
          Chat
        </div>
        <div style={styles.count}>{questions.length} pending</div>
      </div>
      <div style={styles.list}>
        {questions.length === 0 ? (
          <div style={styles.emptyList}>No pending questions.</div>
        ) : questions.map((q) => (
          <QuestionCard
            key={q.id}
            question={q}
            selected={q.id === selectedId}
            age={relTime(q.created_at, serverOffset, now)}
            onSelect={onSelect}
          />
        ))}
      </div>
    </aside>
  );
}

const styles = {
  sidebar: {
    width: 340, minWidth: 300, height: '100%', background: colors.bgSurface,
    borderRight: `1px solid ${colors.borderSubtle}`,
    display: 'flex', flexDirection: 'column' as const, flexShrink: 0,
  } as React.CSSProperties,
  sideHead: {
    padding: '16px 18px', borderBottom: `1px solid ${colors.borderSubtle}`,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  } as React.CSSProperties,
  brand: {
    display: 'flex', alignItems: 'center', gap: 8,
    fontWeight: 700, fontSize: 15, color: colors.textPrimary,
  } as React.CSSProperties,
  dot: {
    width: 8, height: 8, borderRadius: '50%', background: colors.success,
    boxShadow: '0 0 0 3px rgba(34,197,94,.18)',
    display: 'inline-block', flexShrink: 0,
    transition: 'background-color .2s, box-shadow .2s',
  } as React.CSSProperties,
  dotIdle: {
    background: colors.border, boxShadow: 'none',
  } as React.CSSProperties,
  count: {
    color: colors.textSecondary, fontSize: 12.5,
    fontWeight: 500, fontVariantNumeric: 'tabular-nums',
  } as React.CSSProperties,
  list: {
    flex: 1, overflowY: 'auto', padding: 8,
  } as React.CSSProperties,
  emptyList: {
    padding: '40px 12px', textAlign: 'center' as const,
    color: colors.textSecondary, fontSize: 13,
  } as React.CSSProperties,
};

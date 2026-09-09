/**
 * Sidebar listing every pending chat question.
 * Called by ChatPage; rows render via QuestionCard.
 */
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { merge } from '../../shared/styles/recipes';
import { EmptyState } from '../../shared/ui/EmptyState';
import { QuestionCard } from './QuestionCard';
import { formatRelativeAge } from '../../shared/format';

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
          <EmptyState message="No pending questions." />
        ) : questions.map((q) => (
          <QuestionCard
            key={q.id}
            question={q}
            selected={q.id === selectedId}
            age={formatRelativeAge(q.created_at, serverOffset, now)}
            onSelect={onSelect}
          />
        ))}
      </div>
    </aside>
  );
}

const styles = {
  sidebar: {
    width: '21.25rem', minWidth: '18.75rem', height: '100%', background: colors.bgSurface,
    borderRight: `1px solid ${colors.borderSubtle}`,
    display: 'flex', flexDirection: 'column' as const, flexShrink: 0,
  } as React.CSSProperties,
  sideHead: {
    padding: '1rem 1.125rem', borderBottom: `1px solid ${colors.borderSubtle}`,
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  } as React.CSSProperties,
  brand: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    fontWeight: 700, fontSize: '0.9375rem', color: colors.textPrimary,
  } as React.CSSProperties,
  dot: {
    width: '0.5rem', height: '0.5rem', borderRadius: '50%', background: colors.success,
    boxShadow: '0 0 0 0.1875rem rgba(34,197,94,.18)',
    display: 'inline-block', flexShrink: 0,
    transition: 'background-color .2s, box-shadow .2s',
  } as React.CSSProperties,
  dotIdle: {
    background: colors.border, boxShadow: 'none',
  } as React.CSSProperties,
  count: {
    color: colors.textSecondary, fontSize: '0.78125rem',
    fontWeight: 500, fontVariantNumeric: 'tabular-nums',
  } as React.CSSProperties,
  list: {
    flex: 1, overflowY: 'auto', padding: '0.5rem',
  } as React.CSSProperties,
};

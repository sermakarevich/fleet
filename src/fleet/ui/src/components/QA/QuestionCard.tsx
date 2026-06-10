import { useState } from 'react';
import type { QuestionSummary } from '../../types';
import { AnswerComposer } from './AnswerComposer';
import * as T from '../../styles/tokens';

interface Props {
  question: QuestionSummary;
  onAnswer: (id: string, answer: string) => Promise<void>;
  onDefer: (id: string) => Promise<void>;
  selected?: boolean;
  onSelect?: (id: string, selected: boolean) => void;
  batchMode?: boolean;
}

function formatElapsed(sec: number): string {
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

function statusColor(status: QuestionSummary['status']): string {
  switch (status) {
    case 'open': return '#22c55e';
    case 'answered': return '#3b82f6';
    case 'timed_out': return '#ef4444';
    case 'deferred': return '#f59e0b';
  }
}

export function QuestionCard({
  question,
  onAnswer,
  onDefer,
  selected,
  onSelect,
  batchMode,
}: Props) {
  const [busy, setBusy] = useState(false);

  const handleAnswer = async (answer: string) => {
    setBusy(true);
    try { await onAnswer(question.id, answer); } finally { setBusy(false); }
  };

  const handleDefer = async () => {
    setBusy(true);
    try { await onDefer(question.id); } finally { setBusy(false); }
  };

  const isOpen = question.status === 'open';

  return (
    <div style={{ ...styles.card, borderLeftColor: statusColor(question.status) }}>
      <div style={styles.header}>
        {batchMode && isOpen && (
          <input
            type="checkbox"
            checked={selected ?? false}
            onChange={e => onSelect?.(question.id, e.target.checked)}
            style={styles.checkbox}
          />
        )}
        <span style={styles.taskTitle}>{question.task_title || question.task_id}</span>
        {question.task_cwd && (
          <span style={styles.cwd}>{question.task_cwd}</span>
        )}
        <span style={styles.elapsed}>{formatElapsed(question.elapsed_sec)}</span>
        <span style={{ ...styles.statusBadge, color: statusColor(question.status) }}>
          {question.status === 'timed_out' ? 'timed out' : question.status}
        </span>
      </div>
      <p style={styles.questionText}>{question.question}</p>
      {isOpen && !batchMode && (
        <div style={styles.actions}>
          <AnswerComposer
            choices={question.choices}
            onSubmit={handleAnswer}
            disabled={busy}
          />
          <button onClick={handleDefer} disabled={busy} style={styles.deferBtn}>
            Defer
          </button>
        </div>
      )}
      {!isOpen && question.answer && question.answer !== '__DEFERRED__' && (
        <p style={styles.answerText}>Answer: {question.answer}</p>
      )}
    </div>
  );
}

const styles = {
  card: {
    background: T.colors.bgElevated,
    borderRadius: 6,
    padding: '0.75rem 1rem',
    borderLeft: '3px solid #22c55e',
    marginBottom: '0.75rem',
  } as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.5rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  checkbox: {
    flexShrink: 0,
    cursor: 'pointer',
    width: '1rem',
    height: '1rem',
  } as React.CSSProperties,
  taskTitle: {
    fontWeight: 600,
    fontSize: '0.875rem',
    color: T.colors.textPrimary,
    flex: '0 0 auto',
  } as React.CSSProperties,
  cwd: {
    fontSize: '0.75rem',
    color: T.colors.textDim,
    fontFamily: 'monospace',
    flex: '0 0 auto',
  } as React.CSSProperties,
  elapsed: {
    fontSize: '0.75rem',
    color: T.colors.textMuted,
    marginLeft: 'auto',
  } as React.CSSProperties,
  statusBadge: {
    fontSize: '0.7rem',
    fontWeight: 600,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    flexShrink: 0,
  } as React.CSSProperties,
  questionText: {
    margin: '0 0 0.75rem',
    fontSize: '0.875rem',
    color: '#d4d4d8',
    lineHeight: 1.5,
    whiteSpace: 'pre-wrap' as const,
  } as React.CSSProperties,
  actions: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.5rem',
  } as React.CSSProperties,
  deferBtn: {
    ...T.btnGhost,
    alignSelf: 'flex-start' as const,
    padding: '0.25rem 0.75rem',
    border: '1px solid #52525b',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  answerText: {
    margin: 0,
    fontSize: '0.8125rem',
    color: T.colors.textDim,
    fontStyle: 'italic' as const,
  } as React.CSSProperties,
};

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';
import type { QuestionSummary } from '../types';
import { AnswerComposer } from '../components/QA/AnswerComposer';
import { QuestionCard } from '../components/QA/QuestionCard';
import * as T from '../styles/tokens';

type Filter = 'all' | 'open' | 'answered' | 'timed_out' | 'deferred';

const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'answered', label: 'Answered' },
  { value: 'timed_out', label: 'Timed out' },
  { value: 'deferred', label: 'Deferred' },
];

export function QAInbox() {
  const [questions, setQuestions] = useState<QuestionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>('open');
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [errorToasts, setErrorToasts] = useState<Array<{ id: string; message: string }>>([]);
  const qc = useQueryClient();

  const addError = (message: string) => {
    const id = String(Date.now());
    setErrorToasts(prev => [...prev, { id, message }]);
    setTimeout(() => setErrorToasts(prev => prev.filter(t => t.id !== id)), 8000);
  };

  useEffect(() => {
    api
      .getQA()
      .then(list => {
        setQuestions(list);
        setLoading(false);
      })
      .catch(err => {
        setError(String(err));
        setLoading(false);
      });
  }, []);

  // Prepend new questions arriving via WebSocket
  useWebSocket((_taskId, event) => {
    if (event.kind !== 'ask_human') return;
    // Re-fetch the full list so we get task_title/task_cwd metadata
    api.getQA().then(list => setQuestions(list)).catch(() => undefined);
  });

  const markAnswered = (id: string, answer: string) => {
    setQuestions(prev =>
      prev.map(q => (q.id === id ? { ...q, status: 'answered' as const, answer } : q)),
    );
    void qc.invalidateQueries({ queryKey: ['qa'] });
  };

  const markDeferred = (id: string) => {
    setQuestions(prev =>
      prev.map(q => (q.id === id ? { ...q, status: 'deferred' as const } : q)),
    );
    void qc.invalidateQueries({ queryKey: ['qa'] });
  };

  const handleAnswer = async (id: string, answer: string) => {
    try {
      await api.answerQuestion(id, answer);
      markAnswered(id, answer);
    } catch (err) {
      addError(`Failed to answer question: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDefer = async (id: string) => {
    try {
      await api.deferQuestion(id);
      markDeferred(id);
    } catch (err) {
      addError(`Failed to defer question: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleSelect = (id: string, checked: boolean) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleBatchAnswer = async (answer: string) => {
    const ids = Array.from(selectedIds);
    const results = await Promise.allSettled(ids.map(id => api.answerQuestion(id, answer)));
    const succeeded: string[] = [];
    let failCount = 0;
    results.forEach((result, i) => {
      if (result.status === 'fulfilled') {
        succeeded.push(ids[i]);
      } else {
        failCount++;
      }
    });
    succeeded.forEach(id => markAnswered(id, answer));
    if (failCount > 0) {
      addError(
        failCount === ids.length
          ? `All ${ids.length} answers failed to send`
          : `${failCount} of ${ids.length} answers failed to send`,
      );
    }
    setSelectedIds(new Set());
  };

  const toggleBatchMode = () => {
    setBatchMode(b => !b);
    setSelectedIds(new Set());
  };

  const countByStatus = (s: QuestionSummary['status']) =>
    questions.filter(q => q.status === s).length;

  const visible = filter === 'all' ? questions : questions.filter(q => q.status === filter);

  if (loading) return <p style={styles.msg}>Loading…</p>;
  if (error) return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {error}</p>;

  return (
    <div style={styles.page}>
      {errorToasts.length > 0 && (
        <div style={styles.errorToastContainer}>
          {errorToasts.map(t => (
            <div key={t.id} style={styles.errorToast}>
              <span style={styles.toastText}>{t.message}</span>
              <button
                style={styles.toastClose}
                onClick={() => setErrorToasts(prev => prev.filter(x => x.id !== t.id))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={styles.toolbar}>
        <h1 style={styles.heading}>Q&amp;A Inbox</h1>
        <div style={styles.chips}>
          {FILTERS.map(({ value, label }) => {
            const count = value !== 'all' ? countByStatus(value as QuestionSummary['status']) : questions.length;
            return (
              <button
                key={value}
                onClick={() => setFilter(value)}
                style={{
                  ...styles.chip,
                  ...(filter === value ? styles.chipActive : {}),
                }}
              >
                {label}
                <span style={styles.chipCount}>{count}</span>
              </button>
            );
          })}
        </div>
        <button
          onClick={toggleBatchMode}
          style={{ ...styles.batchBtn, ...(batchMode ? styles.batchBtnActive : {}) }}
        >
          {batchMode ? 'Cancel batch' : 'Batch answer'}
        </button>
      </div>

      {batchMode && selectedIds.size > 0 && (
        <div style={styles.batchComposer}>
          <p style={styles.batchLabel}>
            Send to {selectedIds.size} question{selectedIds.size !== 1 ? 's' : ''}:
          </p>
          <AnswerComposer
            onSubmit={handleBatchAnswer}
            placeholder={`Answer for all ${selectedIds.size} selected…`}
          />
        </div>
      )}

      {visible.length === 0 ? (
        <p style={styles.empty}>
          No questions{filter !== 'all' ? ` with status "${filter}"` : ''}
        </p>
      ) : (
        <div>
          {visible.map(q => (
            <QuestionCard
              key={q.id}
              question={q}
              onAnswer={handleAnswer}
              onDefer={handleDefer}
              selected={selectedIds.has(q.id)}
              onSelect={handleSelect}
              batchMode={batchMode}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
  } as React.CSSProperties,
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    marginBottom: '1rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '1rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
    flexShrink: 0,
  } as React.CSSProperties,
  chips: {
    display: 'flex',
    gap: '0.375rem',
    flexWrap: 'wrap' as const,
    flex: 1,
  } as React.CSSProperties,
  chip: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    padding: '0.25rem 0.625rem',
    background: T.colors.borderSubtle,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  chipActive: {
    background: '#1e3a5f',
    borderColor: T.colors.accent,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  chipCount: {
    background: T.colors.border,
    borderRadius: 9999,
    padding: '0 0.3rem',
    fontSize: '0.7rem',
    lineHeight: '1.2rem',
    minWidth: '1.2rem',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  batchBtn: {
    ...T.btnGhost,
    padding: '0.25rem 0.75rem',
    border: '1px solid #52525b',
    fontSize: '0.8125rem',
    flexShrink: 0,
  } as React.CSSProperties,
  batchBtnActive: {
    borderColor: T.colors.danger,
    color: '#fca5a5',
  } as React.CSSProperties,
  batchComposer: {
    background: T.colors.bgElevated,
    borderRadius: 6,
    padding: '0.75rem 1rem',
    marginBottom: '1rem',
    borderLeft: `3px solid ${T.colors.accent}`,
  } as React.CSSProperties,
  batchLabel: {
    margin: '0 0 0.5rem',
    fontSize: '0.875rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  empty: {
    color: T.colors.textMuted,
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
  errorToastContainer: {
    position: 'fixed',
    bottom: '1.5rem',
    right: '1.5rem',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.5rem',
    zIndex: 1000,
  } as React.CSSProperties,
  errorToast: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    background: '#991b1b',
    color: '#fff',
    padding: '0.75rem 1rem',
    borderRadius: 6,
    boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    maxWidth: '24rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  toastText: {
    flex: 1,
  } as React.CSSProperties,
  toastClose: {
    background: 'none',
    border: 'none',
    color: '#fca5a5',
    cursor: 'pointer',
    fontSize: '1.125rem',
    lineHeight: 1,
    padding: 0,
    flexShrink: 0,
  } as React.CSSProperties,
};

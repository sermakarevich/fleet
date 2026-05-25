import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import { useWebSocket } from '../hooks/useWebSocket';
import type { QuestionSummary } from '../types';
import { AnswerComposer } from '../components/QA/AnswerComposer';
import { QuestionCard } from '../components/QA/QuestionCard';

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
  const qc = useQueryClient();

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
    await api.answerQuestion(id, answer);
    markAnswered(id, answer);
  };

  const handleDefer = async (id: string) => {
    await api.deferQuestion(id);
    markDeferred(id);
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
    await Promise.all(ids.map(id => api.answerQuestion(id, answer)));
    ids.forEach(id => markAnswered(id, answer));
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
    color: '#71717a',
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
    color: '#e4e4e7',
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
    background: '#27272a',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  chipActive: {
    background: '#1e3a5f',
    borderColor: '#3b82f6',
    color: '#e4e4e7',
  } as React.CSSProperties,
  chipCount: {
    background: '#3f3f46',
    borderRadius: 9999,
    padding: '0 0.3rem',
    fontSize: '0.7rem',
    lineHeight: '1.2rem',
    minWidth: '1.2rem',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  batchBtn: {
    padding: '0.25rem 0.75rem',
    background: 'transparent',
    border: '1px solid #52525b',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
    flexShrink: 0,
  } as React.CSSProperties,
  batchBtnActive: {
    borderColor: '#ef4444',
    color: '#fca5a5',
  } as React.CSSProperties,
  batchComposer: {
    background: '#1c1c20',
    borderRadius: 6,
    padding: '0.75rem 1rem',
    marginBottom: '1rem',
    borderLeft: '3px solid #3b82f6',
  } as React.CSSProperties,
  batchLabel: {
    margin: '0 0 0.5rem',
    fontSize: '0.875rem',
    color: '#a1a1aa',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
};

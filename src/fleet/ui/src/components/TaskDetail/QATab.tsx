import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { useQA, useAnswerQuestion } from '../../hooks/useApi';

interface QABlock {
  question: string;
  answer: string | null;
}

function parseQA(markdown: string): QABlock[] {
  const blocks: QABlock[] = [];
  const sections = markdown.split(/^## /m).filter(Boolean);
  for (const section of sections) {
    if (section.startsWith('Q:')) {
      const body = section.slice(section.indexOf('\n') + 1).trim();
      blocks.push({ question: body, answer: null });
    } else if (section.startsWith('A:')) {
      const body = section.slice(section.indexOf('\n') + 1).trim() || section.slice(2).trim();
      if (blocks.length > 0 && blocks[blocks.length - 1].answer == null) {
        blocks[blocks.length - 1].answer = body;
      }
    }
  }
  return blocks;
}

interface Props {
  taskId: string;
  taskStatus: string;
}

export function QATab({ taskId, taskStatus }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const { data: openQuestions } = useQA('open');
  const { mutate: answerQuestion, isPending } = useAnswerQuestion();

  useEffect(() => {
    api.getArtifactQA(taskId)
      .then(data => { setContent(data.content); setError(null); })
      .catch(() => setError(null)); // no Q&A file is fine
  }, [taskId]);

  useEffect(() => {
    if (taskStatus === 'blocked') {
      const timer = setInterval(() => {
        api.getArtifactQA(taskId)
          .then(data => setContent(data.content))
          .catch(() => {});
      }, 3000);
      return () => clearInterval(timer);
    }
  }, [taskId, taskStatus]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [content]);

  const blocks = content ? parseQA(content) : [];
  const openQuestion = openQuestions?.find(q => q.task_id === taskId) ?? null;

  function handleSubmit() {
    if (!openQuestion || !answerText.trim()) return;
    answerQuestion(
      { id: openQuestion.id, answer: answerText.trim() },
      { onSuccess: () => setAnswerText('') },
    );
  }

  if (error) return <p style={styles.empty}>{error}</p>;

  return (
    <div style={styles.container}>
      <div style={styles.thread}>
        {blocks.length === 0 && (
          <p style={styles.empty}>No Q&amp;A entries yet.</p>
        )}
        {blocks.map((block, i) => (
          <div key={i} style={styles.block}>
            <div style={styles.qRow}>
              <span style={styles.qLabel}>Q</span>
              <pre style={styles.qText}>{block.question}</pre>
            </div>
            {block.answer != null && (
              <div style={styles.aRow}>
                <span style={styles.aLabel}>A</span>
                <pre style={styles.aText}>{block.answer}</pre>
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {taskStatus === 'blocked' && openQuestion && (
        <div style={styles.composer}>
          <div style={styles.composerQuestion}>
            <span style={styles.blockedPill}>blocked</span>
            <span style={styles.composerQ}>{openQuestion.question}</span>
          </div>
          <textarea
            style={styles.textarea}
            value={answerText}
            onChange={e => setAnswerText(e.target.value)}
            placeholder="Type your answer…"
            rows={3}
            onKeyDown={e => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit();
            }}
          />
          <div style={styles.composerActions}>
            <button
              style={{
                ...styles.submitBtn,
                opacity: (!answerText.trim() || isPending) ? 0.5 : 1,
              }}
              onClick={handleSubmit}
              disabled={!answerText.trim() || isPending}
            >
              {isPending ? 'Sending…' : 'Submit answer'}
            </button>
            <span style={styles.hint}>⌘↵ / Ctrl↵</span>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  thread: {
    flex: 1,
    overflowY: 'auto',
    padding: '0.75rem 1rem',
  },
  block: {
    marginBottom: '1rem',
    background: '#18181b',
    borderRadius: 6,
    overflow: 'hidden',
  },
  qRow: {
    display: 'flex',
    gap: '0.5rem',
    padding: '0.5rem 0.75rem',
    background: '#1c1c20',
    borderBottom: '1px solid #27272a',
  },
  qLabel: {
    fontWeight: 700,
    color: '#f59e0b',
    fontSize: '0.75rem',
    flexShrink: 0,
    marginTop: 2,
  },
  qText: {
    margin: 0,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.85rem',
    color: '#e4e4e7',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  aRow: {
    display: 'flex',
    gap: '0.5rem',
    padding: '0.5rem 0.75rem',
  },
  aLabel: {
    fontWeight: 700,
    color: '#22c55e',
    fontSize: '0.75rem',
    flexShrink: 0,
    marginTop: 2,
  },
  aText: {
    margin: 0,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.85rem',
    color: '#a1a1aa',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  empty: {
    padding: '1rem',
    color: '#52525b',
    margin: 0,
  },
  composer: {
    padding: '0.75rem',
    borderTop: '1px solid #27272a',
    background: '#18181b',
  },
  composerQuestion: {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '0.5rem',
    marginBottom: '0.5rem',
  },
  blockedPill: {
    display: 'inline-block',
    padding: '0.1rem 0.45rem',
    borderRadius: 9999,
    background: '#f59e0b',
    color: '#fff',
    fontSize: '0.65rem',
    fontWeight: 700,
    flexShrink: 0,
    marginTop: 2,
  },
  composerQ: {
    fontSize: '0.8rem',
    color: '#a1a1aa',
    fontStyle: 'italic',
  },
  textarea: {
    width: '100%',
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
    padding: '0.5rem',
    resize: 'vertical',
    boxSizing: 'border-box',
  },
  composerActions: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginTop: '0.4rem',
    justifyContent: 'flex-end',
  },
  submitBtn: {
    background: '#3b82f6',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    padding: '0.35rem 0.75rem',
    fontSize: '0.8rem',
    fontWeight: 600,
    cursor: 'pointer',
  },
  hint: {
    fontSize: '0.7rem',
    color: '#52525b',
  },
};

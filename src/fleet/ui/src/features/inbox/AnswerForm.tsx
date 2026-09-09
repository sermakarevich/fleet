// Selected inbox question detail plus the answer form. Rendered by
// InboxPage (desktop right pane) and InboxDetailPage (mobile full page);
// parses the form into a string|string[] answer and hands it to the
// inbox hook's submit. Options render exactly as before (radio or
// checkbox rows); triage proposals gain a triage chip plus the asking
// task's status chip.
import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { formatRelativeAge } from '../../shared/format';
import { useTask } from '../../shared/hooks/useApi';
import { StatusChip } from '../../shared/ui/StatusChip';
import { isTriageQuestion, triageChipStyle } from './questionMeta';

interface Props {
  question: ChatQuestion;
  serverOffset: number;
  now: number;
  isSubmitting: boolean;
  notify: (msg: string) => void;
  onSubmit: (id: string, answer: string | string[]) => void;
}

// Read the answer out of the submitted form.
function readAnswer(form: HTMLFormElement, q: ChatQuestion): string | string[] | null {
  if (q.options) {
    const checked = Array.from(form.querySelectorAll<HTMLInputElement>('input[name="answer"]:checked'));
    if (!checked.length) return null;
    const vals = checked.map((c) => c.value);
    return q.multi_select ? vals : vals[0];
  }
  const v = form.querySelector<HTMLTextAreaElement>('textarea')?.value.trim() ?? '';
  return v || null;
}

// The asking task's status chip (triage proposals only); null while the
// task loads or when it is gone.
function TaskStatusChip({ taskId }: { taskId: string }) {
  const { data, isError } = useTask(taskId);
  if (isError || !data) return null;
  return <StatusChip status={data.status} />;
}

// Detail header, prompt and answer form for one question.
export function AnswerForm({ question: q, serverOffset, now, isSubmitting, notify, onSubmit }: Props) {
  const answerRef = useRef<HTMLTextAreaElement>(null);
  const triage = isTriageQuestion(q);

  // Focus the answer box when a new question is selected (the autoFocus
  // prop is banned by jsx-a11y, so focus imperatively on question change).
  useEffect(() => {
    answerRef.current?.focus();
  }, [q.id]);

  function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const answer = readAnswer(ev.currentTarget, q);
    if (answer == null) {
      notify(q.options ? 'Pick an option first.' : 'Type an answer first.');
      return;
    }
    onSubmit(q.id, answer);
  }

  return (
    <div>
      <div style={styles.detailHead}>
        <div style={styles.detailAgent}>{q.agent_id || 'unknown'}</div>
        <div style={styles.detailMeta}>
          <span style={styles.mono}>#{q.id.slice(0, 8)}</span>
          {q.task_id && (
            <Link to={`/workers/${q.task_id}`} style={styles.taskLink}>
              worker {q.task_id}
            </Link>
          )}
          {q.session_id && <span>session {q.session_id}</span>}
          <span>asked {formatRelativeAge(q.created_at, serverOffset, now)} ago</span>
          {q.timeout_s != null && <span>timeout {Math.round(q.timeout_s)}s</span>}
          {q.priority > 0 && <span style={styles.prioText}>priority {q.priority}</span>}
        </div>
        {triage && (
          <div style={styles.chips}>
            <span style={triageChipStyle()}>triage</span>
            {q.task_id && <TaskStatusChip taskId={q.task_id} />}
          </div>
        )}
      </div>

      <div style={styles.detailPrompt}>{q.prompt}</div>

      <form key={q.id} style={styles.answerForm} onSubmit={handleSubmit}>
        {q.options ? (
          <div style={styles.options}>
            {q.options.map((opt, i) => (
              <label key={i} style={styles.opt}>
                <input
                  type={q.multi_select ? 'checkbox' : 'radio'}
                  name="answer"
                  value={opt}
                  style={styles.optInput}
                />
                <span style={styles.optText}>{opt}</span>
              </label>
            ))}
          </div>
        ) : (
          <textarea
            name="answer"
            ref={answerRef}
            style={styles.textarea}
            placeholder="Type your answer…"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                (e.currentTarget.form as HTMLFormElement).requestSubmit();
              }
            }}
          />
        )}
        <div style={styles.actions}>
          <button type="submit" style={styles.submitBtn} disabled={isSubmitting}>
            {isSubmitting ? 'Sending…' : q.options ? 'Submit answer' : 'Send'}
          </button>
          {!q.options && <span style={styles.hint}>⌘/Ctrl + Enter</span>}
          {q.default_answer != null && (
            <span style={styles.hint}>
              default on timeout:{' '}
              {Array.isArray(q.default_answer) ? q.default_answer.join(', ') : q.default_answer}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

const styles = {
  detailHead: {
    marginBottom: '0.375rem',
  } as React.CSSProperties,
  detailAgent: {
    fontSize: '1.375rem', fontWeight: 700, color: colors.textPrimary,
  } as React.CSSProperties,
  detailMeta: {
    display: 'flex', flexWrap: 'wrap' as const, gap: '0.375rem 0.875rem',
    marginTop: '0.5rem', color: colors.textSecondary, fontSize: '0.78125rem',
  } as React.CSSProperties,
  mono: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: colors.textSecondary,
  } as React.CSSProperties,
  taskLink: {
    color: colors.link, textDecoration: 'none',
  } as React.CSSProperties,
  prioText: {
    color: colors.amberLight, fontWeight: 600,
  } as React.CSSProperties,
  chips: {
    display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '0.5rem',
  } as React.CSSProperties,
  detailPrompt: {
    fontSize: '1.125rem', fontWeight: 500, lineHeight: 1.5,
    margin: '1.125rem 0 1.625rem', whiteSpace: 'pre-wrap' as const, color: colors.textPrimary,
  } as React.CSSProperties,
  answerForm: {
    maxWidth: '38.75rem',
  } as React.CSSProperties,
  options: {
    display: 'flex', flexDirection: 'column' as const, gap: '0.5rem',
  } as React.CSSProperties,
  opt: {
    display: 'flex', alignItems: 'center', gap: '0.6875rem', padding: '0.8125rem 0.9375rem',
    cursor: 'pointer', border: `1px solid ${colors.borderSubtle}`,
    borderRadius: '0.6875rem', background: colors.bgSurface,
  } as React.CSSProperties,
  optInput: {
    width: '1.0625rem', height: '1.0625rem', margin: 0, accentColor: colors.periwinkle, flexShrink: 0,
  } as React.CSSProperties,
  optText: {
    fontSize: '0.90625rem', color: colors.textPrimary,
  } as React.CSSProperties,
  textarea: {
    width: '100%', minHeight: '5.25rem', padding: '0.8125rem 0.9375rem', font: 'inherit',
    resize: 'vertical' as const, color: colors.textPrimary,
    background: colors.bgSurface, border: `1px solid ${colors.borderSubtle}`,
    borderRadius: '0.6875rem', boxSizing: 'border-box' as const,
  } as React.CSSProperties,
  actions: {
    display: 'flex', alignItems: 'center', gap: '0.875rem', marginTop: '1.125rem',
  } as React.CSSProperties,
  submitBtn: {
    padding: '0.6875rem 1.25rem', border: 0, borderRadius: '0.625rem', background: colors.periwinkle,
    color: colors.white, fontSize: '0.875rem', fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
  } as React.CSSProperties,
  hint: {
    color: colors.textSecondary, fontSize: '0.78125rem',
  } as React.CSSProperties,
};
